"""The frozen sponsorship verdict matrix is a gate, not a document.

A matrix that is only run by hand is the matrix this repo already had — rebuilt
from scratch on each of five passes over the classifier and lost each time. This
wires it into the unit suite so a sponsorship edit that moves a tripwire row
fails before it is committed.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sponsorship_matrix import (  # noqa: E402
    FIELDS,
    lint_matrix,
    load_matrix,
    replay,
)


class SponsorshipVerdictMatrixTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.matrix = load_matrix()
        cls.records = replay(cls.matrix)

    def test_matrix_is_well_formed(self):
        self.assertEqual(lint_matrix(self.matrix), [])

    def test_matrix_covers_the_groups_it_was_built_for(self):
        """The row set is the argument; a silently shrunk matrix proves nothing."""
        groups = {record["group"] for record in self.records}
        for required in (
            "corpus",
            "known-issue-reproduction",
            "deliberately-not-fixed",
            "no-signal-citizenship-denial",
            "denial-coverage-gap",
            "conditional-offer",
            "h1b-transfer-scope",
            "control",
        ):
            self.assertIn(required, groups)
        self.assertGreaterEqual(len(self.records), 75)

    def test_every_row_agrees_with_its_asserted_reading(self):
        disagreeing = [record for record in self.records if not record["agrees"]]
        if not disagreeing:
            return
        report = []
        for record in disagreeing:
            report.append(record["id"])
            for field in FIELDS:
                if record["asserted"][field] != record["live"][field]:
                    report.append(
                        f"    {field}: asserted {record['asserted'][field]!r} "
                        f"but reads {record['live'][field]!r}")
        self.fail("matrix rows disagree with their asserted reading:\n"
                  + "\n".join(report))

    def test_no_signal_citizenship_denials_are_still_refusals(self):
        """The Step-1 prefilter's whole safety argument, asserted directly.

        Five settled denials in ``_SPONSOR_NEGATIVE`` contain no sponsorship,
        visa or immigration word at all. Any prefilter gated on a "signal word"
        — the shape GH #231 proposes — converts every one of them from a
        confident refusal into ``review``, silently, in the expensive direction.
        """
        rows = [record for record in self.records
                if record["group"] == "no-signal-citizenship-denial"]
        self.assertEqual(len(rows), 5)
        for record in rows:
            with self.subTest(record["id"]):
                self.assertEqual(record["live"]["decision"], "no_match")
                self.assertEqual(record["live"]["verdict"], "unlikely")


if __name__ == "__main__":
    unittest.main()
