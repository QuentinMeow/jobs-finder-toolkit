"""Tests for the roadmap-staleness gardener routine.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests

This routine exists because age used to be enforced by the reconciler, which runs in
pre-commit AND CI — so a roadmap nobody had re-dated for a month would have failed
every commit in the repo. The two properties worth pinning are therefore the two that
make it a reminder rather than a gate: it FINDS the stale roadmap, and it exits 0 while
doing so. A third pins the shared parser, because the whole reason the reminder can be
trusted is that it reads the date exactly the way the gate does.

Every test runs against a throwaway tree (``C.REPO_ROOT`` is redirected), never the
real repo and never the overlay — ``test_fixture_isolation.py`` is the standing guard
for the folder.
"""
from __future__ import annotations

import datetime
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import roadmap_staleness as RS  # noqa: E402

TODAY = datetime.date(2026, 7, 31)


class TempTree(unittest.TestCase):

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="roadmap-staleness-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        saved = RS.C.REPO_ROOT
        RS.C.REPO_ROOT = self.root
        self.addCleanup(lambda: setattr(RS.C, "REPO_ROOT", saved))

    def write(self, body: str) -> None:
        (self.root / "docs/roadmap").mkdir(parents=True, exist_ok=True)
        (self.root / "docs/roadmap/current-state.md").write_text(body, encoding="utf-8")

    def report(self) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = RS.run(today=TODAY)
        self.assertEqual(rc, 0, "the routine must never fail a caller")
        return buf.getvalue()


class TestStaleness(TempTree):

    def test_a_year_stale_roadmap_is_reported(self) -> None:
        self.write("- **Last-updated**: 2025-07-30\n")
        res = RS.analyze(today=TODAY)
        self.assertTrue(res["stale"])
        self.assertEqual(res["age"], 366)
        self.assertIn("STALE", self.report())

    def test_reporting_a_stale_roadmap_still_exits_zero(self) -> None:
        """The property the whole redesign turns on: this blocks nothing."""
        self.write("- **Last-updated**: 2020-01-01\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(RS.run(today=TODAY), 0)
        self.assertIn("STALE", buf.getvalue())

    def test_the_boundary_is_the_declared_limit(self) -> None:
        edge = TODAY - datetime.timedelta(days=RS.MAX_AGE_DAYS)
        self.write(f"- **Last-updated**: {edge.isoformat()}\n")
        self.assertFalse(RS.analyze(today=TODAY)["stale"],
                         "exactly at the limit is not yet stale")
        over = TODAY - datetime.timedelta(days=RS.MAX_AGE_DAYS + 1)
        self.write(f"- **Last-updated**: {over.isoformat()}\n")
        self.assertTrue(RS.analyze(today=TODAY)["stale"])

    def test_a_fresh_roadmap_says_current(self) -> None:
        self.write("- **Last-updated**: 2026-07-30\n")
        self.assertFalse(RS.analyze(today=TODAY)["stale"])
        report = self.report()
        self.assertIn("day(s) old", report, report)
        self.assertNotIn("STALE", report, report)

    def test_an_absent_roadmap_is_not_an_error(self) -> None:
        """The published export ships no docs/roadmap/."""
        self.assertFalse((self.root / "docs/roadmap").exists())
        self.assertFalse(RS.analyze(today=TODAY)["exists"])
        self.assertIn("nothing to check", self.report())

    def test_malformed_dates_defer_to_the_gate(self) -> None:
        """Those cases still FAIL a commit; this routine must not double-report them."""
        for body in ("- **Last-updated**: whenever\n",
                     "# Current state\n\nno date here\n",
                     "- **Last-updated**: 2027-01-01\n"):
            self.write(body)
            self.assertFalse(RS.analyze(today=TODAY)["stale"], body)
            self.assertIn("roadmap-dated", self.report(), body)

    def test_it_uses_the_reconcilers_parser(self) -> None:
        """One line, one reading — a second regex here could drift from the gate."""
        sys.path.insert(0, str(GARDENER_DIR.parent / "reconcile"))
        import reconcile  # noqa: PLC0415  (imported only for this identity check)
        self.assertIs(RS.reconcile.parse_last_updated, reconcile.parse_last_updated)
        # And it reads the same backticked/bolded spellings the gate accepts.
        self.write("- **Last-updated**: `2026-07-30`\n")
        self.assertEqual(RS.analyze(today=TODAY)["stamp"], datetime.date(2026, 7, 30))


class TestRegistration(unittest.TestCase):
    """A routine nobody can invoke is a file, not a routine."""

    def test_the_front_end_lists_it_and_runs_it_dry(self) -> None:
        import gardener  # noqa: PLC0415  (front-end imported only for this assertion)
        self.assertIn("roadmap-staleness", gardener.ROUTINES)
        self.assertIn("roadmap-staleness", gardener.ALL_ORDER)
        _, supports_apply = gardener.ROUTINES["roadmap-staleness"]
        self.assertFalse(supports_apply, "report-only: --apply must be a no-op")


if __name__ == "__main__":
    unittest.main()
