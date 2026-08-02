"""Retention GC: config language, ref-counted sweep, frozen facts, crash-safety.

Covers the store-core Retention contract (§9) and the Stage-4 acceptance:
config parsing (never/single/all_of/any_of + loud rejection of unknown keys),
the refcount veto (a keep-class reference protects a shared blob), the full prune
flow (candidates on both dates, frozen-facts BEFORE the tombstone, tombstone read
as ``pruned``, manifests intact, validate green), the crash window
(tombstone-present-blob-present is re-sweepable, never ``corrupt``), the debris
sweep, the builder-lock fail-fast, and the prune → rebuild carry-forward
(reconstructed ``carried+frozen``, no husks, incremental == rebuild byte-identical).

All isolation is via tempdirs / JOBHUNT_DATA_ROOT — never the real store.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
REPO_ROOT = SHARED.parents[1]
STORE_TOOLS = REPO_ROOT / "automation" / "store"
if str(STORE_TOOLS) not in sys.path:
    sys.path.insert(0, str(STORE_TOOLS))

from store import retention, serialization, validation  # noqa: E402
from store.blobs import BlobStore, CORRUPT, PRESENT, PRUNED  # noqa: E402
from store.locking import DomainLock  # noqa: E402
from store.manifest import build_envelope, iter_manifests, write_manifest  # noqa: E402
from store.paths import domain_layout  # noqa: E402
from store.retention import Filter, RetentionError  # noqa: E402

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)


def _days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


# ── config parsing ───────────────────────────────────────────
class ConfigParseTests(unittest.TestCase):
    def test_never(self):
        cfg = retention.parse_config({"tiers": {"t": {"prune_blobs_when": "never"}}})
        self.assertTrue(cfg.rule_for_tier("t").is_never)

    def test_single_filter(self):
        cfg = retention.parse_config(
            {"tiers": {"aggregator_sweeps":
                       {"prune_blobs_when": {"last_observed_older_than_days": 30}}}})
        rule = cfg.rule_for_operation("scrape")
        self.assertFalse(rule.is_never)
        self.assertTrue(rule.matches(None, _days_ago(31), NOW))
        self.assertFalse(rule.matches(None, _days_ago(10), NOW))

    def test_all_of_is_and(self):
        cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
            "prune_blobs_when": {"all_of": [
                {"posting_date_older_than_days": 90},
                {"last_observed_older_than_days": 30}]}}}})
        rule = cfg.rule_for_operation("scrape")
        self.assertTrue(rule.matches(_days_ago(100), _days_ago(40), NOW))  # both
        self.assertFalse(rule.matches(_days_ago(100), _days_ago(10), NOW))  # obs fails
        self.assertFalse(rule.matches(_days_ago(10), _days_ago(40), NOW))  # posting fails

    def test_any_of_is_or(self):
        cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
            "prune_blobs_when": {"any_of": [
                {"posting_date_older_than_days": 200},
                {"last_observed_older_than_days": 30}]}}}})
        rule = cfg.rule_for_operation("scrape")
        self.assertTrue(rule.matches(_days_ago(10), _days_ago(40), NOW))  # obs alone
        self.assertFalse(rule.matches(_days_ago(10), _days_ago(10), NOW))  # neither

    def test_unknown_filter_key_rejected_loudly(self):
        with self.assertRaises(RetentionError) as ctx:
            retention.parse_config({"tiers": {"t": {"prune_blobs_when":
                                    {"created_before_days": 5}}}})
        self.assertIn("created_before_days", str(ctx.exception))

    def test_bad_combinator_mix_rejected(self):
        with self.assertRaises(RetentionError):
            retention.parse_config({"tiers": {"t": {"prune_blobs_when": {
                "all_of": [{"posting_date_older_than_days": 1}],
                "any_of": [{"last_observed_older_than_days": 1}]}}}})

    def test_negative_days_rejected(self):
        with self.assertRaises(RetentionError):
            retention.parse_config({"tiers": {"t": {"prune_blobs_when":
                                    {"posting_date_older_than_days": -1}}}})

    def test_missing_file_is_never(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            cfg = retention.load_config(layout)  # no retention.yaml on disk
            self.assertTrue(cfg.is_opt_in_only)
            self.assertTrue(cfg.rule_for_operation("scrape").is_never)

    def test_unmentioned_tier_is_never(self):
        cfg = retention.parse_config({"tiers": {"aggregator_sweeps":
                                      {"prune_blobs_when": {"last_observed_older_than_days": 1}}}})
        # board maps to boards_and_jds, which the config never mentions → never.
        self.assertTrue(cfg.rule_for_operation("board").is_never)


# ── date helpers ─────────────────────────────────────────────
class DateHelperTests(unittest.TestCase):
    def test_parse_shapes(self):
        self.assertIsNotNone(retention.parse_dt("2026-07-18T07:24:14Z"))
        self.assertIsNotNone(retention.parse_dt("2026-07-18T07:24:14+00:00"))
        self.assertIsNotNone(retention.parse_dt("2026-07-18"))
        self.assertIsNone(retention.parse_dt(""))
        self.assertIsNone(retention.parse_dt("not-a-date"))

    def test_unknown_date_never_older(self):
        # A filter can never fire on a date we do not have (conservative keep).
        self.assertFalse(Filter("posting_date_older_than_days", 0).matches(None, NOW, NOW))


# ── synthetic-store helpers ──────────────────────────────────
def _write_fetch(layout, blobs, fetch_id, dt, *, source, operation, payload):
    ref = blobs.write(payload, "application/json")
    env = build_envelope(
        fetch_id=fetch_id, source=source, operation=operation,
        request={"url": "u"}, status=200, fetched_at=serialization.to_z(dt),
        payload=ref.as_payload("application/json"), context={"company": "examplecorp"})
    write_manifest(layout.manifest_path(source, dt, fetch_id), env)
    return ref


def _write_entity(layout, key, *, fetch_ids, posted_at, company="ExampleCorp"):
    """A minimal derived entity so the blob→entity→posting-date map resolves."""
    part = company.lower().replace(" ", "")
    entity_dir = layout.derived / "postings" / part / key
    posting = {
        "schema_version": 1, "key": key, "company": company, "title": "Engineer",
        "location": "Remote, US", "first_seen": serialization.to_z(_days_ago(120)),
        "last_seen": serialization.to_z(_days_ago(40)),
        "facts": {"posted_at": posted_at},
        "provenance": {"built_by": "test", "fetch_ids": list(fetch_ids)},
    }
    from store.atomic import atomic_write_text
    atomic_write_text(entity_dir / "posting.yaml", serialization.dumps_yaml(posting))
    return entity_dir


# ── refcount veto ────────────────────────────────────────────
class RefcountVetoTests(unittest.TestCase):
    def test_keep_class_reference_vetoes_shared_blob(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            shared = b'{"shared": 1}'
            # SAME payload referenced by a prunable scrape AND a keep-class board.
            _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                         _days_ago(40), source="jobicy", operation="scrape",
                         payload=shared)
            _write_fetch(layout, blobs, "20260701T000000Z-000002-bbbbbb",
                         _days_ago(40), source="greenhouse", operation="board",
                         payload=shared)
            cfg = retention.parse_config({"tiers": {
                "aggregator_sweeps": {"prune_blobs_when": {"last_observed_older_than_days": 0}},
                "boards_and_jds": {"prune_blobs_when": "never"}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.candidates), 0)  # board reference vetoes it
            self.assertEqual(plan.vetoed, 1)

    def test_scrape_only_blob_is_deletable(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                         _days_ago(40), source="jobicy", operation="scrape",
                         payload=b'{"only": "scrape"}')
            cfg = retention.parse_config({"tiers": {
                "aggregator_sweeps": {"prune_blobs_when": {"last_observed_older_than_days": 0}}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.candidates), 1)


# ── full prune flow ──────────────────────────────────────────
class PruneFlowTests(unittest.TestCase):
    def _store(self, td):
        layout = domain_layout(Path(td), "jobs")
        blobs = BlobStore(layout.blobs)
        # scrape blob feeding one materialized entity; posting 100d, observed 40d.
        ref = _write_fetch(layout, blobs, "20260601T000000Z-000001-aaaaaa",
                           _days_ago(40), source="jobicy", operation="scrape",
                           payload=b'{"job": 1}')
        _write_entity(layout, "url-abc123",
                      fetch_ids=["20260601T000000Z-000001-aaaaaa"],
                      posted_at=serialization.to_z(_days_ago(100)))
        return layout, blobs, ref

    def test_candidate_on_both_dates_and(self):
        with tempfile.TemporaryDirectory() as td:
            layout, blobs, ref = self._store(td)
            cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
                "prune_blobs_when": {"all_of": [
                    {"posting_date_older_than_days": 90},
                    {"last_observed_older_than_days": 30}]}}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.candidates), 1)
            c = plan.candidates[0]
            self.assertEqual(c.tier, "aggregator_sweeps")
            self.assertEqual(c.fed_entity_keys, ("url-abc123",))

    def test_and_not_yet_past_is_kept(self):
        with tempfile.TemporaryDirectory() as td:
            layout, blobs, ref = self._store(td)
            cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
                "prune_blobs_when": {"all_of": [
                    {"posting_date_older_than_days": 90},
                    {"last_observed_older_than_days": 60}]}}}})  # observed 40 < 60
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.candidates), 0)

    def test_execute_writes_frozen_then_tombstone_then_deletes(self):
        with tempfile.TemporaryDirectory() as td:
            layout, blobs, ref = self._store(td)
            manifests_before = len(list(iter_manifests(layout)))
            cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
                "prune_blobs_when": {"last_observed_older_than_days": 0}}}})
            plan, result = retention.sweep(layout, blobs, cfg, now=NOW, execute=True)
            # frozen facts written for the fed entity, and it is NOT a husk.
            frozen = retention.load_frozen_facts(layout)
            self.assertIn("url-abc123", frozen)
            self.assertTrue(frozen["url-abc123"]["entity"]["facts"]["posted_at"])
            # tombstone reads as pruned; blob gone; manifests intact.
            self.assertEqual(blobs.state(ref.sha256, "json"), PRUNED)
            self.assertIsNone(blobs.find(ref.sha256))
            self.assertEqual(len(list(iter_manifests(layout))), manifests_before)
            self.assertEqual(result.frozen_written, 1)
            self.assertEqual(result.deleted, 1)
            # validate_store stays green; pruned is an info state, not an error.
            report = validation.validate_store(Path(td))
            self.assertTrue(report.ok, report.errors)
            self.assertEqual(report.blob_states.get(PRUNED), 1)


# ── crash window ─────────────────────────────────────────────
class CrashWindowTests(unittest.TestCase):
    def test_pruned_pending_is_resweepable_never_corrupt(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            ref = _write_fetch(layout, blobs, "20260601T000000Z-000001-aaaaaa",
                               _days_ago(40), source="jobicy", operation="scrape",
                               payload=b'{"job": 1}')
            # Simulate a crash AFTER the tombstone, BEFORE the delete.
            blobs.write_tombstone(ref.sha256, reason="retention:test")
            self.assertTrue(blobs.is_pruned_pending(ref.sha256, "json"))
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)  # not CORRUPT
            self.assertNotEqual(blobs.state(ref.sha256, "json"), CORRUPT)
            # A validate run must not mis-report it as corrupt.
            report = validation.validate_store(Path(td))
            self.assertEqual(report.blob_states.get(CORRUPT, 0), 0)
            # Re-sweepable: still a candidate, and re-executing completes the delete.
            cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
                "prune_blobs_when": {"last_observed_older_than_days": 0}}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertIn(ref.sha256, [c.sha for c in plan.candidates])
            self.assertIn(ref.sha256, plan.pruned_pending)
            retention.execute_sweep(plan, blobs)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRUNED)


# ── debris sweep ─────────────────────────────────────────────
class DebrisTests(unittest.TestCase):
    def _mk_dir(self, layout, day, fetch_id, age_hours):
        import os
        d = layout.raw / "greenhouse" / "2026" / "07" / day / fetch_id
        d.mkdir(parents=True)
        (d / ".tmp-partial").write_text("junk")  # crash debris — no manifest.json
        # Anchor mtime to NOW (find_debris_dirs measures age against the passed now).
        t = NOW.timestamp() - age_hours * 3600
        os.utime(d, (t, t))
        return d

    def test_stale_reported_removed_only_on_execute_fresh_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            stale = self._mk_dir(layout, "20", "20260720T093000Z-000001-aaaaaa", 30)
            fresh = self._mk_dir(layout, "21", "20260721T093000Z-000002-bbbbbb", 2)
            plan = retention.plan_sweep(layout, blobs, retention.RetentionConfig(),
                                        now=NOW)
            reported = {d.path for d in plan.debris}
            self.assertIn(stale, reported)
            self.assertNotIn(fresh, reported)
            # dry-run leaves both on disk
            self.assertTrue(stale.is_dir())
            # execute removes only the stale one; state/ and _blobs never in scope
            retention.execute_sweep(plan, blobs)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.is_dir())


# ── builder-lock fail-fast + CLI guards ──────────────────────
class GcLockTests(unittest.TestCase):
    def test_gc_fails_fast_when_builder_lock_held(self):
        import gc_store
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            layout.state.mkdir(parents=True, exist_ok=True)
            with DomainLock(layout.lock_path()):  # a fresh, held builder lock
                rc = gc_store.main(["--data-root", td, "--execute"])
            self.assertEqual(rc, 3)

    def test_remove_orphans_requires_execute(self):  # MINOR-3
        import gc_store
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit) as ctx:
                gc_store.main(["--data-root", td, "--remove-orphans"])
            self.assertEqual(ctx.exception.code, 2)  # argparse parser.error


# ── mid-sweep capture race (MINOR-2, defense-in-depth) ───────
class MidSweepRaceTests(unittest.TestCase):
    def test_new_keep_class_reference_revetoes_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            payload = b'{"job": "shared"}'
            scrape = _write_fetch(layout, blobs, "20260601T000000Z-000001-aaaaaa",
                                  _days_ago(40), source="jobicy", operation="scrape",
                                  payload=payload)
            cfg = retention.parse_config({"tiers": {
                "aggregator_sweeps": {"prune_blobs_when": {"last_observed_older_than_days": 0}},
                "boards_and_jds": {"prune_blobs_when": "never"}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.candidates), 1)
            # A fetcher captures the SAME content under a keep-class board manifest
            # AFTER the plan (dedup → same blob sha, now referenced by a never tier).
            _write_fetch(layout, blobs, "20260701T000000Z-000002-bbbbbb",
                         _days_ago(1), source="greenhouse", operation="board",
                         payload=payload)
            result = retention.execute_sweep(plan, blobs)
            self.assertEqual(result.re_vetoed, 1)
            self.assertEqual(result.deleted, 0)
            self.assertEqual(blobs.state(scrape.sha256, "json"), PRESENT)  # survived


# ── prune → rebuild (frozen-facts carry-forward, byte-identical) ──
BUILDER = (REPO_ROOT / "skills" / "job-search" / "scripts"
           / "build_postings.py")


def _run_builder(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BUILDER), "--data-root", str(root), *args],
                          capture_output=True, text=True)


class PruneRebuildTests(unittest.TestCase):
    """End-to-end on a generated fixture (subprocess builder = clean import env)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(STORE_TOOLS))
        import generate_fixture_store as gfs
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "data"
        gfs.generate(cls.root)
        # Prune the aggregator scrape blob (aggressive, on the COPY only).
        (cls.root / "jobs" / "retention.yaml").write_text(
            "tiers:\n"
            "  aggregator_sweeps:\n"
            "    prune_blobs_when:\n"
            "      last_observed_older_than_days: 0\n"
            "  boards_and_jds:\n"
            "    prune_blobs_when: never\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _scrape_entity_keys(self, root: Path) -> list[str]:
        layout = domain_layout(root, "jobs")
        keys = []
        for key, ef in retention.build_entity_index(layout).items():
            srcs = {s.get("source") for s in (ef.entity.get("source_ids") or [])}
            if "jobicy" in srcs:
                keys.append(key)
        return sorted(keys)

    def test_prune_then_rebuild_carries_frozen_facts_no_husk(self):
        import gc_store
        root = self.tmp / "carry"
        shutil.copytree(self.root, root)
        scrape_keys = self._scrape_entity_keys(root)
        self.assertTrue(scrape_keys)
        rc = gc_store.main(["--data-root", str(root), "--execute"])
        self.assertEqual(rc, 0)
        # Frozen facts written for every materialized scrape entity.
        frozen = retention.load_frozen_facts(domain_layout(root, "jobs"))
        for k in scrape_keys:
            self.assertIn(k, frozen)
        # Remove the derived entities so ONLY frozen facts can restore them.
        postings = root / "jobs" / "derived" / "postings"
        for k in scrape_keys:
            for d in postings.rglob(k):
                shutil.rmtree(d)
        result = _run_builder(root, "--rebuild")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Reconstructed, carried+frozen, and NOT a husk.
        import yaml
        for k in scrape_keys:
            hits = list(postings.rglob(k))
            self.assertTrue(hits, f"{k} vanished (husk)")
            data = yaml.safe_load((hits[0] / "posting.yaml").read_text())
            prov = data.get("provenance") or {}
            self.assertTrue(prov.get("carried"))
            self.assertTrue(prov.get("frozen"))
            self.assertTrue(data.get("title"))
            self.assertTrue(data.get("facts"))

    def test_incremental_equals_rebuild_on_pruned_store(self):
        import gc_store
        base = self.tmp / "eqbase"
        shutil.copytree(self.root, base)
        scrape_keys = self._scrape_entity_keys(base)
        gc_store.main(["--data-root", str(base), "--execute"])
        postings = base / "jobs" / "derived" / "postings"
        for k in scrape_keys:
            for d in postings.rglob(k):
                shutil.rmtree(d)
        a, b = self.tmp / "eqA", self.tmp / "eqB"
        shutil.copytree(base, a)
        shutil.copytree(base, b)
        self.assertEqual(_run_builder(a, "--rebuild").returncode, 0)
        self.assertEqual(_run_builder(b).returncode, 0)  # incremental

        def tree(root):
            d = root / "jobs" / "derived"
            return {p.relative_to(d).as_posix(): p.read_bytes()
                    for p in sorted(d.rglob("*")) if p.is_file()}

        self.assertEqual(tree(a), tree(b))  # byte-identical


# ── partial prune: MAJOR-1 (first_seen) + MINOR-1 (marker determinism) ──
def _gh_board_payload(jid, title, location):
    return {"jobs": [{
        "id": jid, "title": title, "location": {"name": location},
        "absolute_url": f"https://boards.greenhouse.io/examplecorp/jobs/{jid}",
        "content": f"<p>Role in {location}.</p>",
        "first_published": "2026-01-01T00:00:00Z",
        "company_name": "ExampleCorp", "metadata": []}]}


def _write_board_fetch(layout, blobs, fetch_id, dt, payload):
    ref = blobs.write(serialization.dumps_json(payload).encode("utf-8"),
                      "application/json")
    env = build_envelope(
        fetch_id=fetch_id, source="greenhouse", operation="board",
        request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
        status=200, fetched_at=serialization.to_z(dt), item_count=1,
        payload=ref.as_payload("application/json"),
        context={"company": "examplecorp", "profile": "profile-01"})
    write_manifest(layout.manifest_path("greenhouse", dt, fetch_id), env)
    return ref


T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)   # old observation (blob A)
T1 = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)   # new observation (blob B)
SWEEP_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
FA = "20260101T090000Z-000001-aaaaaa"
FB = "20260620T090000Z-000002-bbbbbb"


class PartialPruneTests(unittest.TestCase):
    """A 2-blob entity where only the OLD blob is pruned (reviewer's MAJOR-1)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.base = cls.tmp / "base"
        layout = domain_layout(cls.base, "jobs")
        blobs = BlobStore(layout.blobs)
        cls.ref_a = _write_board_fetch(layout, blobs, FA, T0,
                                       _gh_board_payload("555", "Engineer", "Austin, TX"))
        cls.ref_b = _write_board_fetch(layout, blobs, FB, T1,
                                       _gh_board_payload("555", "Engineer", "Seattle, WA"))
        # Build the full 2-observation entity first (both blobs present).
        assert _run_builder(cls.base).returncode == 0
        # Prune ONLY the old blob A: boards_and_jds prunable at 100d, now=2026-06-25 →
        # A (last-observed 2026-01-01, ~175d) qualifies; B (2026-06-20, ~5d) does not.
        (cls.base / "jobs" / "retention.yaml").write_text(
            "tiers:\n  boards_and_jds:\n    prune_blobs_when:\n"
            "      last_observed_older_than_days: 100\n", encoding="utf-8")
        cfg = retention.load_config(layout)
        plan, result = retention.sweep(layout, blobs, cfg, now=SWEEP_NOW, execute=True)
        assert result.deleted == 1, (len(plan.candidates), result)
        assert blobs.state(cls.ref_a.sha256, "json") == PRUNED
        assert blobs.state(cls.ref_b.sha256, "json") == PRESENT
        cls.key = "gh-555"
        # first_seen recorded by the full build (the value pruning must not corrupt).
        import yaml
        pyaml = next((cls.base / "jobs" / "derived" / "postings").rglob("posting.yaml"))
        cls.full = yaml.safe_load(pyaml.read_text())
        assert cls.full["first_seen"] == serialization.to_z(T0)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _posting(self, root):
        import yaml
        pyaml = next((root / "jobs" / "derived" / "postings").rglob("posting.yaml"))
        return yaml.safe_load(pyaml.read_text())

    def _events(self, root):
        evs = next((root / "jobs" / "derived" / "postings").rglob("events.jsonl"))
        from store.atomic import read_jsonl
        return read_jsonl(evs)

    def test_rebuild_preserves_first_seen_and_pruned_events(self):
        root = self.tmp / "rb"
        shutil.copytree(self.base, root)
        self.assertEqual(_run_builder(root, "--rebuild").returncode, 0)
        p = self._posting(root)
        # MAJOR-1: first_seen is NOT shifted from T0 to T1 by dropping the pruned obs.
        self.assertEqual(p["first_seen"], serialization.to_z(T0))
        self.assertEqual(p["last_seen"], serialization.to_z(T1))
        prov = p.get("provenance") or {}
        self.assertTrue(prov.get("frozen"))
        self.assertTrue(prov.get("carried"))
        self.assertIn(FA, prov.get("fetch_ids", []))
        # the pruned observation's event (fetch == FA) is present, not vanished.
        fetches = {e.get("fetch") for e in self._events(root)}
        self.assertIn(FA, fetches)
        self.assertIn(FB, fetches)

    def test_byte_identical_incremental_rebuild_rebuild_twice(self):
        def tree(root):
            d = root / "jobs" / "derived"
            return {q.relative_to(d).as_posix(): q.read_bytes()
                    for q in sorted(d.rglob("*")) if q.is_file()}
        inc = self.tmp / "inc"; rb = self.tmp / "rb2"; rb2 = self.tmp / "rb2x"
        for r in (inc, rb, rb2):
            shutil.copytree(self.base, r)
        self.assertEqual(_run_builder(inc).returncode, 0)          # incremental
        self.assertEqual(_run_builder(rb, "--rebuild").returncode, 0)
        self.assertEqual(_run_builder(rb2, "--rebuild").returncode, 0)
        self.assertEqual(_run_builder(rb2, "--rebuild").returncode, 0)  # rebuild-twice
        self.assertEqual(tree(inc), tree(rb))
        self.assertEqual(tree(rb), tree(rb2))

    def test_marker_determinism_derived_present_vs_wiped(self):  # MINOR-1
        # Same store, one build with derived present, one with derived wiped → the
        # output (incl. carried/frozen markers) must be byte-identical, because the
        # merge/reconstruct source is the frozen snapshot, not the transient derived.
        present = self.tmp / "dp"; wiped = self.tmp / "dw"
        shutil.copytree(self.base, present)
        shutil.copytree(self.base, wiped)
        shutil.rmtree(wiped / "jobs" / "derived")
        self.assertEqual(_run_builder(present, "--rebuild").returncode, 0)
        self.assertEqual(_run_builder(wiped, "--rebuild").returncode, 0)

        def tree(root):
            d = root / "jobs" / "derived"
            return {q.relative_to(d).as_posix(): q.read_bytes()
                    for q in sorted(d.rglob("*")) if q.is_file()}

        self.assertEqual(tree(present), tree(wiped))
        self.assertTrue((self._posting(present).get("provenance") or {}).get("frozen"))


# ── an unreadable manifest is DAMAGE, never an absent one ────
class DamagedManifestTests(unittest.TestCase):
    """A present-but-unparseable ``manifest.json`` must never read as "no reference".

    The manifest is the ONLY record that a blob is referenced. Silently skipping an
    unreadable one turns its payload into an apparent orphan (deleted with no
    tombstone, then reported as ``not-synced-here`` — "go re-sync a file that no
    longer exists anywhere") and evaporates its keep-class veto. Residue trade:
    a suspended sweep leaves reclaimable disk on the machine; a wrong delete
    destroys bytes nothing regenerates.
    """

    def _damage(self, layout):
        """Truncate the first manifest on disk to half its bytes (a half-rsync)."""
        path = sorted(layout.raw.glob("*/**/manifest.json"))[0]
        raw = path.read_bytes()
        path.write_bytes(raw[:len(raw) // 2])
        return path

    def test_truncated_manifest_is_damage_and_its_blob_is_not_an_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            ref = _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                               _days_ago(40), source="greenhouse", operation="board",
                               payload=b'{"job": "only-copy"}')
            damaged_path = self._damage(layout)

            from store.manifest import audit_refcounts, find_damaged_manifests
            found = find_damaged_manifests(layout)
            self.assertEqual([d.path for d in found], [damaged_path])

            audit = audit_refcounts(layout, blobs)
            self.assertEqual(audit["orphans"], [])          # NOT [ref.sha256]
            self.assertTrue(audit["orphans_undetermined"])
            self.assertEqual(len(audit["damaged"]), 1)

            # No retention.yaml at all — the documented "everything never" state.
            plan = retention.plan_sweep(layout, blobs, retention.RetentionConfig(),
                                        now=NOW)
            self.assertEqual(len(plan.damaged), 1)
            self.assertEqual(plan.orphans, [])
            self.assertEqual(plan.candidates, [])

            result = retention.execute_sweep(plan, blobs, remove_orphans=True)
            self.assertEqual(result.blocked_by_damaged, 1)
            self.assertEqual(result.orphans_removed, 0)
            self.assertEqual(result.deleted, 0)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)

    def _dangle(self, layout):
        """Repoint the first manifest at a target that does not exist."""
        path = sorted(layout.raw.glob("*/**/manifest.json"))[0]
        path.unlink()
        path.symlink_to("manifest.json.gone")   # target is never created
        return path

    def test_dangling_symlink_manifest_is_damage_and_its_blob_is_not_an_orphan(self):
        """A ``manifest.json`` symlinked to a missing target is damage, not absence.

        ``Path.exists()`` FOLLOWS symlinks, so a dangling one both raises
        ``FileNotFoundError`` on read and answers ``False`` to ``exists()`` — the one
        pair that used to read as "the file genuinely is not there any more", the
        single classification with no consequences. The link is a directory entry
        that IS on disk; only its contents are unreadable. Getting this wrong made
        the blob it references look unreferenced, and the GC deleted the only copy.

        VERSION CAVEAT — reachability here is CPython-version-sensitive, so the
        assumption is pinned rather than left to a future reader. Under the previous
        ``raw.glob("*/**/manifest.json")`` traversal, whether a dangling symlink even
        REACHED the classifier depended on the interpreter (measured, not inferred):

        * 3.11.15 — NOT listed: a literal path component is matched by
          ``pathlib._PreciseSelector``, which tests ``Path.exists()``.
        * 3.12.13 — listed: ``_PreciseSelector`` is gone, and literal components are
          matched against ``os.scandir()`` entries, which include dangling links.
        * 3.13.13 — listed: glob was rewritten around ``os.path.lexists``.

        The repo floor is 3.11 and CI pins 3.12 (``.github/workflows/ci.yml``), so
        the fix could not live in ``_read_manifest`` alone — on the floor the path
        never got there. ``_iter_manifest_paths`` now walks with ``os.walk`` +
        ``os.path.lexists``, which makes this test interpreter-independent: it is
        expected to pass on 3.11, 3.12 and 3.13 alike and needs no version skip.
        """
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            ref = _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                               _days_ago(40), source="greenhouse", operation="board",
                               payload=b'{"job": "only-copy"}')
            dangling = self._dangle(layout)
            self.assertTrue(dangling.is_symlink())
            self.assertFalse(dangling.exists())   # the blind spot, stated out loud

            from store.manifest import audit_refcounts, find_damaged_manifests
            found = find_damaged_manifests(layout)
            self.assertEqual([d.path for d in found], [dangling])

            audit = audit_refcounts(layout, blobs)
            self.assertEqual(audit["orphans"], [])          # NOT [ref.sha256]
            self.assertTrue(audit["orphans_undetermined"])
            self.assertEqual(len(audit["damaged"]), 1)

            plan = retention.plan_sweep(layout, blobs, retention.RetentionConfig(),
                                        now=NOW)
            self.assertEqual(len(plan.damaged), 1)
            self.assertEqual(plan.orphans, [])
            self.assertEqual(plan.candidates, [])

            # The GC must REFUSE to collect the blob, exactly as for a truncated one.
            result = retention.execute_sweep(plan, blobs, remove_orphans=True)
            self.assertEqual(result.blocked_by_damaged, 1)
            self.assertEqual(result.orphans_removed, 0)
            self.assertEqual(result.deleted, 0)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)

    def test_live_fetch_dir_with_a_dangling_manifest_is_not_crash_debris(self):
        """The same blind spot in ``find_debris_dirs`` deletes the whole fetch dir.

        ``find_debris_dirs`` tested ``(fetch_dir / "manifest.json").exists()``, so a
        dangling manifest symlink read as "no commit marker" — crash debris — and
        ``execute_sweep`` ``rmtree``s debris past the 24h window. One broken symlink
        therefore lost the observation record as well as the blob. Manifest presence
        is a DIRECTORY-ENTRY question (``os.path.lexists``); an entry that is present
        but unreadable is damage, never debris.

        Reachability is not version-sensitive here: the fetch dir is a real directory
        listed by a wildcard glob component on every supported interpreter.
        """
        import os
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                         _days_ago(40), source="greenhouse", operation="board",
                         payload=b'{"job": "only-copy"}')
            fetch_dir = self._dangle(layout).parent
            # Genuine debris (no manifest at all) as the control: the presence test
            # must still SEE real crash debris, not just stop reporting everything.
            debris_dir = (layout.raw / "greenhouse" / "2026" / "07" / "02"
                          / "20260702T000000Z-000002-bbbbbb")
            debris_dir.mkdir(parents=True)
            (debris_dir / ".tmp-partial").write_text("junk")
            t = NOW.timestamp() - 48 * 3600          # both well past the 24h window
            for d in (fetch_dir, debris_dir):
                os.utime(d, (t, t))

            reported = {d.path for d in retention.find_debris_dirs(layout, now=NOW)}
            self.assertNotIn(fetch_dir, reported)    # live fetch — never debris
            self.assertIn(debris_dir, reported)      # control still detected

            plan = retention.plan_sweep(layout, blobs, retention.RetentionConfig(),
                                        now=NOW)
            self.assertNotIn(fetch_dir, {d.path for d in plan.debris})
            retention.execute_sweep(plan, blobs)
            self.assertTrue(fetch_dir.is_dir())
            self.assertTrue(os.path.lexists(fetch_dir / "manifest.json"))

    def test_damaged_keep_class_manifest_does_not_evaporate_its_veto(self):
        # Same fixture as test_keep_class_reference_vetoes_shared_blob, with the
        # keep-class (board) manifest damaged: the veto must survive its unreadability.
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            shared = b'{"shared": 1}'
            _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                         _days_ago(40), source="jobicy", operation="scrape",
                         payload=shared)
            ref = _write_fetch(layout, blobs, "20260701T000000Z-000002-bbbbbb",
                               _days_ago(40), source="greenhouse", operation="board",
                               payload=shared)
            board_manifest = sorted(layout.raw.glob("greenhouse/**/manifest.json"))[0]
            board_manifest.write_text('{"envelope_schema": 1, "payl', encoding="utf-8")

            cfg = retention.parse_config({"tiers": {
                "aggregator_sweeps": {"prune_blobs_when": {"last_observed_older_than_days": 0}},
                "boards_and_jds": {"prune_blobs_when": "never"}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.candidates), 0)
            result = retention.execute_sweep(plan, blobs)
            self.assertEqual(result.deleted, 0)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)

    def test_damage_appearing_after_the_plan_still_blocks_execute(self):
        # gc_store prints the whole plan for a human between plan and execute, so a
        # manifest can be half-rsynced in that window.
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            ref = _write_fetch(layout, blobs, "20260601T000000Z-000001-aaaaaa",
                               _days_ago(40), source="jobicy", operation="scrape",
                               payload=b'{"only": "scrape"}')
            cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
                "prune_blobs_when": {"last_observed_older_than_days": 0}}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.candidates), 1)
            self.assertEqual(plan.damaged, [])
            self._damage(layout)  # ← the window
            result = retention.execute_sweep(plan, blobs)
            self.assertEqual(result.blocked_by_damaged, 1)
            self.assertEqual(result.deleted, 0)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)

    def test_validate_store_reports_damage_as_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                         _days_ago(40), source="greenhouse", operation="board",
                         payload=b'{"job": 1}')
            self._damage(layout)
            report = validation.validate_store(Path(td))
            self.assertFalse(report.ok)
            self.assertTrue(any("UNREADABLE" in e for e in report.errors), report.errors)

    def test_gc_cli_exits_4_and_deletes_nothing(self):
        import gc_store
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            layout.state.mkdir(parents=True, exist_ok=True)
            blobs = BlobStore(layout.blobs)
            ref = _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                               _days_ago(40), source="greenhouse", operation="board",
                               payload=b'{"job": 1}')
            self._damage(layout)
            rc = gc_store.main(["--data-root", td, "--execute", "--remove-orphans"])
            self.assertEqual(rc, 4)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)


# ── orphan removal: re-check + tombstone (capture is lock-free) ──
class OrphanRemovalTests(unittest.TestCase):
    """Capture writes the blob BEFORE its manifest, so an in-flight fetch presents to
    the planner as exactly an orphan. ``--remove-orphans`` must re-read the reference
    set immediately before deleting, and tombstone what it does delete."""

    def test_manifest_committed_between_plan_and_execute_saves_the_blob(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            payload = b'{"fetch": "in-flight"}'
            # t0: capture-before-parse — the blob is on disk, the manifest is not.
            ref = blobs.write(payload, "application/json")
            plan = retention.plan_sweep(layout, blobs, retention.RetentionConfig(),
                                        now=NOW)
            self.assertEqual(plan.orphans, [ref.sha256])
            # t1: the fetch commits its manifest (blob write dedupes to a no-op).
            _write_fetch(layout, blobs, "20260701T000000Z-000001-aaaaaa",
                         _days_ago(1), source="greenhouse", operation="board",
                         payload=payload)
            # t2: execute — the plan says orphan, the store says referenced.
            result = retention.execute_sweep(plan, blobs, remove_orphans=True)
            self.assertEqual(result.orphans_removed, 0)
            self.assertEqual(result.orphans_re_vetoed, 1)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)

    def test_a_real_orphan_is_tombstoned_before_it_is_deleted(self):
        # A deliberately removed blob must read `pruned`, never `not-synced-here`
        # (which tells the owner to re-sync a file that no longer exists anywhere).
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            layout.raw.mkdir(parents=True, exist_ok=True)
            blobs = BlobStore(layout.blobs)
            ref = blobs.write(b'{"truly": "unreferenced"}', "application/json")
            plan = retention.plan_sweep(layout, blobs, retention.RetentionConfig(),
                                        now=NOW)
            self.assertEqual(plan.orphans, [ref.sha256])
            result = retention.execute_sweep(plan, blobs, remove_orphans=True)
            self.assertEqual(result.orphans_removed, 1)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRUNED)
            self.assertTrue(blobs.tombstone_path(ref.sha256).exists())


class DamagedDerivedEntityTests(unittest.TestCase):
    """A present-but-unparseable derived entity YAML is damage, not an absent entity.

    ``build_entity_index`` is where a blob learns which entities it feeds, i.e.
    where its keep-class veto and its posting date come from. An unreadable
    ``posting.yaml`` makes its blob look like it feeds nothing — the same shape as
    the damaged-manifest defect one class up. The sweep therefore suspends, and it
    does so with a named report rather than a raw ``ScannerError`` traceback.
    """

    def _store_with_damaged_entity(self, td):
        layout = domain_layout(Path(td), "jobs")
        blobs = BlobStore(layout.blobs)
        ref = _write_fetch(layout, blobs, "20260601T000000Z-000001-aaaaaa",
                           _days_ago(40), source="jobicy", operation="scrape",
                           payload=b'{"job": 1}')
        entity_dir = _write_entity(layout, "url-abc123",
                                   fetch_ids=["20260601T000000Z-000001-aaaaaa"],
                                   posted_at=serialization.to_z(_days_ago(100)))
        path = entity_dir / "posting.yaml"
        path.write_text("key: url-abc123\nprovenance: {fetch_ids: [\n",
                        encoding="utf-8")  # half-synced YAML
        return layout, blobs, ref, path

    def test_unparseable_entity_yaml_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as td:
            layout, blobs, _ref, path = self._store_with_damaged_entity(td)
            found = retention.find_damaged_entities(layout)
            self.assertEqual([d.path for d in found], [path])
            self.assertEqual(retention.build_entity_index(layout), {})

    def test_damaged_entity_suspends_the_sweep(self):
        with tempfile.TemporaryDirectory() as td:
            layout, blobs, ref, _path = self._store_with_damaged_entity(td)
            cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
                "prune_blobs_when": {"last_observed_older_than_days": 0}}}})
            plan = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(len(plan.damaged_entities), 1)
            self.assertEqual(plan.candidates, [])
            result = retention.execute_sweep(plan, blobs, remove_orphans=True)
            self.assertEqual(result.deleted, 0)
            self.assertEqual(result.orphans_removed, 0)
            self.assertTrue(result.blocked_by_damaged)
            self.assertEqual(blobs.state(ref.sha256, "json"), PRESENT)

    def test_gc_store_reports_the_damage_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            layout, _blobs, _ref, _path = self._store_with_damaged_entity(td)
            proc = subprocess.run(
                [sys.executable, str(STORE_TOOLS / "gc_store.py"),
                 "--data-root", str(Path(td)), "--dry-run"],
                capture_output=True, text=True)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("DAMAGED derived entities", proc.stdout)
            self.assertEqual(proc.returncode, 4)


class MultiExtensionSweepTests(unittest.TestCase):
    """Two content-types over identical bytes are ONE blob; the sweep must reclaim it."""

    def test_sweep_reclaims_both_copies_and_stops_re_listing(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            payload = b'{"job": "same bytes, two content-types"}'
            ref = _write_fetch(layout, blobs, "20260601T000000Z-000001-aaaaaa",
                               _days_ago(40), source="jobicy", operation="scrape",
                               payload=payload)
            blobs.write(payload, None)  # a second capture with no Content-Type
            self.assertEqual(len(list(layout.blobs.rglob("*.zst"))), 2)
            cfg = retention.parse_config({"tiers": {"aggregator_sweeps": {
                "prune_blobs_when": {"last_observed_older_than_days": 0}}}})
            _plan, result = retention.sweep(layout, blobs, cfg, now=NOW, execute=True)
            self.assertEqual(result.deleted, 1)
            self.assertEqual(blobs.state(ref.sha256), PRUNED)
            self.assertEqual(list(layout.blobs.rglob("*.zst")), [])
            # A second pass has nothing left to do — no forever-re-tombstoning.
            plan2 = retention.plan_sweep(layout, blobs, cfg, now=NOW)
            self.assertEqual(plan2.candidates, [])


if __name__ == "__main__":
    unittest.main()
