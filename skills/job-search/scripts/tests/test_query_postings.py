"""query_postings tests: the design §5 example queries, cursors, and history.

Every test isolates the store to a throwaway ``JOBHUNT_DATA_ROOT``.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS_DIR), str(_SCRIPTS_DIR / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_postings as bp  # noqa: E402
import query_postings as qp  # noqa: E402
from _vendor.store import serialization  # noqa: E402
from _vendor.store.capture import CaptureSession  # noqa: E402
from _vendor.store.paths import domain_layout  # noqa: E402

UTC = timezone.utc


def _iso(days_ago):
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT00:00:00Z")


class QueryCase(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.get("JOBHUNT_DATA_ROOT")
        self.data_root = Path(tempfile.mkdtemp(prefix="query-test-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.data_root)
        self.layout = domain_layout(self.data_root, "jobs")
        sess = CaptureSession("jobs", self.data_root, tool_version="test")
        jobs = [
            {"id": 1234567, "title": "Remote SWE", "location": {"name": "Remote, US"},
             "absolute_url": "https://boards.greenhouse.io/examplecorp/jobs/1234567",
             "content": "We are happy to sponsor H-1B visas and green card process.",
             "first_published": _iso(2), "company_name": "ExampleCorp", "metadata": []},
            {"id": 222, "title": "Onsite SWE", "location": {"name": "Austin, TX"},
             "absolute_url": "https://boards.greenhouse.io/examplecorp/jobs/222",
             "content": "No visa sponsorship is available for this role.",
             "first_published": _iso(40), "company_name": "ExampleCorp", "metadata": []},
        ]
        sess.capture_fetch(
            source="greenhouse", operation="board",
            request={"url": "https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs"},
            status=200, payload_bytes=json.dumps({"jobs": jobs}).encode(),
            content_type="application/json",
            fetched_at=datetime.now(UTC) - timedelta(days=1),
            context={"company": "examplecorp", "profile": "profile-01"})
        self.assertEqual(bp.main(["--data-root", str(self.data_root)]), 0)

    def tearDown(self):
        if self._prior is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior
        shutil.rmtree(self.data_root, ignore_errors=True)

    def _q(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qp.main(argv + ["--data-root", str(self.data_root)])
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def _count(self, out):
        for line in out.splitlines():
            if line.strip().endswith("posting(s)") and not line.startswith("#"):
                return int(line.strip().split()[0])
        return None

    def test_company_query(self):
        out = self._q(["--company", "examplecorp"])
        self.assertEqual(self._count(out), 2)

    def test_visa_remote_maxage_query(self):
        # §5: --visa yes --workplace remote --max-age-days 7 → only the fresh remote row
        out = self._q(["--visa", "yes", "--workplace", "remote", "--max-age-days", "7"])
        self.assertEqual(self._count(out), 1)

    def test_new_since_cursor_then_mark_reviewed(self):
        # no cursor yet → everything is "new"
        out = self._q(["--new-since-cursor", "shortlist-review", "--profile", "profile-01"])
        self.assertEqual(self._count(out), 2)
        # advance the cursor to the max seq displayed
        self._q(["--new-since-cursor", "shortlist-review", "--mark-reviewed",
                 "shortlist-review"])
        # nothing new after the cursor advanced (advance-after-action)
        out2 = self._q(["--new-since-cursor", "shortlist-review"])
        self.assertEqual(self._count(out2), 0)

    def test_since_override(self):
        out = self._q(["--since", "0"])
        self.assertEqual(self._count(out), 2)
        out = self._q(["--since", "999999"])
        self.assertEqual(self._count(out), 0)

    def test_key_history(self):
        out = self._q(["--key", "gh-1234567", "--history"])
        self.assertIn("gh-1234567", out)
        self.assertIn("first_seen", out)

    def test_jsonl_output(self):
        out = self._q(["--company", "examplecorp", "--jsonl"])
        rows = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
        self.assertEqual(len(rows), 2)

    def test_profile_membership_filter(self):
        # all fetches were captured under profile-01
        self.assertEqual(self._count(self._q(["--profile", "profile-01"])), 2)
        self.assertEqual(self._count(self._q(["--profile", "profile-99"])), 0)


if __name__ == "__main__":
    unittest.main()
