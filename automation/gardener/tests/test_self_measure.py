"""Tests for the self-measure gardener routine's skip-log funnel input.

``funnel.discovered`` counts POSTINGS the toolkit has already considered. Its
source is now the append-only applications skip-log, which holds one line per
EVENT: a posting that went drafted -> applied -> rejected occupies three lines and
must still count once. A raw line count would make the funnel climb every time any
posting merely changed status, so the metric silently inflates with no bad data
anywhere — which is why this is asserted rather than assumed.

No candidate data: every fixture is a temp-dir JSONL with fictional companies.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import self_measure  # noqa: E402


def _event(**row) -> str:
    event = {"company": "", "slug": "", "date": "2026-07-16", "status": "drafted",
             "role": "", "url": "", "recorded": "2026-07-16T09:00:00Z",
             "source": "sync"}
    event.update(row)
    return json.dumps(event)


class DiscoveredCountTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "applications-log.jsonl"
        self.addCleanup(self._tmp.cleanup)

    def _write(self, *lines: str):
        self.log.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def test_three_events_for_one_posting_count_as_one(self):
        url = "https://boards.example.com/nimbus/jobs/2001"
        self._write(
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url=url, status="drafted"),
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url=url, status="applied"),
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url=url, status="rejected"),
        )
        self.assertEqual(self_measure._discovered_count(self.log), 1)

    def test_distinct_postings_each_count_once(self):
        self._write(
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url="https://boards.example.com/nimbus/jobs/2001"),
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url="https://boards.example.com/nimbus/jobs/2001",
                   status="applied"),
            _event(company="Alpha Systems", role="Staff Backend Engineer",
                   url="https://boards.example.com/alpha/jobs/3001"),
            # A URL-less row folds on (company, role) — the branch that protects
            # the rows most likely to lose their folder.
            _event(company="Beacon Systems", role="Site Reliability Engineer"),
        )
        self.assertEqual(self_measure._discovered_count(self.log), 3)

    def test_a_forgotten_posting_leaves_the_count(self):
        url = "https://boards.example.com/nimbus/jobs/2001"
        self._write(
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url=url),
            _event(company="Alpha Systems", role="Staff Backend Engineer",
                   url="https://boards.example.com/alpha/jobs/3001"),
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url=url, forget=True),
        )
        self.assertEqual(self_measure._discovered_count(self.log), 1)

    def test_empty_log_counts_zero_and_a_missing_one_is_unknown(self):
        self.log.write_text("", encoding="utf-8")
        self.assertEqual(self_measure._discovered_count(self.log), 0)
        self.assertIsNone(
            self_measure._discovered_count(self.log.with_name("absent.jsonl")))


if __name__ == "__main__":
    unittest.main()
