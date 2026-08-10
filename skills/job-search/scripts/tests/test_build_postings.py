"""Builder tests: determinism, incremental==rebuild, orphan hard-fail, suppression,
weak identity, changed events, opinions-only diff, ATS-migration links, key pinning.

Every test isolates the store to a throwaway ``JOBHUNT_DATA_ROOT`` **and** pins
``JOBHUNT_CONFIG`` to a throwaway config — no test writes into, or reads from, the
real ``private/`` tree. Pinning only the data root is not enough: every build calls
``_pin_referenced_keys``, which walks ``config.applications_root()``.
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS_DIR), str(_SCRIPTS_DIR / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_postings as bp  # noqa: E402
import config  # vendored toolkit config loader  # noqa: E402
import postings_fold_state as fold_state  # noqa: E402
from _vendor.store import serialization  # noqa: E402
from _vendor.store.atomic import atomic_write_text, read_jsonl  # noqa: E402
from _vendor.store.capture import CaptureSession  # noqa: E402
from _vendor.store.paths import domain_layout  # noqa: E402
from _vendor.store.validation import validate_store  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PRIVATE_DATA = _REPO_ROOT / "private" / "data"
UTC = timezone.utc


def _gh_board(jobs):
    return json.dumps({"jobs": jobs}).encode()


def _dt(day, hour=9):
    return datetime(2026, 7, day, hour, 0, 0, tzinfo=UTC)


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.get("JOBHUNT_DATA_ROOT")
        self._prior_config = os.environ.get(config.ENV_VAR)
        self.data_root = Path(tempfile.mkdtemp(prefix="build-test-"))
        self._pre_build = Path(tempfile.mkdtemp(prefix="pre-build-")) / "data"
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.data_root)
        # Pin the CONFIG too, not just the store. `_pin_referenced_keys` runs on
        # every build path and rglobs `config.applications_root()` for `store_key`
        # references — so on a configured machine a suite that pinned only the data
        # root would walk the owner's real applications tree on every build. It is
        # read-only, but a test suite must not touch the private tree at all.
        apps = self.data_root / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        cfg = self.data_root / "config.yaml"
        cfg.write_text('candidate:\n  name: "Jordan Rivers"\n'
                       f'paths:\n  applications_root: "{apps}"\n'
                       f'  discoveries_dir: "{apps}/1_discoveries"\n', encoding="utf-8")
        os.environ[config.ENV_VAR] = str(cfg)
        config._load.cache_clear()  # the loader caches for the process lifetime
        self.assertEqual(config.applications_root(), apps,
                         "test config not pinned — builds would read the real tree")
        self.layout = domain_layout(self.data_root, "jobs")

    def tearDown(self):
        for var, prior in (("JOBHUNT_DATA_ROOT", self._prior),
                           (config.ENV_VAR, self._prior_config)):
            if prior is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prior
        config._load.cache_clear()
        shutil.rmtree(self.data_root, ignore_errors=True)
        shutil.rmtree(self._pre_build.parent, ignore_errors=True)

    def _session(self):
        return CaptureSession("jobs", self.data_root, tool_version="test")

    # ── incremental == rebuild, proved against an INDEPENDENT rebuild ──
    def _tree_bytes(self, root):
        out = {}
        for p in sorted(Path(root).rglob("*")):
            if p.is_file():
                out[str(p.relative_to(root))] = p.read_bytes()
        return out

    def _snapshot_pre_build(self):
        """Keep the generation the next build starts FROM.

        ``_assert_matches_rebuild`` rebuilds this clone in a store of its own, so
        the rebuild's carry-forward input is the generation that existed *before*
        the incremental run — never the incremental run's own output.
        """
        shutil.rmtree(self._pre_build, ignore_errors=True)
        shutil.copytree(self.data_root, self._pre_build)

    def _assert_matches_rebuild(self, *extra_argv):
        """Require the last incremental build to equal an independent rebuild.

        Rebuilding IN PLACE proves nothing for the entities this optimization
        exists for. ``_carry_forward`` (``_load_existing_entity``) and
        ``_reconstruct_from_frozen`` read ``derived/<key>/posting.yaml`` — so an
        in-place rebuild reads the incremental run's OWN output and copies it
        forward, and the assertion compares every carried and frozen entity to
        itself. Byte-identical-to-rebuild is the contract the whole O(new)
        optimization rests on, so the rebuild has to start from the same input
        the incremental build did: a clone of the pre-build generation, built in
        a data root of its own.
        """
        parent = Path(tempfile.mkdtemp(prefix="rebuild-"))
        try:
            rebuilt = parent / "data"
            shutil.copytree(self._pre_build, rebuilt)
            self.assertEqual(
                bp.main(["--data-root", str(rebuilt), "--rebuild", *extra_argv]), 0)
            rb = domain_layout(rebuilt, "jobs")
            self.assertEqual(self._tree_bytes(self.layout.derived),
                             self._tree_bytes(rb.derived),
                             "derived: incremental != rebuild")
            self.assertEqual(self._tree_bytes(self.layout.index),
                             self._tree_bytes(rb.index),
                             "index: incremental != rebuild")
        finally:
            shutil.rmtree(parent, ignore_errors=True)

    def _capture_gh(self, jobs, dt, company="examplecorp"):
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"},
            status=200, payload_bytes=_gh_board(jobs), content_type="application/json",
            fetched_at=dt, context={"company": company, "profile": "profile-01"})

    def _capture_scrape(self, source, payload, dt):
        self._session().capture_fetch(
            source=source, operation="scrape",
            request={"url": f"https://{source}.example/api"},
            status=200, payload_bytes=json.dumps(payload).encode(),
            content_type="application/json", fetched_at=dt,
            context={"profile": "profile-01"})

    # One JD shared by two boards — the content that puts two keys in one
    # `_post_pass` duplicate bucket.
    DUP_JD = "Own the ingestion pipeline end to end. Kafka, Flink, and Iceberg."

    def _capture_ashby(self, company, jid, title, dt, jd):
        payload = {"apiVersion": "1", "jobs": [{
            "id": jid, "title": title, "location": "Remote, US",
            "jobUrl": f"https://jobs.ashbyhq.com/{company}/{jid}",
            "descriptionPlain": jd, "publishedAt": "2026-07-15T00:00:00Z",
            "isListed": True}]}
        self._session().capture_fetch(
            source="ashby", operation="board",
            request={"url": f"https://api.ashbyhq.com/posting-api/job-board/{company}"},
            status=200, payload_bytes=json.dumps(payload).encode(),
            content_type="application/json", fetched_at=dt,
            context={"company": company, "profile": "profile-01"})

    def _capture_aggregator_row(self, company_name, title, dt, jid=7):
        """One aggregator row — the capture shape that carries NO context company.

        The partition is then derived from the row's own ``companyName``, which the
        aggregator can change between sweeps while the URL-derived key stays put.
        """
        self._capture_scrape("jobicy", {"jobs": [{
            "id": jid, "url": f"https://jobicy.com/jobs/{jid}-backend",
            "jobTitle": title, "companyName": company_name,
            "jobGeo": "Remote, USA", "jobDescription": "Own the ingestion pipeline.",
            "pubDate": "2026-07-12"}]}, dt)

    def _partitions(self):
        root = self.layout.derived / "postings"
        return sorted(p.name for p in root.iterdir()) if root.is_dir() else []

    def _annotate(self, key, facts):
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.layout.annotations / f"{key}.yaml",
                          serialization.dumps_yaml(
                              {"schema_version": 1, "key": key,
                               "verified_by": "human", "facts": facts}))

    def _capture_workday(self, req, company_slug, dt, host="acme.wd5.myworkdayjobs.com",
                         site="Careers"):
        payload = {"jobPostings": [{
            "title": "Platform Engineer",
            "externalPath": f"/en-US/{site}/job/Loc/PE_{req}",
            "locationsText": "Santa Clara, CA", "bulletFields": [req]}]}
        self._session().capture_fetch(
            source="workday", operation="search",
            request={"url": f"https://{host}/wday/cxs/acme/{site}"},
            status=200, payload_bytes=json.dumps(payload).encode(),
            content_type="application/json", fetched_at=dt,
            context={"company": company_slug, "profile": "profile-01"})

    def _build(self, argv):
        self._snapshot_pre_build()
        return bp.main(argv + ["--data-root", str(self.data_root)])

    def _summary(self, argv=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self._build(argv or [])
        self.assertEqual(rc, 0, buf.getvalue())
        return buf.getvalue()

    def _cache(self):
        return fold_state.cache_path(self.layout)

    def _index_keys(self):
        rows = [json.loads(l) for l in
                (self.layout.index / "postings.jsonl").read_text().splitlines()][1:]
        return {r["key"] for r in rows}

    def _index_rows(self):
        return [json.loads(l) for l in
                (self.layout.index / "postings.jsonl").read_text().splitlines()][1:]

    def _posting(self, partition, key):
        return serialization.loads_yaml((self.layout.derived / "postings" / partition
                                         / key / "posting.yaml").read_text())

    def _delete_blob_for(self, key):
        from _vendor.store.resolver import load_entity, resolve_blob
        from _vendor.store.blobs import BlobStore
        _p, entity = load_entity(self.layout, key)
        payload = resolve_blob(self.layout, entity)
        BlobStore(self.layout.blobs).find(payload["blob"]).unlink()

    def _truncate_newest_blob(self):
        """Half-copy the newest blob — exactly what an interrupted rsync leaves.

        The file stays in ``present_shas()`` (the name is intact), so nothing in
        the store's absence bookkeeping moves; only ``BlobStore.read`` can tell.
        """
        blobs = sorted(Path(self.layout.blobs).rglob("*.zst"),
                       key=lambda p: p.stat().st_mtime)
        target = blobs[-1]
        data = target.read_bytes()
        target.write_bytes(data[:len(data) // 2])
        return target

    def _freeze_and_prune(self, partition, key, *, prune=True):
        """Do what the retention GC does: snapshot the entity, then prune its blob."""
        from _vendor.store import retention
        entity_dir = self.layout.derived / "postings" / partition / key
        entity = serialization.loads_yaml(
            (entity_dir / "posting.yaml").read_text(encoding="utf-8"))
        ef = retention.EntityFacts(
            key=key, entity_dir=entity_dir, entity_yaml=entity_dir / "posting.yaml",
            entity=entity, posted_at=None,
            fetch_ids=tuple((entity.get("provenance") or {}).get("fetch_ids") or ()))
        retention.write_frozen_facts(self.layout, retention.snapshot_entity(ef))
        if prune:
            self._delete_blob_for(key)

    def _drop_raw_and_derived(self):
        """Simulate a checkout that only has the committed index/state locally.

        Mirrors the real incident: ``raw/`` + ``derived/`` are gitignored and never
        reached this machine, while ``index/`` + ``state/`` are committed history.
        """
        shutil.rmtree(self.layout.raw, ignore_errors=True)
        shutil.rmtree(self.layout.derived, ignore_errors=True)

    def _index_rows_at(self, root):
        idx = domain_layout(root, "jobs").index / "postings.jsonl"
        return [json.loads(l) for l in idx.read_text().splitlines()][1:]


# fictional greenhouse jobs
def _job(jid, title, loc, content="Build things"):
    return {"id": jid, "title": title, "location": {"name": loc},
            "absolute_url": f"https://boards.greenhouse.io/examplecorp/jobs/{jid}",
            "content": content, "first_published": "2026-07-10T00:00:00Z",
            "company_name": "ExampleCorp", "metadata": []}


class MaterializeTests(_StoreCase):
    def test_build_materializes_validates_and_pins(self):
        self._capture_gh([_job(111, "Software Engineer", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        # annotation for gh-111 -> must pin
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.layout.annotations / "gh-111.yaml",
                          serialization.dumps_yaml({"schema_version": 1, "key": "gh-111",
                                                    "verified_by": "human",
                                                    "facts": {"workplace": "onsite"}}))
        rc = self._build([])
        self.assertEqual(rc, 0)
        report = validate_store(self.data_root)
        self.assertTrue(report.ok, report.errors)
        entity = self.layout.derived / "postings" / "examplecorp" / "gh-111" / "posting.yaml"
        self.assertTrue(entity.exists())
        data = serialization.loads_yaml(entity.read_text())
        self.assertEqual(data["company"], "examplecorp")
        self.assertEqual(data["identity"], "strong")
        self.assertIn("visa", data["opinions"])
        # key registry pinned on the annotation join
        reg = serialization.loads_yaml(self.layout.key_registry.read_text())
        self.assertTrue(reg["keys"]["gh-111"]["pinned"])

    def test_no_writes_reach_private_data(self):
        def _files():
            if not _PRIVATE_DATA.is_dir():
                return set()
            return {str(p) for p in _PRIVATE_DATA.rglob("*") if p.is_file()}
        before = _files()
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self._build([])
        self.assertEqual(_files(), before)
        # …and nothing is READ from it either: the key-pinning walk follows the
        # pinned config's applications root, which must live in the temp store.
        for path in (config.applications_root(), config.discoveries_dir()):
            self.assertFalse(str(path).startswith(str(_REPO_ROOT / "private")), path)
            self.assertTrue(str(path).startswith(str(self.data_root)), path)


class SuppressionAndWeakTests(_StoreCase):
    SCRAPE = {"jobs": [
        {"id": 1, "url": "https://jobicy.com/jobs/1-us", "jobTitle": "US Backend",
         "companyName": "UsCo", "jobGeo": "USA", "jobDescription": "d",
         "pubDate": "2026-07-12"},
        {"id": 2, "url": "https://jobicy.com/jobs/2-lon", "jobTitle": "UK Backend",
         "companyName": "UkCo", "jobGeo": "London, United Kingdom",
         "jobDescription": "d", "pubDate": "2026-07-12"},
        {"id": 3, "url": "", "jobTitle": "Weak Row", "companyName": "GhostCo",
         "jobGeo": "United States", "jobDescription": "d", "pubDate": "2026-07-12"},
    ]}

    def test_foreign_scrape_suppressed_weak_materialized(self):
        self._capture_scrape("jobicy", self.SCRAPE, _dt(14))
        self.assertEqual(self._build([]), 0)
        # suppressed queue carries the foreign row + the raw manifest path
        triage = list((self.layout.index / "triage").glob("*.jsonl"))
        self.assertEqual(len(triage), 1)
        rows = [json.loads(l) for l in triage[0].read_text().splitlines()][1:]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["gate"], "structural_foreign_location")
        self.assertTrue(rows[0]["manifest"].endswith("manifest.json"))
        # the no-url row materializes as a WEAK content-keyed entity
        idx = [json.loads(l) for l in
               (self.layout.index / "postings.jsonl").read_text().splitlines()][1:]
        weak = [r for r in idx if r.get("identity") == "weak"]
        self.assertEqual(len(weak), 1)
        self.assertTrue(weak[0]["key"].startswith("ck-"))
        # US rows are NOT suppressed
        self.assertEqual(len({r["key"] for r in idx}), 2)


class DeterminismTests(_StoreCase):
    def test_staged_incremental_equals_rebuild(self):
        # stage 1: day-14 board
        self._capture_gh([_job(111, "SWE", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        # stage 2: day-15 board — gh-111 changed location (Austin -> Seattle)
        self._capture_gh([_job(111, "SWE", "Seattle, WA"),
                          _job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build([]), 0)

        # A rebuild of the SAME input, in a store of its own, must be byte-identical.
        self._assert_matches_rebuild()

        # rebuild again — byte-identical to the first rebuild
        self.assertEqual(self._build(["--rebuild"]), 0)
        rb1_d = self._tree_bytes(self.layout.derived)
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertEqual(self._tree_bytes(self.layout.derived), rb1_d,
                         "derived: rebuild != rebuild")

    def test_changed_event_recorded(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(15))
        self.assertEqual(self._build([]), 0)
        events_path = (self.layout.derived / "postings" / "examplecorp" / "gh-111"
                       / "events.jsonl")
        events = [json.loads(l) for l in events_path.read_text().splitlines()]
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "first_seen")
        changed = [e for e in events if e["type"] == "changed"]
        self.assertEqual(len(changed), 1)
        fields = {c["field"] for c in changed[0]["changes"]}
        self.assertIn("location", fields)


class IncrementalFoldTests(_StoreCase):
    """The O(new) fold: it must reach every entity a full fold would have changed.

    Each test here compares the incremental result against a full ``--rebuild`` of
    the same raw zone byte-for-byte, and several deliberately arrange for a NEW
    manifest to change an entity that manifest never mentions — the failure mode a
    "only touch what the delta names" optimization invites.
    """

    # ── the fast path runs at all ──
    def test_second_build_folds_pending_only(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertIn("fold=full", self._summary())
        self.assertTrue(self._cache().exists())
        self._capture_gh([_job(111, "SWE", "Seattle, WA"),
                          _job(222, "SRE", "Remote, US")], _dt(15))
        out = self._summary()
        self.assertIn("fold=pending-only", out)
        self._assert_matches_rebuild()

    # ── an entity that changes company MOVES; it must not fork ──
    def test_a_company_rename_moves_the_derived_dir_instead_of_forking_it(self):
        """One key, two partitions is a store a ``--rebuild`` cannot produce.

        The aggregator renames the company between sweeps; the URL-derived key does
        not move, so the entity belongs at a new partition. A writer that only ever
        writes leaves BOTH — a duplicate posting with a frozen ``last_seen``, which
        ``validate_store`` still calls ok.
        """
        self._capture_aggregator_row("Zeta Corp", "Backend Engineer", _dt(14))
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._partitions(), ["zeta-corp"])

        self._capture_aggregator_row("Alpha Labs", "Senior Backend Engineer", _dt(15))
        self.assertIn("fold=pending-only", self._summary())
        self.assertEqual(self._partitions(), ["alpha-labs"])
        self._assert_matches_rebuild()

    def test_a_company_rename_moves_the_derived_dir_on_the_full_fold_too(self):
        """The same defect on the fallback path — it is not a fast-path artifact."""
        self._capture_aggregator_row("Zeta Corp", "Backend Engineer", _dt(14))
        self.assertEqual(self._build([]), 0)
        self._cache().unlink()                       # force the whole-raw-zone fold
        self._capture_aggregator_row("Alpha Labs", "Senior Backend Engineer", _dt(15))
        self.assertIn("fold=full", self._summary())
        self.assertEqual(self._partitions(), ["alpha-labs"])
        self._assert_matches_rebuild()

    def test_a_key_at_two_partitions_refuses_the_fast_path(self):
        """The cache holds ONE partition per key, so key sets cannot see a fork."""
        self._capture_aggregator_row("Zeta Corp", "Backend Engineer", _dt(14))
        self.assertEqual(self._build([]), 0)
        entity = next((self.layout.derived / "postings" / "zeta-corp").iterdir())
        shutil.copytree(entity, self.layout.derived / "postings" / "usco-inc"
                        / entity.name)
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(15))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(self._build([]), 0)
        self.assertIn("fold=full", out.getvalue())
        self.assertIn("derived zone no longer matches", err.getvalue())
        # …and the full fold that follows heals the fork.
        self.assertEqual(self._partitions(), ["examplecorp", "zeta-corp"])

    # ── the cross-entity reduction: a new manifest changing an OLD entity ──
    def test_new_manifest_stamps_duplicate_hint_on_an_untouched_entity(self):
        """The regression this optimization invites: an entity nobody re-observed.

        The greenhouse posting is NOT in the second build's pending manifest, yet a
        full fold would stamp ``possible_duplicate`` on it because the ashby posting
        landed in its bucket. Folding only the delta's own keys would silently skip
        it.
        """
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
            status=200,
            payload_bytes=_gh_board([_job(900, "Staff Engineer", "Remote, US",
                                          content=self.DUP_JD)]),
            content_type="application/json", fetched_at=_dt(14),
            context={"company": "examplecorp", "profile": "profile-01"})
        self.assertEqual(self._build([]), 0)
        self.assertNotIn("possible_duplicate", self._posting("examplecorp", "gh-900"))

        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(16),
                            self.DUP_JD)
        self.assertIn("fold=pending-only", self._summary())
        gh = self._posting("examplecorp", "gh-900")
        ashby = self._posting("examplecorp", "ashby-ay-1")
        self.assertEqual(gh.get("possible_duplicate"), ["ashby-ay-1"])
        self.assertEqual(ashby.get("possible_duplicate"), ["gh-900"])
        self._assert_matches_rebuild()

    def _capture_dup_pair(self):
        """One posting cross-listed on greenhouse and ashby — one duplicate bucket."""
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
            status=200,
            payload_bytes=_gh_board([_job(900, "Staff Engineer", "Remote, US",
                                          content=self.DUP_JD)]),
            content_type="application/json", fetched_at=_dt(14),
            context={"company": "examplecorp", "profile": "profile-01"})
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(15),
                            self.DUP_JD)
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._posting("examplecorp", "gh-900")["possible_duplicate"],
                         ["ashby-ay-1"])
        self.assertEqual(self._posting("examplecorp", "ashby-ay-1")["possible_duplicate"],
                         ["gh-900"])

    def test_annotating_half_a_duplicate_pair_keeps_both_hints(self):
        """The two reach mechanisms INTERSECTING — each is fine alone.

        ``gh-900`` joins the working set only because it is an annotation target:
        no manifest mentions it, and it is not a duplicate participant of anything
        this run folded. It is loaded with its hints STRIPPED so they can be
        re-derived — but ``_post_pass`` only re-derives from whole buckets, and its
        bucket mate is not in the working set. Without `_bucket_closure` the hint is
        not re-stamped, it is silently DELETED, leaving an asymmetric pair only a
        ``--rebuild`` repairs.
        """
        self._capture_dup_pair()
        self._annotate("gh-900", {"workplace": "onsite"})
        self.assertIn("fold=pending-only", self._summary())   # zero-pending fast path
        self.assertEqual(self._posting("examplecorp", "gh-900")["possible_duplicate"],
                         ["ashby-ay-1"])
        self.assertEqual(self._posting("examplecorp", "ashby-ay-1")["possible_duplicate"],
                         ["gh-900"])
        self._assert_matches_rebuild()

    def test_removing_an_annotation_from_half_a_pair_keeps_both_hints(self):
        """The same intersection down the OTHER reach: the ``ann_keys`` undo path."""
        self._capture_dup_pair()
        self._annotate("gh-900", {"workplace": "onsite"})
        self.assertEqual(self._build([]), 0)
        (self.layout.annotations / "gh-900.yaml").unlink()
        self.assertIn("fold=pending-only", self._summary())
        gh = self._posting("examplecorp", "gh-900")
        self.assertNotIn("human", gh)                          # the undo happened…
        self.assertEqual(gh["possible_duplicate"], ["ashby-ay-1"])  # …and only that
        self._assert_matches_rebuild()

    def test_departing_entity_clears_a_stale_duplicate_hint(self):
        """The mirror case: a bucket EMPTIES and the leftover hint must disappear."""
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
            status=200,
            payload_bytes=_gh_board([_job(900, "Staff Engineer", "Remote, US",
                                          content=self.DUP_JD)]),
            content_type="application/json", fetched_at=_dt(14),
            context={"company": "examplecorp", "profile": "profile-01"})
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(15),
                            self.DUP_JD)
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._posting("examplecorp", "gh-900")["possible_duplicate"],
                         ["ashby-ay-1"])
        # The ashby JD is rewritten — the pair is no longer a content duplicate, so
        # the greenhouse entity (untouched by this fetch) must lose its hint.
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(17),
                            "Completely different role: run the billing platform.")
        self.assertIn("fold=pending-only", self._summary())
        self.assertNotIn("possible_duplicate", self._posting("examplecorp", "gh-900"))
        self._assert_matches_rebuild()

    def test_new_annotation_reaches_an_unobserved_entity(self):
        """A human annotation lands with no new fetch for the entity it annotates."""
        self._capture_gh([_job(111, "SWE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.layout.annotations / "gh-111.yaml",
                          serialization.dumps_yaml({"schema_version": 1, "key": "gh-111",
                                                    "verified_by": "human",
                                                    "facts": {"workplace": "onsite"}}))
        self._capture_gh([_job(222, "SRE", "Austin, TX")], _dt(15))
        self.assertIn("fold=pending-only", self._summary())
        p = self._posting("examplecorp", "gh-111")
        self.assertEqual(p["opinions"]["workplace"]["effective"], "onsite")
        row = [r for r in self._index_rows() if r["key"] == "gh-111"][0]
        self.assertEqual(row["workplace"], "onsite")
        self._assert_matches_rebuild()

    def test_removed_annotation_is_undone_on_an_unobserved_entity(self):
        self._capture_gh([_job(111, "SWE", "Remote, US")], _dt(14))
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        ann = self.layout.annotations / "gh-111.yaml"
        atomic_write_text(ann, serialization.dumps_yaml(
            {"schema_version": 1, "key": "gh-111", "verified_by": "human",
             "facts": {"workplace": "onsite"}}))
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._posting("examplecorp", "gh-111")
                         ["opinions"]["workplace"]["effective"], "onsite")
        ann.unlink()
        self._capture_gh([_job(222, "SRE", "Austin, TX")], _dt(15))
        self.assertIn("fold=pending-only", self._summary())
        p = self._posting("examplecorp", "gh-111")
        self.assertNotIn("human", p)
        self.assertNotIn("effective", p["opinions"]["workplace"])
        self._assert_matches_rebuild()

    # ── multi-stage histories, including JD versions and suppressed rows ──
    def test_many_staged_builds_equal_one_rebuild(self):
        jd_a = "Build the control plane. Kubernetes at scale."
        jd_b = "Build the control plane. Now with Rust and eBPF."
        self._capture_gh([_job(111, "SWE", "Austin, TX", content=jd_a),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        # stage 2: gh-111's JD text changes -> a `changed` event + a jd-<hash>.md
        self._capture_gh([_job(111, "SWE", "Austin, TX", content=jd_b),
                          _job(222, "SRE", "Remote, US")], _dt(15))
        self.assertIn("fold=pending-only", self._summary())
        # stage 3: a brand-new posting appears; gh-222 is not listed at all
        self._capture_gh([_job(111, "SWE", "Seattle, WA", content=jd_b),
                          _job(333, "Data Engineer", "NYC, NY")], _dt(16))
        self.assertIn("fold=pending-only", self._summary())
        # stage 4: an aggregator scrape adds a weak-identity row AND a suppressed row
        self._capture_scrape("jobicy", SuppressionAndWeakTests.SCRAPE, _dt(17))
        self.assertIn("fold=pending-only", self._summary())

        jd_versions = list((self.layout.derived / "postings" / "examplecorp"
                            / "gh-111").glob("jd-*.md"))
        self.assertEqual(len(jd_versions), 1, "prior JD version not snapshotted")
        triage = list((self.layout.index / "triage").glob("*.jsonl"))
        self.assertEqual(len(triage), 1)
        self._assert_matches_rebuild()

    def test_reached_entity_keeps_its_continuable_fold(self):
        """Being pulled in for a hint or an annotation must not cost the fast path.

        An entity reached by the duplicate pass is loaded from disk, not folded, so
        rebuilding its cache entry from that load would drop its fold state and
        condemn it to forcing a full fold on every later build that touches it.
        """
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
            status=200,
            payload_bytes=_gh_board([_job(900, "Staff Engineer", "Remote, US",
                                          content=self.DUP_JD)]),
            content_type="application/json", fetched_at=_dt(14),
            context={"company": "examplecorp", "profile": "profile-01"})
        self.assertEqual(self._build([]), 0)
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(16),
                            self.DUP_JD)
        self.assertIn("fold=pending-only", self._summary())   # gh-900 gets reached
        # gh-900 is now re-observed. If its cache entry lost the fold state, this
        # build would fall back to a full fold instead of continuing it.
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
            status=200,
            payload_bytes=_gh_board([_job(900, "Staff Engineer", "Austin, TX",
                                          content=self.DUP_JD)]),
            content_type="application/json", fetched_at=_dt(18),
            context={"company": "examplecorp", "profile": "profile-01"})
        self.assertIn("fold=pending-only", self._summary())
        self._assert_matches_rebuild()

    def test_repeated_no_op_builds_are_stable(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        before = self._tree_bytes(self.layout.index)
        for _ in range(3):
            self.assertEqual(self._build([]), 0)
        self.assertEqual(self._tree_bytes(self.layout.index), before)
        self._assert_matches_rebuild()

    # ── refusals: every one must still produce the rebuild's bytes ──
    def test_out_of_order_capture_falls_back_to_a_full_fold(self):
        """A backfilled/clock-skewed fetch may not be appended to a finished fold."""
        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(16))
        self.assertEqual(self._build([]), 0)
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))  # EARLIER capture
        out = self._summary()
        self.assertIn("fold=full", out)
        events_path = (self.layout.derived / "postings" / "examplecorp" / "gh-111"
                       / "events.jsonl")
        events = [json.loads(ln) for ln in events_path.read_text().splitlines()]
        self.assertEqual(events[0]["at"], "2026-07-14T09:00:00Z")  # re-ordered fold
        self._assert_matches_rebuild()

    def test_per_entity_order_check_is_independent_of_the_global_one(self):
        """The fold's own stop point is re-checked, not just the manifest bound.

        Forcing one entity's recorded stop point past the incoming capture is the
        only way to exercise the per-entity guard, because the whole-store bound
        in `_fast_plan` is strictly the stronger of the two in normal operation.
        A build that appended here anyway would emit different `changed` events
        than a rebuild — the silent corruption this whole design guards against.
        """
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        path = self._cache()
        lines = path.read_text().splitlines()
        rows = [json.loads(ln) for ln in lines]
        for row in rows[1:]:
            if row["k"] == "gh-111":
                row["f"]["l"] = ["2099-01-01T00:00:00Z", "zzzz"]
        path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(15))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = self._build([])
        self.assertEqual(rc, 0)
        self.assertIn("fold=full", out.getvalue())
        self.assertIn("out of order", err.getvalue())
        self._assert_matches_rebuild()

    def test_missing_cache_falls_back(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self._cache().unlink()
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertIn("fold=full", self._summary())
        self._assert_matches_rebuild()

    def test_truncated_cache_falls_back(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        path = self._cache()
        path.write_text(path.read_text().splitlines()[0] + "\n")  # header only
        self._capture_gh([_job(333, "Data Engineer", "NYC, NY")], _dt(15))
        self.assertIn("fold=full", self._summary())
        self._assert_matches_rebuild()

    def test_classifier_change_re_derives_every_entity(self):
        """A code fingerprint change must reach postings no fetch has touched."""
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        path = self._cache()
        lines = path.read_text().splitlines()
        header = json.loads(lines[0])
        header["fingerprint"]["visa"] = "visa.py@deadbeef"
        path.write_text("\n".join([json.dumps(header, sort_keys=True)] + lines[1:])
                        + "\n")
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertIn("fold=full", self._summary())
        self._assert_matches_rebuild()

    def test_dropped_derived_falls_back(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        shutil.rmtree(self.layout.derived / "postings" / "examplecorp" / "gh-111")
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertIn("fold=full", self._summary())
        self._assert_matches_rebuild()

    def test_a_manifest_replaced_in_place_falls_back(self):
        """The refusal table promises this; a bare fetch-id digest cannot see it.

        Raw is contractually append-only, so a manifest rewritten with the same
        ``fetch_id`` and a different ``payload.blob`` is out-of-contract — but the
        table says "a manifest was removed, or the raw zone was not synced" is
        detected, and this was neither detected nor folded: the replaced manifest
        is not pending, so its new rows never reached derived at all.
        """
        from _vendor.store.blobs import BlobStore
        from _vendor.store.manifest import iter_manifests

        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._index_keys(), {"gh-111"})

        path, env = next(iter(iter_manifests(self.layout)))
        before = env["payload"]["blob"]
        ref = BlobStore(self.layout.blobs).write(
            _gh_board([_job(111, "SWE", "Austin, TX"),
                       _job(333, "Data Engineer", "NYC, NY")]), "application/json")
        self.assertNotEqual(ref.sha256, before)
        env["payload"] = ref.as_payload("application/json")
        atomic_write_text(path, serialization.dumps_json(env))

        self._capture_gh([_job(444, "Platform Engineer", "Remote, US")], _dt(15))
        self.assertIn("fold=full", self._summary())
        self.assertEqual(self._index_keys(), {"gh-111", "gh-333", "gh-444"})
        self._assert_matches_rebuild()

    def test_a_deleted_event_log_falls_back(self):
        """``posting.yaml`` alone is not "this entity's derived is intact".

        ``_resume_fold`` reads ``events.jsonl`` too, so a deleted one silently
        truncated the entity's whole event history: the resumed fold started from
        an empty list and ``by-day/`` lost every earlier day, with no refusal.
        """
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(15))
        self.assertEqual(self._build([]), 0)
        entity = self.layout.derived / "postings" / "examplecorp" / "gh-111"
        before = [e["type"] for e in read_jsonl(entity / "events.jsonl")]
        self.assertEqual(before, ["first_seen", "seen", "changed"])

        (entity / "events.jsonl").unlink()
        self._capture_gh([_job(111, "SWE", "Denver, CO")], _dt(16))
        self.assertIn("fold=full", self._summary())
        self.assertEqual([e["type"] for e in read_jsonl(entity / "events.jsonl")],
                         before + ["seen", "changed"])
        self.assertEqual(sorted(p.stem for p in
                                (self.layout.index / "by-day").glob("*.jsonl")),
                         ["2026-07-14", "2026-07-15", "2026-07-16"])
        self._assert_matches_rebuild()

    def test_ledger_ahead_of_cache_falls_back(self):
        """A crash between the derived/index writes and the cache write."""
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        stale = self._cache().read_text()
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build([]), 0)
        self._cache().write_text(stale)          # cache rolled back, store did not
        self._capture_gh([_job(333, "Data Engineer", "NYC, NY")], _dt(16))
        self.assertIn("fold=full", self._summary())
        self._assert_matches_rebuild()

    def test_a_killed_zero_pending_build_is_detected(self):
        """The crash window no header digest can see.

        The ledger only moves when a manifest is recorded, so a build with ZERO
        pending manifests — exactly what applying a human annotation is — leaves
        every digest in the header unchanged. Killed between the derived writes and
        the cache write, it would otherwise be invisible, and the next run would
        compute its annotation-undo reach from a record that predates the derived
        zone it is supposed to correct: the removed annotation is never undone, and
        the index keeps serving a human fact that exists nowhere in the store.
        """
        self._capture_gh([_job(111, "SWE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self._annotate("gh-111", {"workplace": "onsite"})

        class _Killed(Exception):
            """Stands in for SIGKILL: the cache is the build's last write."""

        real_save = fold_state.save
        fold_state.save = lambda *a, **k: (_ for _ in ()).throw(_Killed())
        try:
            with self.assertRaises(_Killed):
                self._build([])
        finally:
            fold_state.save = real_save
        # derived moved; the cache still describes the generation before it
        self.assertEqual(self._posting("examplecorp", "gh-111")
                         ["opinions"]["workplace"]["effective"], "onsite")

        (self.layout.annotations / "gh-111.yaml").unlink()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(self._build([]), 0)
        self.assertIn("fold=full", out.getvalue())
        self.assertIn("did not finish", err.getvalue())
        p = self._posting("examplecorp", "gh-111")
        self.assertNotIn("human", p)
        self.assertNotIn("effective", p["opinions"]["workplace"])
        self.assertEqual([r for r in self._index_rows()
                          if r["key"] == "gh-111"][0]["workplace"], "remote")
        self._assert_matches_rebuild()

    def test_a_finished_build_leaves_no_incomplete_marker(self):
        """The marker must not survive a clean build, or every later build is slow."""
        marker = fold_state.incomplete_path(self.layout)
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self.assertFalse(marker.exists())
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertIn("fold=pending-only", self._summary())
        self.assertFalse(marker.exists())
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self._build(["--opinions-only"]), 0)
        self.assertFalse(marker.exists())

    def test_a_crlf_jd_survives_the_resumed_fold(self):
        """``jd.md`` is written as BYTES; reading it back as text translates them.

        Ashby's ``descriptionPlain`` reaches ``jd.md`` without passing through
        ``strip_html``, so a CRLF in the payload is a real shape rather than a
        hypothetical. The resumed fold carries the previous JD forward to archive it
        as ``jd-<hash>.md`` at a change point — read as text, that snapshot holds LF
        where raw holds CRLF, and only the archive diverges (the content hash
        normalizes whitespace away).
        """
        crlf = "Own the ingestion pipeline.\r\nKafka, Flink, Iceberg.\r\nShip it."
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(14), crlf)
        self.assertEqual(self._build([]), 0)
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(16),
                            "Completely different role: run the billing platform.")
        self.assertIn("fold=pending-only", self._summary())
        entity = self.layout.derived / "postings" / "examplecorp" / "ashby-ay-1"
        archived = sorted(entity.glob("jd-*.md"))
        self.assertEqual(len(archived), 1, archived)
        self.assertIn(b"\r\n", archived[0].read_bytes())
        self._assert_matches_rebuild()

    def test_pruned_blob_falls_back(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build([]), 0)
        self._delete_blob_for("gh-222")
        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(16))
        self.assertIn("fold=full", self._summary())
        self.assertTrue(self._posting("examplecorp", "gh-222")["provenance"]["carried"])
        self._assert_matches_rebuild()


class CarriedOverlayTests(_StoreCase):
    """Every load path must hand ``_post_pass``/``_apply_annotations`` a bare posting.

    ``_post_pass`` and the annotation overlay only ever ADD, so an entity that
    arrives still carrying last generation's ``possible_duplicate`` /
    ``migrated_from`` / ``human`` overlays can gain a hint but never lose one. The
    fast path's loader (``_load_derived_entity``) strips them for exactly that
    reason; the full fold's ``_load_existing_entity`` and ``_reconstruct_from_frozen``
    must too, or ``--rebuild`` — the authoritative path — is the one that cannot
    repair a stale hint or take back a deleted annotation.
    """

    def test_a_carried_entity_loses_a_hint_its_bucket_no_longer_supports(self):
        self._capture_gh([_job(900, "Staff Engineer", "Remote, US",
                               content=self.DUP_JD)], _dt(14))
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(15),
                            self.DUP_JD)
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._posting("examplecorp", "gh-900")["possible_duplicate"],
                         ["ashby-ay-1"])
        self.assertEqual(self._posting("examplecorp", "ashby-ay-1")["possible_duplicate"],
                         ["gh-900"])
        # Ashby's raw stops syncing to this laptop → the entity is CARRIED from
        # derived, and greenhouse's JD is rewritten, so the pair is no longer a
        # content duplicate. Both halves must lose the hint.
        self._delete_blob_for("ashby-ay-1")
        self._capture_gh([_job(900, "Staff Engineer", "Remote, US",
                               content="Completely different role: run billing.")],
                         _dt(17))
        self.assertEqual(self._build([]), 0)
        self.assertNotIn("possible_duplicate", self._posting("examplecorp", "gh-900"))
        self.assertNotIn("possible_duplicate",
                         self._posting("examplecorp", "ashby-ay-1"))
        self._assert_matches_rebuild()

    def test_the_fast_path_and_a_rebuild_agree_about_a_carried_entitys_hint(self):
        """The asymmetry itself, as a byte divergence between the two paths.

        The blob is already absent when the fold cache is written, so the next
        build keeps the fast path — which reaches the carried entity through
        ``_duplicate_participants`` and loads it STRIPPED, correctly dropping the
        hint. A rebuild reaches the same entity through ``_carry_forward``. If only
        one of the two loaders strips, the two paths write different bytes for the
        same input, and ``--rebuild`` is the one that is wrong.
        """
        self._capture_gh([_job(900, "Staff Engineer", "Remote, US",
                               content=self.DUP_JD)], _dt(14))
        self._capture_ashby("examplecorp", "ay-1", "Staff Engineer", _dt(15),
                            self.DUP_JD)
        self.assertEqual(self._build([]), 0)
        self._delete_blob_for("ashby-ay-1")
        self.assertEqual(self._build([]), 0)   # absorbs the absence into the cache
        self.assertEqual(self._posting("examplecorp", "ashby-ay-1")
                         ["possible_duplicate"], ["gh-900"])
        # A new greenhouse JD takes gh-900 out of the bucket — on the FAST path.
        self._capture_gh([_job(900, "Staff Engineer", "Remote, US",
                               content="Completely different role: run billing.")],
                         _dt(17))
        self.assertIn("fold=pending-only", self._summary())
        self.assertNotIn("possible_duplicate",
                         self._posting("examplecorp", "ashby-ay-1"))
        self._assert_matches_rebuild()

    def test_a_carried_entity_gives_back_a_deleted_annotation(self):
        self._capture_gh([_job(111, "SWE", "Remote, US")], _dt(14))
        self._annotate("gh-111", {"workplace": "onsite"})
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._posting("examplecorp", "gh-111")
                         ["opinions"]["workplace"]["effective"], "onsite")
        self._delete_blob_for("gh-111")                     # raw stops syncing here
        (self.layout.annotations / "gh-111.yaml").unlink()  # the owner takes it back
        self._capture_gh([_job(222, "SRE", "Austin, TX")], _dt(15))
        self.assertEqual(self._build([]), 0)
        p = self._posting("examplecorp", "gh-111")
        self.assertNotIn("human", p)
        self.assertNotIn("effective", p["opinions"]["workplace"])
        self.assertEqual([r for r in self._index_rows()
                          if r["key"] == "gh-111"][0]["workplace"], "remote")
        self._assert_matches_rebuild()

    def test_the_overlay_strip_and_the_index_floor_cover_disjoint_keys(self):
        """The two mechanisms that decide what survives without being re-derived.

        ``_write_postings_index`` re-adds, verbatim, every live-index key the build
        does not account for. The overlay strip re-derives every key the build DOES
        account for. The sets are disjoint by construction — a stripped key has a
        derived or frozen entity, and that is exactly what puts it in the writer's
        ``rows`` — so no row can both survive the writer untouched and be one the
        strip owed a re-derivation. This holds all three states in one build.

        The last assertion is the boundary, stated deliberately: an index-only
        survivor's ``workplace`` was baked from a human annotation that is now
        deleted, and it stays. Its raw AND derived are both gone, so there is no JD
        to re-classify from and nothing to re-derive — the row is honest history
        marked ``carried_from: index``. Dropping it instead is the exact data loss
        the single-writer change exists to prevent.
        """
        self._capture_gh([_job(111, "SWE", "Remote, US")], _dt(14))
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self._annotate("gh-111", {"workplace": "onsite"})
        self._annotate("gh-222", {"workplace": "onsite"})
        self.assertEqual(self._build([]), 0)
        before = {r["key"]: r for r in self._index_rows()}
        self.assertEqual(before["gh-111"]["workplace"], "onsite")
        self.assertEqual(before["gh-222"]["workplace"], "onsite")

        # gh-111 keeps its derived (carried); gh-222 loses raw AND derived, so only
        # its committed index row remains. Both annotations are taken back.
        self._delete_blob_for("gh-111")
        self._delete_blob_for("gh-222")
        shutil.rmtree(self.layout.derived / "postings" / "examplecorp" / "gh-222")
        for key in ("gh-111", "gh-222"):
            (self.layout.annotations / f"{key}.yaml").unlink()
        self._capture_gh([_job(333, "Data Engineer", "NYC, NY")], _dt(16))
        self.assertEqual(self._build([]), 0)

        rows = {r["key"]: r for r in self._index_rows()}
        self.assertEqual(set(rows), {"gh-111", "gh-222", "gh-333"})
        # gh-111 — the strip owns it: re-derived, and NOT a floor survivor.
        p = self._posting("examplecorp", "gh-111")
        self.assertNotIn("human", p)
        self.assertNotIn("effective", p["opinions"]["workplace"])
        self.assertEqual(rows["gh-111"]["workplace"], "remote")
        self.assertNotIn("carried_from", rows["gh-111"])
        # gh-222 — the floor owns it: verbatim, original seq, no derived fabricated.
        self.assertEqual(rows["gh-222"]["carried_from"], "index")
        self.assertEqual(rows["gh-222"]["seq"], before["gh-222"]["seq"])
        self.assertFalse((self.layout.derived / "postings" / "examplecorp"
                          / "gh-222").exists())
        self.assertNotIn("carried_from", rows["gh-333"])
        # The boundary: the survivor keeps the human-derived value it was written
        # with, because nothing survives to re-derive it from.
        self.assertEqual(rows["gh-222"]["workplace"], "onsite")
        self._assert_matches_rebuild()

    def test_a_frozen_entity_gives_back_a_deleted_annotation(self):
        """The third loader: reconstructed from a frozen-facts snapshot.

        The snapshot is the entity YAML verbatim, overlays included, and it wins
        over derived — so without a strip a pruned entity's human fact is
        un-deletable by any build path at all.
        """
        self._capture_gh([_job(111, "SWE", "Remote, US")], _dt(14))
        self._annotate("gh-111", {"workplace": "onsite"})
        self.assertEqual(self._build([]), 0)
        self._freeze_and_prune("examplecorp", "gh-111")
        (self.layout.annotations / "gh-111.yaml").unlink()
        self._capture_gh([_job(222, "SRE", "Austin, TX")], _dt(15))
        self.assertEqual(self._build([]), 0)
        p = self._posting("examplecorp", "gh-111")
        self.assertTrue(p["provenance"]["frozen"])
        self.assertNotIn("human", p)
        self.assertNotIn("effective", p["opinions"]["workplace"])
        self._assert_matches_rebuild()


class FrozenTimelineTests(_StoreCase):
    """A frozen entity observed again must produce ONE timeline, not two halves."""

    def test_a_re_observed_frozen_entity_keeps_one_first_seen_and_records_the_change(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self._freeze_and_prune("examplecorp", "gh-111")
        # The requisition is still open and is observed again, with a new posted_at.
        job = _job(111, "SWE", "Austin, TX")
        job["first_published"] = "2026-07-18T00:00:00Z"
        self._capture_gh([job], _dt(20))
        self.assertEqual(self._build([]), 0)

        events = [json.loads(ln) for ln in
                  (self.layout.derived / "postings" / "examplecorp" / "gh-111"
                   / "events.jsonl").read_text().splitlines()]
        types = [e["type"] for e in events]
        self.assertEqual(types.count("first_seen"), 1, types)
        self.assertEqual(types[0], "first_seen")
        changed = [e for e in events if e["type"] == "changed"]
        self.assertEqual(len(changed), 1, events)
        self.assertEqual({c["field"] for c in changed[0]["changes"]}, {"posted_at"})
        p = self._posting("examplecorp", "gh-111")
        self.assertEqual(p["first_seen"], "2026-07-14T09:00:00Z")
        self.assertEqual(p["last_seen"], "2026-07-20T09:00:00Z")
        # by-day must not report the same entity as first_seen on two days.
        first_days = [d.name for d in sorted((self.layout.index / "by-day").iterdir())
                      if any(json.loads(ln).get("type") == "first_seen"
                             for ln in d.read_text().splitlines()[1:])]
        self.assertEqual(first_days, ["2026-07-14.jsonl"])
        self._assert_matches_rebuild()

    def test_a_frozen_snapshot_that_adds_nothing_is_a_no_op(self):
        """Frozen holds no fetch the present raw lacks → the fresh fold stands."""
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self._freeze_and_prune("examplecorp", "gh-111", prune=False)
        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(15))
        self.assertEqual(self._build([]), 0)
        p = self._posting("examplecorp", "gh-111")
        self.assertNotIn("frozen", p["provenance"])
        self.assertEqual(p["location"], "Seattle, WA")
        self._assert_matches_rebuild()


class CollectToleranceTests(_StoreCase):
    """`_collect`'s two "I could not use this" states must degrade AND be counted."""

    def test_a_corrupt_blob_is_skipped_counted_and_never_wedges_the_build(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self._truncate_newest_blob()  # exactly what an interrupted rsync leaves
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = self._build([])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertIn("corrupt=1", out.getvalue())
        self.assertIn("corrupt blob", err.getvalue())
        self.assertEqual(self._index_keys(), {"gh-111"})  # gh-222 never materialized
        # …and no build path is wedged by it: the full fold and --rebuild both run.
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertEqual(self._index_keys(), {"gh-111"})

    def test_a_payload_the_parser_cannot_read_is_counted(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build([]), 0)
        # A source-wide parser regression: HTTP 200, well-formed JSON, present
        # blob, new envelope shape — indistinguishable from an empty board today.
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
            status=200,
            payload_bytes=json.dumps({"data": {"jobs": [_job(222, "SRE", "Remote, US")]}}).encode(),
            content_type="application/json", fetched_at=_dt(15),
            context={"company": "examplecorp", "profile": "profile-01"})
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = self._build([])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertIn("no_rows=1", out.getvalue())
        self.assertIn("greenhouse", err.getvalue())

    def test_a_build_with_nothing_to_report_stays_quiet(self):
        """Neither counter fires on a healthy build (they are signal, not noise)."""
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(self._build([]), 0)
        self.assertNotIn("no_rows", out.getvalue())
        self.assertNotIn("corrupt", out.getvalue())
        self.assertNotIn("produced no rows", err.getvalue())
        self.assertNotIn("corrupt blob", err.getvalue())


class OrphanTests(_StoreCase):
    def test_orphan_annotation_hard_fails_rebuild(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.layout.annotations / "gh-does-not-exist.yaml",
                          serialization.dumps_yaml({"schema_version": 1,
                                                    "key": "gh-does-not-exist"}))
        rc = self._build(["--rebuild"])
        self.assertEqual(rc, 2)  # verify hard-fail (orphaned human judgment)


class OpinionsOnlyTests(_StoreCase):
    def test_opinions_only_relabels_and_prints_diff(self):
        # A JD with no visa language classifies "unclear"; corrupting the stored
        # label to "yes" then re-deriving from facts must correct it and print the
        # diff — exercising the facts/opinions split without a real classifier tweak.
        self._capture_gh([_job(111, "SWE", "Austin, TX",
                               content="Build reliable distributed systems.")], _dt(14))
        self.assertEqual(self._build([]), 0)
        pyaml = (self.layout.derived / "postings" / "examplecorp" / "gh-111"
                 / "posting.yaml")
        data = serialization.loads_yaml(pyaml.read_text())
        self.assertEqual(data["opinions"]["visa"]["label"], "unclear")
        data["opinions"]["visa"]["label"] = "yes"
        atomic_write_text(pyaml, serialization.dumps_yaml(data))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self._build(["--opinions-only"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("re-labeled", out)
        self.assertIn("visa yes", out)  # "N posting(s) changed visa yes→unclear"
        fixed = serialization.loads_yaml(pyaml.read_text())
        self.assertEqual(fixed["opinions"]["visa"]["label"], "unclear")


class CarryForwardTests(_StoreCase):
    """MAJOR-1: a not-synced-here entity (blob absent, no tombstone) is KEPT."""

    def test_incremental_and_rebuild_keep_not_synced_entity(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))     # blob A
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))     # blob B
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._index_keys(), {"gh-111", "gh-222"})
        # delete gh-222's ONLY blob (no tombstone) → not-synced-here
        self._delete_blob_for("gh-222")
        # incremental must keep it (carried), never drop or error
        self.assertEqual(self._build([]), 0)
        self.assertIn("gh-222", self._index_keys())
        self.assertTrue(self._posting("examplecorp", "gh-222")["provenance"]["carried"])
        # rebuild must also keep it (not silently dropped from derived+index)
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertIn("gh-222", self._index_keys())

    def test_a_renamed_company_is_not_reinstated_by_carry_forward(self):
        """The orphan partition does not just sit there — it can WIN the index.

        ``_carry_forward`` walks ``sorted(rglob("posting.yaml"))`` assigning
        ``out[key]``, so the alphabetically LAST partition wins. With the stale
        ``zeta-corp/`` dir still present, the first build that cannot see raw
        reinstates the OLD company and title into the index, silently reverting a
        rename that already happened — and ``validate_store`` reports ``ok``.
        """
        self._capture_aggregator_row("Zeta Corp", "Backend Engineer", _dt(14))
        self.assertEqual(self._build([]), 0)
        self._capture_aggregator_row("Alpha Labs", "Senior Backend Engineer", _dt(15))
        self.assertEqual(self._build([]), 0)
        [row] = self._index_rows()
        self.assertEqual((row["company"], row["title"]),
                         ("Alpha Labs", "Senior Backend Engineer"))

        shutil.rmtree(self.layout.raw)      # raw never synced to this machine
        self.assertEqual(self._build([]), 0)
        [row] = self._index_rows()
        self.assertEqual((row["company"], row["title"]),
                         ("Alpha Labs", "Senior Backend Engineer"),
                         "carry-forward reinstated the pre-rename orphan")
        self.assertEqual(self._partitions(), ["alpha-labs"])
        report = validate_store(self.data_root)
        self.assertTrue(report.ok, report.errors)

    def test_annotated_not_synced_entity_passes_verify(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build([]), 0)
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.layout.annotations / "gh-222.yaml",
                          serialization.dumps_yaml({"schema_version": 1, "key": "gh-222",
                                                    "facts": {"visa": "yes"}}))
        self._delete_blob_for("gh-222")
        # carried key still resolves the annotation → NOT an orphan hard-fail
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertIn("gh-222", self._index_keys())


class AnnotationMergeTests(_StoreCase):
    """MAJOR-2: human facts win in the view; a disagreement records one conflict."""

    def test_annotation_overrides_opinion_and_logs_conflict(self):
        self._capture_gh([_job(111, "SWE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        # computed workplace is remote; annotate the opposite (a disagreement)
        self.assertEqual(self._posting("examplecorp", "gh-111")
                         ["opinions"]["workplace"]["value"], "remote")
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.layout.annotations / "gh-111.yaml",
                          serialization.dumps_yaml({"schema_version": 1, "key": "gh-111",
                                                    "verified_by": "human",
                                                    "facts": {"workplace": "onsite"}}))
        self.assertEqual(self._build([]), 0)  # incremental applies the merge
        p = self._posting("examplecorp", "gh-111")
        wp = p["opinions"]["workplace"]
        self.assertEqual(wp["value"], "remote")     # raw opinion preserved
        self.assertEqual(wp["effective"], "onsite")  # human wins in the view
        self.assertEqual(wp["source"], "human")
        self.assertEqual(p["human"]["facts"]["workplace"], "onsite")
        # index reflects the human-overridden value
        row = [r for r in self._index_rows() if r["key"] == "gh-111"][0]
        self.assertEqual(row["workplace"], "onsite")
        # exactly one conflict line
        conflicts = self.layout.state / "annotation-conflicts.jsonl"
        lines = [json.loads(l) for l in conflicts.read_text().splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["entity"], lines[0]["field"],
                          lines[0]["human_value"]), ("gh-111", "workplace", "onsite"))
        # rebuild does NOT duplicate the conflict (idempotent)
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertEqual(len(conflicts.read_text().splitlines()), 1)
        # opinions-only never beats the annotation
        self.assertEqual(self._build(["--opinions-only"]), 0)
        self.assertEqual(self._posting("examplecorp", "gh-111")
                         ["opinions"]["workplace"]["effective"], "onsite")


class WorkdayAliasTests(_StoreCase):
    """MAJOR-3: two context slugs aliasing one canonical yield ONE wd- key."""

    REGISTRY = {"companies": [{
        "name": "Acme Corp", "ats": "workday", "token": "acme",
        "host": "acme.wd5.myworkdayjobs.com", "site": "Careers", "tags": ["x"],
        "aliases": ["ACME Inc"]}]}

    def test_aliases_map_to_one_workday_key(self):
        reg = self.data_root / "companies.yaml"
        atomic_write_text(reg, serialization.dumps_yaml(self.REGISTRY))
        # same requisition observed under two different context slugs (aliases)
        self._capture_workday("JR100", "acme", _dt(14))
        self._capture_workday("JR100", "acme-inc", _dt(15))
        self.assertEqual(self._build(["--rebuild", "--registry", str(reg)]), 0)
        keys = self._index_keys()
        self.assertEqual(keys, {"wd-acme-corp-jr100"})


class IncrementalVerifyTests(_StoreCase):
    """MINOR-2: the orphan hard-fail runs on the INCREMENTAL path too."""

    def test_orphan_annotation_hard_fails_incremental(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.layout.annotations.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.layout.annotations / "gh-nope.yaml",
                          serialization.dumps_yaml({"schema_version": 1, "key": "gh-nope"}))
        self.assertEqual(self._build([]), 2)  # incremental verify hard-fail


class MigrationTests(_StoreCase):
    REGISTRY = {"companies": [
        {"name": "MigCo", "ats": "ashby", "token": "migco", "tags": ["x"],
         "previous": [{"ats": "greenhouse", "token": "migco-old",
                       "until": "2026-06-01"}]}]}

    def _write_registry(self):
        path = self.data_root / "companies.yaml"
        atomic_write_text(path, serialization.dumps_yaml(self.REGISTRY))
        return path

    def test_declared_migration_links_across_ats(self):
        jd = "Design and run the platform. Kubernetes at scale."
        # old ATS (greenhouse) and new ATS (ashby), same company+title+JD content
        self._session().capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/migco-old/jobs"},
            status=200, payload_bytes=_gh_board([_job(900, "Staff Engineer",
                                                      "Remote, US", content=jd)]),
            content_type="application/json", fetched_at=_dt(14),
            context={"company": "migco", "profile": "profile-01"})
        ashby = {"apiVersion": "1", "jobs": [{
            "id": "ay-1", "title": "Staff Engineer", "location": "Remote, US",
            "jobUrl": "https://jobs.ashbyhq.com/migco/ay-1",
            "descriptionPlain": jd, "publishedAt": "2026-07-15T00:00:00Z",
            "isListed": True}]}
        self._session().capture_fetch(
            source="ashby", operation="board",
            request={"url": "https://api.ashbyhq.com/posting-api/job-board/migco"},
            status=200, payload_bytes=json.dumps(ashby).encode(),
            content_type="application/json", fetched_at=_dt(16),
            context={"company": "migco", "profile": "profile-01"})
        reg = self._write_registry()
        rc = self._build(["--rebuild", "--registry", str(reg)])
        self.assertEqual(rc, 0)
        ashby_entity = serialization.loads_yaml(
            (self.layout.derived / "postings" / "migco" / "ashby-ay-1"
             / "posting.yaml").read_text())
        self.assertIn("migrated_from", ashby_entity)
        self.assertEqual(ashby_entity["migrated_from"]["key"], "gh-900")
        self.assertEqual(ashby_entity["migrated_from"]["ats"], "greenhouse")


class IndexPreservationTests(_StoreCase):
    """Decision 2: the committed index is a durable floor the builder never drops.

    A key surviving only in the pre-existing ``index/postings.jsonl`` — no current
    entity, no derived on disk, no tombstone — is preserved verbatim at its original
    ``seq`` and marked ``carried``/``carried_from: index``; a key this build DID
    materialize always wins its own row.
    """

    def test_fresh_rebuild_with_index_only_history_is_superset(self):
        # Establish full derived+index history for gh-111 on a "prior machine".
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build(["--rebuild"]), 0)
        orig_row = [r for r in self._index_rows() if r["key"] == "gh-111"][0]
        self.assertNotIn("carried", orig_row)

        # New checkout: only the committed index/state made it here (raw/derived
        # never synced) — then a fresh capture of an UNRELATED posting.
        self._drop_raw_and_derived()
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(20))

        rc = self._build(["--rebuild"])
        self.assertEqual(rc, 0)

        # Superset: both the historical index-only key and the freshly built key.
        self.assertEqual(self._index_keys(), {"gh-111", "gh-222"})
        rows = {r["key"]: r for r in self._index_rows()}
        survivor = rows["gh-111"]
        self.assertTrue(survivor["carried"])
        self.assertEqual(survivor["carried_from"], "index")
        self.assertEqual(survivor["seq"], orig_row["seq"])  # original seq preserved
        # Every other field is preserved verbatim from the old index row.
        for field in ("company", "title", "location", "first_seen", "last_seen"):
            self.assertEqual(survivor[field], orig_row[field])
        # Never fabricated as a derived artifact.
        self.assertFalse((self.layout.derived / "postings" / "examplecorp"
                          / "gh-111").exists())
        fresh_row = rows["gh-222"]
        self.assertNotIn("carried", fresh_row)

        report = validate_store(self.data_root)
        self.assertTrue(report.ok, report.errors)

    def test_incremental_also_preserves_index_only_survivor(self):
        # Same setup, but exercised through the incremental path (not just rebuild).
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build(["--rebuild"]), 0)
        self._drop_raw_and_derived()
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(20))

        rc = self._build([])  # incremental (default mode)
        self.assertEqual(rc, 0)
        self.assertEqual(self._index_keys(), {"gh-111", "gh-222"})
        survivor = [r for r in self._index_rows() if r["key"] == "gh-111"][0]
        self.assertTrue(survivor["carried"])
        self.assertEqual(survivor["carried_from"], "index")

    def test_updated_current_entity_replaces_stale_index_row(self):
        """Built entities win by key — a stale pre-existing index row never wins."""
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build(["--rebuild"]), 0)

        # Hand-corrupt the live index row to look like ancient, wildly-stale history
        # (as if the committed index predates a real rename/relocation of this role).
        idx_path = self.layout.index / "postings.jsonl"
        lines = idx_path.read_text().splitlines()
        rows = [json.loads(l) for l in lines]
        for row in rows:
            if row.get("key") == "gh-111":
                row["title"] = "STALE TITLE FROM AN OLD ERA"
                row["location"] = "Nowhere, XX"
                row["seq"] = 999
        atomic_write_text(idx_path, "".join(
            json.dumps(r, sort_keys=True) + "\n" for r in rows))

        # A fresh capture of the SAME entity (real raw present this run).
        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(15))
        rc = self._build(["--rebuild"])
        self.assertEqual(rc, 0)

        row = [r for r in self._index_rows() if r["key"] == "gh-111"][0]
        self.assertEqual(row["title"], "SWE")
        self.assertEqual(row["location"], "Seattle, WA")
        self.assertNotIn("carried", row)
        self.assertNotEqual(row["seq"], 999)  # real computed seq, not the stale one

    def test_a_row_deleted_from_the_committed_index_falls_back(self):
        """The floor is the last zone with no invalidation signal of its own.

        ``_patch_index_zone`` reads ``index/postings.jsonl`` as authoritative for
        every row this run does not rebuild, so a row deleted from it stayed lost
        across every subsequent fast build — in the zone the design calls
        committed, durable history. Reproduces only for a row this sweep does not
        re-observe; a re-observed one writes its own row back.
        """
        self._capture_gh([_job(111, "SWE", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._index_keys(), {"gh-111", "gh-222"})

        # Hand-delete gh-222's row. derived/ and raw/ are untouched.
        idx = self.layout.index / "postings.jsonl"
        rows = [json.loads(l) for l in idx.read_text().splitlines()]
        atomic_write_text(idx, "".join(
            json.dumps(r, sort_keys=True) + "\n" for r in rows
            if r.get("key") != "gh-222"))
        self.assertEqual(self._index_keys(), {"gh-111"})

        self._capture_gh([_job(111, "SWE", "Seattle, WA")], _dt(15))  # gh-222 absent
        self.assertIn("fold=full", self._summary())
        self.assertEqual(self._index_keys(), {"gh-111", "gh-222"})

    def test_full_current_input_remains_unchanged(self):
        """No index-only survivors on a full-raw machine — output is unaffected."""
        self._capture_gh([_job(111, "SWE", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._build(["--rebuild"]), 0)
        rows = self._index_rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertNotIn("carried", row)
            self.assertNotIn("carried_from", row)

    def _zone_bytes(self, *subs):
        out = {}
        for sub in subs:
            d = self.layout.index / sub
            for p in sorted(d.rglob("*")) if d.is_dir() else []:
                if p.is_file():
                    out[f"{sub}/{p.relative_to(d)}"] = p.read_bytes()
        return out

    def test_opinions_only_preserves_index_only_survivors(self):
        """`--opinions-only` must not destroy the rows that exist nowhere else.

        It rewrites ``index/postings.jsonl`` from ``derived/`` alone, so a row whose
        raw AND derived are both gone has no source to be rebuilt from and was simply
        dropped. Nothing regenerates those rows and ``--rebuild`` cannot bring them
        back — there is nothing left to rebuild from — so the loss is permanent, and
        `--opinions-only` is documented as a cheap re-classification pass that warns
        about nothing.
        """
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build(["--rebuild"]), 0)
        before = {r["key"]: r for r in self._index_rows()}

        # New checkout: only the committed index/state are here. One fresh capture
        # gives the store a live entity, so gh-111/gh-222 survive ONLY as index rows.
        self._drop_raw_and_derived()
        self._capture_gh([_job(333, "Data Engineer", "Seattle, WA")], _dt(20))
        self.assertEqual(self._build([]), 0)
        self.assertEqual(self._index_keys(), {"gh-111", "gh-222", "gh-333"})
        survivors = {r["key"]: r for r in self._index_rows()
                     if r.get("carried_from") == "index"}
        self.assertEqual(set(survivors), {"gh-111", "gh-222"})
        bucketed = self._zone_bytes("by-day", "triage")

        self.assertEqual(self._build(["--opinions-only"]), 0)

        self.assertEqual(self._index_keys(), {"gh-111", "gh-222", "gh-333"})
        after = {r["key"]: r for r in self._index_rows()}
        for key, row in survivors.items():
            self.assertEqual(after[key], row)              # verbatim
            self.assertEqual(after[key]["seq"], before[key]["seq"])  # original seq
        self.assertNotIn("carried", after["gh-333"])       # the live entity is unmarked
        # by-day / triage are event-derived and opinions-only writes no events;
        # preserving the floor must not start writing (or emptying) them.
        self.assertEqual(self._zone_bytes("by-day", "triage"), bucketed)

    def test_the_postings_index_has_exactly_one_writer(self):
        """The floor is enforced AT the write, so no build path can forget it.

        ``--opinions-only`` destroyed survivor rows because the floor was threaded
        through the callers and one caller was never handed it. A second writer of
        ``index/postings.jsonl`` reopens exactly that hole, so this fails the moment
        one appears.
        """
        src = Path(bp.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        writers = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and getattr(n.func, "id", "") == "atomic_write_text"
                   and n.args
                   and "postings.jsonl" in (ast.get_source_segment(src, n.args[0]) or "")]
        self.assertEqual(
            len(writers), 1,
            "index/postings.jsonl must have exactly ONE writer "
            "(_write_postings_index), which applies the durable floor; found "
            f"{len(writers)} at line(s) {[n.lineno for n in writers]}")

    def test_incremental_and_rebuild_agree_on_index_survivors(self):
        """Incremental and rebuild compute the identical union + survivor set."""
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build(["--rebuild"]), 0)
        orig_seq = {r["key"]: r["seq"] for r in self._index_rows()}

        self._drop_raw_and_derived()
        self._capture_gh([_job(333, "Platform Engineer", "NYC, NY")], _dt(16))

        root_incr = Path(tempfile.mkdtemp(prefix="agree-incr-"))
        root_rebuild = Path(tempfile.mkdtemp(prefix="agree-rebuild-"))
        try:
            shutil.rmtree(root_incr)
            shutil.copytree(self.data_root, root_incr)
            shutil.rmtree(root_rebuild)
            shutil.copytree(self.data_root, root_rebuild)

            rc_incr = bp.main(["--data-root", str(root_incr)])
            rc_rebuild = bp.main(["--data-root", str(root_rebuild), "--rebuild"])
            self.assertEqual(rc_incr, 0)
            self.assertEqual(rc_rebuild, 0)

            rows_incr = self._index_rows_at(root_incr)
            rows_rebuild = self._index_rows_at(root_rebuild)
            key = lambda r: r["key"]
            self.assertEqual(sorted(rows_incr, key=key), sorted(rows_rebuild, key=key))

            survivors = {r["key"] for r in rows_incr if r.get("carried_from") == "index"}
            self.assertEqual(survivors, {"gh-111", "gh-222"})
            for k in ("gh-111", "gh-222"):
                row = [r for r in rows_incr if r["key"] == k][0]
                self.assertEqual(row["seq"], orig_seq[k])
            fresh = [r for r in rows_incr if r["key"] == "gh-333"][0]
            self.assertNotIn("carried", fresh)
        finally:
            shutil.rmtree(root_incr, ignore_errors=True)
            shutil.rmtree(root_rebuild, ignore_errors=True)


class EmptyStoreRebuildTests(_StoreCase):
    """A rebuild that materializes zero entities must still commit a store.

    ``_write_entity`` is what creates ``derived.building``, so a build with nothing
    to write left the aside dir absent and ``_swap_dir``'s second rename raised an
    uncaught ``FileNotFoundError`` — *after* the first rename had already moved the
    live ``derived/`` to ``derived.old``. The traceback is the visible half; the
    data-availability half is that the derived zone is gone until some later build
    happens to run ``_recover_swap_remnants``.
    """

    def _aside(self, zone, suffix):
        return zone.with_name(zone.name + suffix)

    def _assert_zones_committed(self):
        for zone in (self.layout.derived, self.layout.index):
            self.assertTrue(zone.is_dir(), f"{zone.name} was not committed")
            for suffix in (".old", ".building"):
                self.assertFalse(self._aside(zone, suffix).exists(),
                                 f"{zone.name}{suffix} left behind")

    def test_rebuild_of_an_empty_store_exits_cleanly(self):
        self.assertEqual(self._build(["--rebuild"]), 0)
        self._assert_zones_committed()

    def test_rebuild_when_every_captured_row_is_suppressed(self):
        # One aggregator sweep whose only row is a non-US posting — the realistic
        # shape: raw exists, every row is suppressed, zero entities materialize.
        self._capture_scrape("jobicy", {"jobs": [
            {"id": 2, "url": "https://jobicy.com/jobs/2-lon", "jobTitle": "UK Backend",
             "companyName": "UkCo", "jobGeo": "London, United Kingdom",
             "jobDescription": "d", "pubDate": "2026-07-12"}]}, _dt(14))
        self.assertEqual(self._build(["--rebuild"]), 0)
        self._assert_zones_committed()
        triage = list((self.layout.index / "triage").glob("*.jsonl"))
        self.assertEqual(len(triage), 1)

    def test_rebuild_of_an_index_only_checkout_keeps_the_floor(self):
        """The two defects meet: zero entities AND the index is the only record."""
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build(["--rebuild"]), 0)
        floor = {r["key"]: r for r in self._index_rows()}
        self.assertEqual(set(floor), {"gh-111", "gh-222"})

        self._drop_raw_and_derived()
        self.assertEqual(self._build(["--rebuild"]), 0)
        self._assert_zones_committed()
        rows = {r["key"]: r for r in self._index_rows()}
        self.assertEqual(set(rows), set(floor))
        for key, row in rows.items():
            self.assertEqual(row["carried_from"], "index")
            self.assertEqual(row["seq"], floor[key]["seq"])


class IndexRegenCrashTests(_StoreCase):
    """The incremental regeneration must not delete the index zone before writing.

    ``--rebuild`` writes the whole index into ``index.building`` and swaps, so a
    failure anywhere before the swap leaves the live zone untouched. The default
    (incremental) path regenerates in place, and it used to ``rmtree`` ``by-day/``
    and ``triage/`` FIRST. ``postings.jsonl`` was already excluded and the crash
    leaves the write-ahead marker that forces the next build to regenerate both
    directories — so the hole is transient, not the permanent loss of a durable
    floor. Transient is still a window ``--rebuild`` does not have.
    """

    def _ensure_index_zone(self):
        """Two postings (by-day rows) plus one suppressed row (a triage row)."""
        self._capture_gh([_job(111, "SWE", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self._capture_scrape("jobicy", {"jobs": [
            {"id": 2, "url": "https://jobicy.com/jobs/2-lon", "jobTitle": "UK Backend",
             "companyName": "UkCo", "jobGeo": "London, United Kingdom",
             "jobDescription": "d", "pubDate": "2026-07-12"}]}, _dt(15))
        self.assertEqual(self._build([]), 0)
        zone = self._zone()
        self.assertTrue(zone["by-day"] and zone["triage"], zone)
        return zone

    def _zone(self):
        out = {"postings.jsonl": (self.layout.index / "postings.jsonl").is_file()}
        for sub in ("by-day", "triage"):
            d = self.layout.index / sub
            out[sub] = sorted(p.name for p in d.glob("*.jsonl")) if d.is_dir() \
                else "MISSING"
        return out

    def _build_with_a_failing_index_write(self, *argv):
        """ENOSPC inside the index write — the audit's demonstration."""
        real = bp.atomic_write_text

        def _fail(path, text):
            if Path(path).name == "postings.jsonl":
                raise OSError(28, "No space left on device")
            return real(path, text)

        bp.atomic_write_text = _fail
        try:
            with self.assertRaises(OSError):
                self._build(list(argv))
        finally:
            bp.atomic_write_text = real

    def test_a_failed_incremental_index_write_leaves_by_day_and_triage(self):
        before = self._ensure_index_zone()
        self._cache().unlink()          # force the whole-raw-zone fold (regen path)
        self._capture_gh([_job(333, "Data Engineer", "NYC, NY")], _dt(16))
        self._build_with_a_failing_index_write()
        self.assertEqual(self._zone(), before)

    def test_rebuild_already_survives_the_same_failure(self):
        """The behaviour the incremental path is being brought level with."""
        before = self._ensure_index_zone()
        self._capture_gh([_job(333, "Data Engineer", "NYC, NY")], _dt(16))
        self._build_with_a_failing_index_write("--rebuild")
        self.assertEqual(self._zone(), before)

    def test_a_bucket_that_empties_still_loses_its_file(self):
        """Write-first must not turn into never-prune: a stale bucket still goes."""
        self._ensure_index_zone()
        orphan = self.layout.index / "by-day" / "2020-01-01.jsonl"
        atomic_write_text(orphan, '{"_schema": 1}\n')
        stray = self.layout.index / "leftovers.jsonl"
        atomic_write_text(stray, '{"_schema": 1}\n')
        self._cache().unlink()
        self._capture_gh([_job(333, "Data Engineer", "NYC, NY")], _dt(16))
        self.assertIn("fold=full", self._summary())
        self.assertFalse(orphan.exists(), "a bucket with no rows kept its file")
        self.assertFalse(stray.exists(), "a stale top-level index file survived")
        self._assert_matches_rebuild()


class SwapCrashRecoveryTests(_StoreCase):
    """A build killed inside ``_swap_dir`` leaves the zone only as ``<zone>.old``.

    That backup is then the sole copy of the committed index — the durable floor
    whose index-only rows exist nowhere else once their raw blobs are pruned and
    their derived is gone. The next run must RESTORE it before reading the floor,
    not delete it: ``_read_index_rows`` tolerates an absent index by returning
    ``{}``, so a destroyed remnant reads as "there was never a floor" and the
    following swap commits an index without those rows.
    """

    def _kill_mid_swap(self, zone: Path) -> Path:
        """Reproduce the exact on-disk state of a SIGKILL between the two renames."""
        backup = zone.with_name(zone.name + ".old")
        zone.rename(backup)                     # window opened, process died here
        (zone.with_name(zone.name + ".building")).mkdir(parents=True)
        return backup

    def test_recover_restores_only_when_the_live_zone_is_absent(self):
        with tempfile.TemporaryDirectory() as td:
            zone = Path(td) / "index"
            (zone / "sub").mkdir(parents=True)
            (zone / "postings.jsonl").write_text("row\n", encoding="utf-8")
            backup = self._kill_mid_swap(zone)
            self.assertFalse(zone.exists())

            self.assertTrue(bp._recover_swap_remnant(zone))
            self.assertTrue((zone / "postings.jsonl").exists())
            self.assertFalse(backup.exists())
            # Idempotent, and a stale backup beside a LIVE zone is not a remnant.
            self.assertFalse(bp._recover_swap_remnant(zone))
            backup.mkdir()
            self.assertFalse(bp._recover_swap_remnant(zone))

    def test_durable_floor_survives_a_build_killed_mid_swap(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self.assertEqual(self._build(["--rebuild"]), 0)
        floor = self._index_keys()
        self.assertEqual(floor, {"gh-111", "gh-222"})

        # Index-only survivors: raw + derived are gone, the committed index is the
        # only record of these rows — and then a build is killed mid-swap.
        self._drop_raw_and_derived()
        self._kill_mid_swap(self.layout.index)
        self.assertFalse(self.layout.index.exists())

        self._capture_gh([_job(333, "Data Engineer", "Seattle, WA")], _dt(20))
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertEqual(self._index_keys(), floor | {"gh-333"})
        for key in floor:
            row = [r for r in self._index_rows() if r["key"] == key][0]
            self.assertEqual(row["carried_from"], "index")

    def test_incremental_path_recovers_the_same_remnant(self):
        self._capture_gh([_job(111, "SWE", "Austin, TX")], _dt(14))
        self.assertEqual(self._build(["--rebuild"]), 0)
        self._drop_raw_and_derived()
        self._kill_mid_swap(self.layout.index)
        self._capture_gh([_job(222, "SRE", "Remote, US")], _dt(20))
        self.assertEqual(self._build([]), 0)    # incremental (the default path)
        self.assertEqual(self._index_keys(), {"gh-111", "gh-222"})


class FoldCoherenceTests(unittest.TestCase):
    """Two observations under ONE key must not produce a chimera.

    `_Fold.add` keeps the last JD it was *given*, so an observation carrying no
    description leaves the previous one standing, while `_finish` takes title and
    location from the latest observation unconditionally. For one posting
    re-observed by a listing-only scrape that is right. For two DIFFERENT postings
    folded under one key it welds one job's title to another job's body — and
    nothing in the finished entity reveals it.

    These drive the real `_Fold`/`_finish`, not a stand-in.
    """

    BOARD = "https://remoteok.com/remote-jobs/"

    def _row(self, native_id, title, company, description, url=None):
        return {"source": "remoteok", "operation": "scrape", "native_id": native_id,
                "title": title, "url": url if url is not None else self.BOARD,
                "location": "Remote", "company_name": company,
                "description": description, "workplace_raw": "remote",
                "posted_at": None, "salary_text": None, "salary_range": None}

    def _fold(self, *rows_and_days):
        """Fold rows into ONE entity key, oldest first, and finish it."""
        fold = bp._Fold("url-testkey")
        for row, day in rows_and_days:
            fold.add(bp.Observation(
                key="url-testkey", strength=bp.ident.STRONG, row=row,
                fetch_id=f"f-{day:04d}", fetched_at=f"2026-08-{day:02d}T00:00:00Z",
                company="Northwind Systems", company_slug="northwind-systems",
                manifest_path=f"m/{day}.json", profile="p"), {})
        return bp._finish(fold, bp._stamps())

    def test_a_foreign_jd_is_never_welded_to_another_jobs_title(self):
        backend = self._row("aa-1", "Senior Backend Engineer", "Northwind Systems",
                            "Northwind Systems is hiring a backend engineer to own "
                            "the billing ledger. Go and Postgres.")
        # A DIFFERENT posting, observed later, carrying no description of its own.
        scientist = self._row("bb-2", "Staff Data Scientist", "Larkspur Analytics", "")
        eb = self._fold((backend, 1), (scientist, 2))

        self.assertEqual(eb.posting["title"], "Staff Data Scientist")
        # The backend JD belongs to the OTHER posting: it must not ship here.
        self.assertEqual(eb.jd_text, "")
        self.assertNotIn("jd", eb.posting)
        conflict = eb.posting["provenance"].get("jd_conflict")
        self.assertIsNotNone(conflict, "dropping a JD must never be silent")
        self.assertEqual(conflict["jd_from"], {"source": "remoteok", "id": "aa-1"})
        self.assertEqual(conflict["entity_from"], {"source": "remoteok", "id": "bb-2"})

    def test_neither_absorbed_posting_loses_its_provenance(self):
        a = self._row("aa-1", "Senior Backend Engineer", "Northwind Systems", "JD A")
        b = self._row("bb-2", "Staff Data Scientist", "Larkspur Analytics", "JD B")
        eb = self._fold((a, 1), (b, 2))
        # Both postings stay named in source_ids even though one entity resulted.
        self.assertEqual([s["id"] for s in eb.posting["source_ids"]], ["aa-1", "bb-2"])

    def test_a_listing_only_rescrape_keeps_the_same_postings_jd(self):
        """The ordinary case must not regress: same posting, JD kept, title fresh.

        A re-scrape of ONE posting that returns no description is stale, not
        foreign — dropping its JD here would throw away the store's main content.
        """
        first = self._row("aa-1", "Senior Backend Engineer", "Northwind Systems",
                          "Own the billing ledger. Go and Postgres.")
        retitled = self._row("aa-1", "Senior Backend Engineer II",
                             "Northwind Systems", "")
        eb = self._fold((first, 1), (retitled, 2))
        self.assertEqual(eb.posting["title"], "Senior Backend Engineer II")
        self.assertEqual(eb.jd_text, "Own the billing ledger. Go and Postgres.")
        self.assertNotIn("jd_conflict", eb.posting["provenance"])
        # ...and the entity SAYS which observation the body came from.
        self.assertEqual(eb.posting["jd"]["from"], {"source": "remoteok", "id": "aa-1"})

    def test_an_unknown_posting_id_leaves_a_good_jd_alone(self):
        """Two rows with no id cannot be proven different — do not drop on a guess."""
        first = self._row(None, "Senior Backend Engineer", "Northwind Systems",
                          "Own the billing ledger.")
        later = self._row(None, "Senior Backend Engineer", "Northwind Systems", "")
        eb = self._fold((first, 1), (later, 2))
        self.assertEqual(eb.jd_text, "Own the billing ledger.")
        self.assertNotIn("jd_conflict", eb.posting["provenance"])

    def test_a_resumed_fold_recovers_the_jd_origin_from_derived(self):
        """Incremental must reach the same verdict as a rebuild.

        The origin is read back from the entity's own `jd.from`, so a fold resumed
        from derived files still refuses a foreign JD.
        """
        fold = bp._Fold("url-testkey")
        fold.resume(source_ids=[{"source": "remoteok", "id": "aa-1", "url": self.BOARD}],
                    profiles=["p"], fetch_ids=["f-0001"], events=[],
                    jd_text="Own the billing ledger.",
                    jd_origin=bp._jd_origin_of(
                        {"jd": {"from": {"source": "remoteok", "id": "aa-1"}}}),
                    prior={}, first_at="2026-08-01T00:00:00Z")
        fold.add(bp.Observation(
            key="url-testkey", strength=bp.ident.STRONG,
            row=self._row("bb-2", "Staff Data Scientist", "Larkspur Analytics", ""),
            fetch_id="f-0002", fetched_at="2026-08-02T00:00:00Z",
            company="Northwind Systems", company_slug="northwind-systems",
            manifest_path="m/2.json", profile="p"), {})
        eb = bp._finish(fold, bp._stamps())
        self.assertEqual(eb.jd_text, "")
        self.assertIn("jd_conflict", eb.posting["provenance"])


if __name__ == "__main__":
    unittest.main()
