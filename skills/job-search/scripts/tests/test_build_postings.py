"""Builder tests: determinism, incremental==rebuild, orphan hard-fail, suppression,
weak identity, changed events, opinions-only diff, ATS-migration links, key pinning.

Every test isolates the store to a throwaway ``JOBHUNT_DATA_ROOT`` and asserts
containment — no test writes into the real ``private/data`` store.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS_DIR), str(_SCRIPTS_DIR / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_postings as bp  # noqa: E402
from _vendor.store import serialization  # noqa: E402
from _vendor.store.atomic import atomic_write_text  # noqa: E402
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
        self.data_root = Path(tempfile.mkdtemp(prefix="build-test-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.data_root)
        self.layout = domain_layout(self.data_root, "jobs")

    def tearDown(self):
        if self._prior is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior
        shutil.rmtree(self.data_root, ignore_errors=True)

    def _session(self):
        return CaptureSession("jobs", self.data_root, tool_version="test")

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
        return bp.main(argv + ["--data-root", str(self.data_root)])

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
    def _snapshot(self, dst):
        shutil.rmtree(dst, ignore_errors=True)
        os.makedirs(dst)
        shutil.copytree(self.layout.derived, Path(dst) / "derived")
        shutil.copytree(self.layout.index, Path(dst) / "index")

    def _tree_bytes(self, root):
        out = {}
        for p in sorted(Path(root).rglob("*")):
            if p.is_file():
                out[str(p.relative_to(root))] = p.read_bytes()
        return out

    def test_staged_incremental_equals_rebuild(self):
        # stage 1: day-14 board
        self._capture_gh([_job(111, "SWE", "Austin, TX"),
                          _job(222, "SRE", "Remote, US")], _dt(14))
        self.assertEqual(self._build([]), 0)
        # stage 2: day-15 board — gh-111 changed location (Austin -> Seattle)
        self._capture_gh([_job(111, "SWE", "Seattle, WA"),
                          _job(222, "SRE", "Remote, US")], _dt(15))
        self.assertEqual(self._build([]), 0)
        snap = tempfile.mkdtemp(prefix="snap-")
        self._snapshot(snap)
        incr_d = self._tree_bytes(Path(snap) / "derived")
        incr_i = self._tree_bytes(Path(snap) / "index")

        # full rebuild over the same raw must be byte-identical
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertEqual(self._tree_bytes(self.layout.derived), incr_d,
                         "derived: incremental != rebuild")
        self.assertEqual(self._tree_bytes(self.layout.index), incr_i,
                         "index: incremental != rebuild")

        # rebuild again — byte-identical to the first rebuild
        rb1_d = self._tree_bytes(self.layout.derived)
        self.assertEqual(self._build(["--rebuild"]), 0)
        self.assertEqual(self._tree_bytes(self.layout.derived), rb1_d,
                         "derived: rebuild != rebuild")
        shutil.rmtree(snap, ignore_errors=True)

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


if __name__ == "__main__":
    unittest.main()
