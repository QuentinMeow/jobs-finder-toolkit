"""Stage-3 store-integration tests for search_jobs.py.

Covers: the run-summary store line (present when enabled, absent when disabled →
byte-identical summary), the N/M + url-map read, the guarded post-fetch build
(disabled → no-op; enabled tiny store → real line), store_key threading into
--json-out only (never into to_dict / snapshots), and snapshot byte-invariance.

Every test isolates the store to a throwaway JOBHUNT_DATA_ROOT; the disabled test
force-nulls config.data_root so it can never touch the machine's real store.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import search_jobs  # noqa: E402
import snapshot  # noqa: E402
from common import JobPosting  # noqa: E402
from _vendor.store.capture import CaptureSession  # noqa: E402
from _vendor.store.paths import domain_layout  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PRIVATE_DATA = _REPO_ROOT / "private" / "data"


def _meta(n_raw=1, kept=1):
    return {"stage": 1, "n_companies": 1, "aggregators": [], "n_raw": n_raw,
            "n_review": 0}


class SummaryLineTests(unittest.TestCase):
    def _summary(self, store_line):
        return search_jobs.render_run_summary(
            _meta(), [], snapshot_display="snap", discoveries_path="disc",
            json_path=None, store_line=store_line)

    def test_store_line_appended_when_present(self):
        out = self._summary("store: 42 tracked, 5 new since your last review")
        self.assertIn("store: 42 tracked, 5 new since your last review", out)

    def test_no_store_line_when_disabled_is_byte_identical(self):
        # Disabled store (store_line=None) → summary identical to pre-integration.
        self.assertEqual(self._summary(None).count("store:"), 0)
        self.assertEqual(self._summary(None), self._summary(""))


class ReadStatusTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="store-status-"))
        self.layout = domain_layout(self.root, "jobs")
        idx = self.layout.index / "postings.jsonl"
        idx.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"_schema": 1, "built_at": "2026-07-20T00:00:00Z", "note": "x"},
            {"key": "gh-1", "canonical_url": "https://x.test/1", "seq": 1},
            {"key": "gh-2", "canonical_url": "https://x.test/2", "seq": 2},
            {"key": "gh-3", "canonical_url": "https://x.test/3", "seq": 3},
        ]
        idx.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        # cursor at seq 1 → 2 entities are "new"
        self.layout.state.mkdir(parents=True, exist_ok=True)
        self.layout.cursors.write_text(
            "schema_version: 1\ncursors:\n  shortlist-review:\n    seq: 1\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_counts_and_url_map(self):
        line, url_map = search_jobs._read_store_status(self.layout)
        self.assertEqual(line, "store: 3 tracked, 2 new since your last review")
        self.assertEqual(url_map, {"https://x.test/1": "gh-1",
                                   "https://x.test/2": "gh-2",
                                   "https://x.test/3": "gh-3"})

    def test_no_cursor_wording(self):
        self.layout.cursors.unlink()  # no shortlist-review cursor exists
        line, _ = search_jobs._read_store_status(self.layout)
        self.assertEqual(
            line, "store: 3 tracked, 3 new (no review cursor yet — see reference)")

    def test_canonical_url_collision_resolves_to_no_key(self):
        # A shadow entity (aggregator url- key) sharing gh-1's canonical_url:
        # last-writer-wins would hand out a WRONG key, so the URL maps to NO key.
        idx = self.layout.index / "postings.jsonl"
        lines = idx.read_text().splitlines()
        lines.append(json.dumps(
            {"key": "url-abc", "canonical_url": "https://x.test/1", "seq": 4}))
        idx.write_text("\n".join(lines) + "\n")
        _line, url_map = search_jobs._read_store_status(self.layout)
        self.assertNotIn("https://x.test/1", url_map)          # collision → absent
        self.assertEqual(url_map.get("https://x.test/2"), "gh-2")  # others unaffected
        from common import JobPosting
        p = JobPosting(source="greenhouse", company="c", title="t",
                       url="https://x.test/1")
        rows = search_jobs._json_rows_with_store_key([p], url_map)
        self.assertIsNone(rows[0]["store_key"])               # null, never the wrong key


class StoreKeyValidationTests(unittest.TestCase):
    def test_empty_and_absent_ok_nonempty_format_checked(self):
        from job_metadata import _validate_store_key
        self.assertEqual(_validate_store_key(None, "store_key"), [])
        self.assertEqual(_validate_store_key("", "store_key"), [])       # unset default
        self.assertEqual(_validate_store_key("gh-1234567", "store_key"), [])
        self.assertEqual(_validate_store_key("wd-nvidia-jr100", "store_key"), [])
        self.assertTrue(_validate_store_key("GH-777", "store_key"))      # uppercase → error
        self.assertTrue(_validate_store_key(42, "store_key"))            # non-string → error


class GuardedBuildTests(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.get("JOBHUNT_DATA_ROOT")
        self.root = Path(tempfile.mkdtemp(prefix="store-build-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.root)

    def tearDown(self):
        if self._prior is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior
        shutil.rmtree(self.root, ignore_errors=True)

    def _private_files(self):
        if not _PRIVATE_DATA.is_dir():
            return set()
        return {str(p) for p in _PRIVATE_DATA.rglob("*") if p.is_file()}

    def test_disabled_store_is_noop(self):
        # Force config.data_root -> None so it can never touch the real store.
        orig = search_jobs.config.data_root
        before = self._private_files()
        try:
            search_jobs.config.data_root = lambda: None
            line, url_map = search_jobs.run_post_fetch_store_build()
        finally:
            search_jobs.config.data_root = orig
        self.assertIsNone(line)
        self.assertEqual(url_map, {})
        self.assertEqual(self._private_files(), before)  # containment

    def test_enabled_build_reports_line_and_urlmap(self):
        sess = CaptureSession("jobs", self.root, tool_version="test")
        job = {"id": "777", "title": "Platform Engineer",
               "location": {"name": "Remote, US"},
               "absolute_url": "https://boards.greenhouse.io/co/jobs/777",
               "content": "Build.", "first_published": "2026-07-15T00:00:00Z",
               "company_name": "Co", "metadata": []}
        sess.capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/co/jobs"},
            status=200, payload_bytes=json.dumps({"jobs": [job]}).encode(),
            content_type="application/json",
            fetched_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            context={"company": "co", "profile": "profile-01"})
        line, url_map = search_jobs.run_post_fetch_store_build()
        self.assertIsNotNone(line)
        self.assertTrue(line.startswith("store: 1 tracked, 1 new"))
        # the posting's canonicalized URL resolves to its store key
        from posting_identity import canonicalize_url
        self.assertEqual(
            url_map.get(canonicalize_url("https://boards.greenhouse.io/co/jobs/777")),
            "gh-777")


class DisabledStoreNoticeTests(unittest.TestCase):
    """Decision 1: a real config layer with data_root left unset gets a loud,
    non-fatal stderr notice on the fetch path; an example/no config layer stays
    silent (unchanged default) — see search_jobs._config_layer_present."""

    def setUp(self):
        self._orig_data_root = search_jobs.config.data_root
        self._orig_config_path = search_jobs.config.config_path
        search_jobs.config.data_root = lambda: None

    def tearDown(self):
        search_jobs.config.data_root = self._orig_data_root
        search_jobs.config.config_path = self._orig_config_path

    def test_notice_printed_when_real_config_layer_present(self):
        search_jobs.config.config_path = lambda: Path("/tmp/real-config.yaml")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            line, url_map = search_jobs.run_post_fetch_store_build()
        self.assertIsNone(line)
        self.assertEqual(url_map, {})
        self.assertIn("store: not configured", buf.getvalue())
        self.assertIn("JOBHUNT_DATA_ROOT", buf.getvalue())

    def test_notice_silent_on_example_config(self):
        search_jobs.config.config_path = lambda: search_jobs.config.EXAMPLE_CONFIG
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            line, url_map = search_jobs.run_post_fetch_store_build()
        self.assertIsNone(line)
        self.assertEqual(url_map, {})
        self.assertEqual(buf.getvalue(), "")

    def test_config_layer_present_helper_guards_exceptions(self):
        search_jobs.config.config_path = lambda: (_ for _ in ()).throw(OSError("x"))
        self.assertFalse(search_jobs._config_layer_present())


class VendoredExampleConfigTests(unittest.TestCase):
    """The example test must hold through the VENDORED config import, unpatched.

    The sibling tests above stub ``config.config_path``, so they compare
    ``EXAMPLE_CONFIG`` with itself and pass no matter where that constant points.
    This one runs the real thing: a fresh interpreter, ``$JOBHUNT_CONFIG`` aimed at
    the tracked ``config.example.yaml``, ``search_jobs`` importing
    ``scripts/_vendor/config.py``. Vendored four levels below the repo root, a
    parent-count ``REPO_ROOT`` made ``EXAMPLE_CONFIG`` a path that can never match
    anything, so ``_config_layer_present()`` answered True on an example-config run
    and the "store: not configured" notice fired in a bare public checkout.
    """

    def _probe(self, expr: str) -> str:
        env = dict(os.environ)
        env.pop("JOBHUNT_REQUIRE_REAL_CONFIG", None)
        env["JOBHUNT_CONFIG"] = str(_REPO_ROOT / "config.example.yaml")
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "import search_jobs\n"
             "print(%s)" % (str(_SCRIPTS), expr)],
            cwd=_REPO_ROOT, capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_config_layer_absent_on_the_tracked_example_config(self):
        self.assertEqual(self._probe("search_jobs._config_layer_present()"), "False")

    def test_vendored_example_config_constant_points_at_a_real_file(self):
        self.assertEqual(self._probe("search_jobs.config.EXAMPLE_CONFIG.is_file()"),
                         "True")


class JsonThreadingTests(unittest.TestCase):
    def _posting(self, url):
        p = JobPosting(source="greenhouse", company="Co", title="SWE", url=url)
        return p

    def test_store_key_added_to_json_only(self):
        url = "https://boards.greenhouse.io/co/jobs/777"
        p = self._posting(url)
        from posting_identity import canonicalize_url
        url_map = {canonicalize_url(url): "gh-777"}
        rows = search_jobs._json_rows_with_store_key([p], url_map)
        self.assertEqual(rows[0]["store_key"], "gh-777")
        # to_dict itself is NOT mutated (snapshots use posting_to_dict; nothing here
        # adds store_key to the JobPosting's own serialization)
        self.assertNotIn("store_key", p.to_dict())

    def test_store_key_absent_cleanly_on_no_match(self):
        p = self._posting("https://other.test/x")
        rows = search_jobs._json_rows_with_store_key([p], {"https://x/1": "gh-1"})
        self.assertIsNone(rows[0]["store_key"])


class RefilterStoreIdentityTests(unittest.TestCase):
    """A no-change ``--refilter`` replay must not lose the identity a fetch had.

    The snapshot is written BEFORE the run's store build, so replaying it emitted
    ``store_key: null`` for every posting while a fresh run of the byte-identical
    rows emitted real keys — the users are told to refilter before acting, so the
    final artifact was the one with the weakest provenance.
    """

    URL = "https://boards.greenhouse.io/co/jobs/777"

    def setUp(self):
        self._prior = os.environ.get("JOBHUNT_DATA_ROOT")
        self.root = Path(tempfile.mkdtemp(prefix="store-replay-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.root)
        self.tmp = Path(tempfile.mkdtemp(prefix="store-replay-cache-"))
        self.fetched_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    def tearDown(self):
        if self._prior is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_store(self):
        """Capture one greenhouse board payload and build the index from it."""
        sess = CaptureSession("jobs", self.root, tool_version="test")
        job = {"id": "777", "title": "Senior Backend Engineer",
               "location": {"name": "Remote, US"}, "absolute_url": self.URL,
               "content": "Python, Kubernetes, AWS, distributed systems, api.",
               "first_published": self.fetched_at.isoformat(),
               "company_name": "Northwind Robotics", "metadata": []}
        sess.capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/co/jobs"},
            status=200, payload_bytes=json.dumps({"jobs": [job]}).encode(),
            content_type="application/json", fetched_at=self.fetched_at,
            context={"company": "co", "profile": "profile-01"})
        with contextlib.redirect_stderr(io.StringIO()):
            return search_jobs.run_post_fetch_store_build()

    def _snapshot(self):
        p = JobPosting(
            source="board", company="Northwind Robotics",
            title="Senior Backend Engineer", url=self.URL, location="Remote, US",
            remote="remote", posted_at=self.fetched_at - timedelta(days=1),
            description="Python, Kubernetes, AWS, distributed systems, api.")
        snap_path, _ = snapshot.write_snapshot(
            self.tmp, profile="example", stage=1, fetched_at=self.fetched_at,
            source_selection={"n_companies": 1, "aggregators": [],
                              "max_age_days_at_fetch": None},
            postings=[p], errors=[])
        return snap_path

    def _tree(self):
        return {str(p): (p.stat().st_mtime_ns, p.stat().st_size)
                for p in self.root.rglob("*") if p.is_file()}

    def test_refilter_emits_the_same_store_key_a_fetch_would(self):
        _line, fetch_map = self._build_store()
        from posting_identity import canonicalize_url
        fetch_key = fetch_map.get(canonicalize_url(self.URL))
        self.assertEqual(fetch_key, "gh-777")          # what a fresh run emits

        snap_path = self._snapshot()
        out_json = self.tmp / "matches.json"
        argv = ["search_jobs.py", "--profile", "example", "--cache-dir",
                str(self.tmp), "--refilter", str(snap_path),
                "--out", str(self.tmp / "m.md"), "--json-out", str(out_json),
                "--sponsor-index", str(self.tmp / "none.json")]
        old = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = search_jobs.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 0)
        rows = json.loads(out_json.read_text())
        self.assertEqual([r["store_key"] for r in rows], [fetch_key])

    def test_the_replay_lookup_reads_the_index_and_writes_nothing(self):
        self._build_store()
        before = self._tree()
        line, url_map = search_jobs.read_store_status_for_replay()
        from posting_identity import canonicalize_url
        self.assertEqual(url_map.get(canonicalize_url(self.URL)), "gh-777")
        self.assertTrue(line.startswith("store: 1 tracked"))
        # A replay is not a fetch: no build, no lock, not one byte rewritten.
        self.assertEqual(self._tree(), before)

    def test_a_store_that_was_never_built_is_not_an_error(self):
        line, url_map = search_jobs.read_store_status_for_replay()
        self.assertIsNone(line)
        self.assertEqual(url_map, {})

    def test_disabled_store_replay_is_a_silent_noop(self):
        orig = search_jobs.config.data_root
        buf = io.StringIO()
        try:
            search_jobs.config.data_root = lambda: None
            with contextlib.redirect_stderr(buf):
                line, url_map = search_jobs.read_store_status_for_replay()
        finally:
            search_jobs.config.data_root = orig
        self.assertIsNone(line)
        self.assertEqual(url_map, {})
        self.assertEqual(buf.getvalue(), "")


class SnapshotInvarianceTests(unittest.TestCase):
    def test_snapshot_bytes_unaffected_by_store_key_threading(self):
        cache = Path(tempfile.mkdtemp(prefix="snap-inv-"))
        try:
            posts = [JobPosting(source="greenhouse", company="Co", title="SWE",
                                url="https://boards.greenhouse.io/co/jobs/777")]
            now = datetime(2026, 7, 15, tzinfo=timezone.utc)
            p1, _ = snapshot.write_snapshot(cache, profile="p", stage=1, fetched_at=now,
                                            source_selection={}, postings=posts, errors=[])
            b1 = Path(p1).read_bytes()
            # Thread store_key into json-out (mutates only the dict copy)…
            search_jobs._json_rows_with_store_key(posts, {"https://x/1": "gh-1"})
            # …then re-snapshot the SAME postings → byte-identical.
            p2, _ = snapshot.write_snapshot(cache, profile="p", stage=1, fetched_at=now,
                                            source_selection={}, postings=posts, errors=[])
            self.assertEqual(Path(p2).read_bytes(), b1)
        finally:
            shutil.rmtree(cache, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
