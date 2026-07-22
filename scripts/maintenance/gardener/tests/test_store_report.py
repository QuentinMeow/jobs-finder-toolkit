"""Tests for the store-report gardener routine (report-only, always).

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s scripts/maintenance/gardener/tests \
        -t scripts/maintenance/gardener/tests

Isolation is via a copy of the tracked fictional fixture store under a tempdir +
``JOBHUNT_DATA_ROOT`` — never the real store, and the routine never mutates.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import store_report  # noqa: E402
from store.paths import DomainLayout  # noqa: E402

REPO_ROOT = GARDENER_DIR.parents[2]
FIXTURE = REPO_ROOT / "examples" / "data"


class StoreReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "data"
        shutil.copytree(FIXTURE, self.root)
        self.layout = DomainLayout(root=self.root / "jobs", domain="jobs")
        self._prev = os.environ.get("JOBHUNT_DATA_ROOT")
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.root)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prev
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runs_clean_on_the_fixture(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = store_report.run()
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("validate_store: OK", out)
        self.assertIn("zone sizes:", out)
        self.assertIn("present blobs:", out)

    def test_reports_a_planted_stale_alloc_lock(self):
        # The identifier alloc lock has NO auto-steal — report it loudly at any age.
        (self.layout.state / store_report.ALLOC_LOCK_NAME).write_text("12345")
        r = store_report.report_domain(self.layout)
        self.assertIsNotNone(r["alloc_lock_age"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            store_report._print_domain(r)
        out = buf.getvalue()
        self.assertIn("identifier alloc lock: PRESENT", out)
        self.assertIn("NO auto-steal", out)

    def test_reports_a_planted_torn_tail(self):
        # A half-flushed append (no trailing newline) is a torn tail — detect+report.
        ledger = self.layout.build_ledger
        with open(ledger, "ab") as fh:
            fh.write(b'{"fetch_id": "torn", "seq": 999')  # no newline → torn
        r = store_report.report_domain(self.layout)
        self.assertIn(ledger, r["torn"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            store_report._print_domain(r)
        self.assertIn("torn JSONL tails", buf.getvalue())

    def test_reports_stale_builder_lock(self):
        import time
        from store.constants import LOCK_STALE_SECONDS
        lock = self.layout.lock_path()
        lock.write_text("{}")
        old = time.time() - (LOCK_STALE_SECONDS + 60)
        os.utime(lock, (old, old))
        r = store_report.report_domain(self.layout)
        self.assertGreaterEqual(r["builder_lock_age"], LOCK_STALE_SECONDS)


if __name__ == "__main__":
    unittest.main()
