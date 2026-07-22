"""Golden test for the compact stdout contract (summary + top-K table).

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests

No network: pure rendering of hand-built postings.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import search_jobs  # noqa: E402
from common import JobPosting  # noqa: E402


def _row(company, title, url, score, level, age, visa):
    p = JobPosting(source="board", company=company, title=title, url=url)
    p.score = score
    p.job_level = {"normalized": level}
    p.age_days = age
    p.visa_label = visa
    return p


# Fixed-width, deterministic: company clipped to 20, title to 32, URL last (unpadded,
# so no line has trailing whitespace). This is the contract agents read instead of
# dumping the discoveries file.
GOLDEN_TABLE = (
    "  #  Company               Title                              Score  Level"
    "          Age  Visa     URL\n"
    "------------------------------------------------------------------------"
    "------------------------  ---\n"
    "  1  Acme AI               Senior Backend Engineer               42  senior"
    "        0.5d  yes      https://acme.example/jobs/1\n"
    "  2  Beacon Labs Incorpor  Distributed Systems Engineer (Pl    33.5  mid"
    "           2.0d  unclear  https://beacon.example/careers/42\n"
    "  3  Delta                 Site Reliability Engineer             12  staff"
    "            ?  no       https://delta.example/j/7"
)


class CompactTableGoldenTests(unittest.TestCase):
    def _kept(self):
        return [
            _row("Acme AI", "Senior Backend Engineer",
                 "https://acme.example/jobs/1", 42.0, "senior", 0.5, "yes"),
            _row("Beacon Labs Incorporated Longname",
                 "Distributed Systems Engineer (Platform, Core Infra Team)",
                 "https://beacon.example/careers/42", 33.5, "mid", 2.0, "unclear"),
            _row("Delta", "Site Reliability Engineer",
                 "https://delta.example/j/7", 12.0, "staff", None, "no"),
        ]

    def test_table_matches_golden(self):
        self.assertEqual(search_jobs.render_compact_table(self._kept()), GOLDEN_TABLE)

    def test_no_line_has_trailing_whitespace(self):
        for line in search_jobs.render_compact_table(self._kept()).splitlines():
            self.assertEqual(line, line.rstrip(), f"trailing space in: {line!r}")

    def test_missing_age_renders_question_mark(self):
        table = search_jobs.render_compact_table(self._kept())
        self.assertRegex(table, r"staff\s+\?\s+no")   # age None -> "?"

    def test_run_summary_is_five_lines(self):
        meta = {"stage": 1, "n_companies": 42,
                "aggregators": ["jobicy", "themuse"], "n_raw": 1234}
        summary = search_jobs.render_run_summary(
            meta, self._kept(), snapshot_display="tmp/search_cache/example-stage1-x.json",
            discoveries_path="applications/1_discoveries/20260115-example.md",
            json_path=None)
        lines = summary.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("42 company boards + 2 aggregator sources", lines[0])
        self.assertIn("Fetched 1234 postings -> kept 3", lines[1])
        self.assertIn("example-stage1-x.json", lines[2])
        self.assertTrue(lines[4].endswith("-"))       # JSON: - when no --json-out

    def test_all_matches_bypasses_top_k_and_diversity(self):
        postings = self._kept()
        selected = search_jobs.select_diverse(
            postings, top_k=None, max_per_company=1)
        self.assertEqual(selected, postings)

    def test_dedupe_keeps_highest_scoring_row_not_fetch_order(self):
        low = _row("Acme AI", "Senior Backend Engineer",
                   "https://acme.example/jobs/old", 10, "senior", 3, "unclear")
        high = _row("acme ai", "senior backend engineer",
                    "https://acme.example/jobs/best", 40, "senior", 1, "yes")
        self.assertEqual(search_jobs.dedupe([low, high]), [high])

    def test_review_report_is_written_and_stale_report_is_removed(self):
        posting = self._kept()[0]
        posting.review_reasons = ["location_requires_review"]
        with TemporaryDirectory() as tmp:
            path = search_jobs.write_review_report([posting], Path(tmp), "example")
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text())["count"], 1)
            self.assertIsNone(
                search_jobs.write_review_report([], Path(tmp), "example"))
            self.assertFalse(path.exists())

    def test_json_output_creates_nested_parent_directory(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "audit" / "matches.json"
            written = search_jobs.write_json_output(path, self._kept(), {})
            self.assertEqual(written, path)
            self.assertEqual(len(json.loads(path.read_text())), 3)


if __name__ == "__main__":
    unittest.main()
