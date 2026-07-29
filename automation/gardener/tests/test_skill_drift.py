"""Tests for the skill-drift gardener routine.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/maintenance/gardener/tests \
        -t automation/maintenance/gardener/tests

The routine is path-injected (find_drift takes explicit baseline/profile paths), so
these tests use throwaway fixture files — no config layer or private overlay needed.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import skill_drift  # noqa: E402

PROFILE = textwrap.dedent("""\
    # Profile

    ## Skills

    ### Approved (include in most resumes)

    - Programming Languages: Python, Go, SQL
    - Skills: REST APIs, distributed systems, CI/CD, observability

    ### Weak (only with an explicit JD mention)

    - Cloud & Infra: AWS (Lambda, SQS, SNS), Kafka

    ### Never (never include)

    - Languages: Rust, Scala

    ## Experience

    Nothing to see here.
    """)


class SkillDriftTests(unittest.TestCase):
    def _write(self, tmp: Path, baseline: str, profile: str = PROFILE):
        (tmp / "baseline.yaml").write_text(baseline, encoding="utf-8")
        (tmp / "profile.md").write_text(profile, encoding="utf-8")
        return tmp / "baseline.yaml", tmp / "profile.md"

    def test_canonical_baseline_has_no_drift(self):
        baseline = textwrap.dedent("""\
            skills:
              - label: "Programming Languages"
                items: "Python, Go, SQL"
              - label: "Skills"
                items: "REST APIs, distributed systems, CI/CD"
            """)
        with tempfile.TemporaryDirectory() as t:
            bp, pp = self._write(Path(t), baseline)
            res = skill_drift.find_drift(bp, pp)
        self.assertTrue(res["canonical_available"])
        self.assertEqual(res["checked"], 6)
        self.assertEqual(res["drift"], [])

    def test_non_canonical_spelling_is_flagged(self):
        # "Distributed System" (singular) drifts from canonical "distributed systems".
        baseline = textwrap.dedent("""\
            skills:
              - label: "Skills"
                items: "REST APIs, Distributed System, TotallyUnknownSkill"
            """)
        with tempfile.TemporaryDirectory() as t:
            bp, pp = self._write(Path(t), baseline)
            res = skill_drift.find_drift(bp, pp)
        flagged = {d["token"] for d in res["drift"]}
        self.assertIn("Distributed System", flagged)
        self.assertIn("TotallyUnknownSkill", flagged)
        self.assertNotIn("REST APIs", flagged)

    def test_parenthesized_canonical_recognizes_members(self):
        # A bare "AWS" / "Lambda" must match the canonical "AWS (Lambda, SQS, SNS)".
        baseline = textwrap.dedent("""\
            skills:
              - label: "Skills"
                items: "AWS, Lambda, Kafka"
            """)
        with tempfile.TemporaryDirectory() as t:
            bp, pp = self._write(Path(t), baseline)
            res = skill_drift.find_drift(bp, pp)
        self.assertEqual(res["drift"], [])

    def test_never_list_spelling_counts_as_canonical(self):
        baseline = textwrap.dedent("""\
            skills:
              - label: "Skills"
                items: "Rust"
            """)
        with tempfile.TemporaryDirectory() as t:
            bp, pp = self._write(Path(t), baseline)
            res = skill_drift.find_drift(bp, pp)
        # "Rust" is a canonical spelling (in the Never list), so it is not drift —
        # the routine flags misspellings, not policy placement.
        self.assertEqual(res["drift"], [])

    def test_missing_baseline_degrades_gracefully(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "profile.md").write_text(PROFILE, encoding="utf-8")
            res = skill_drift.find_drift(tmp / "absent.yaml", tmp / "profile.md")
        self.assertFalse(res["baseline_exists"])
        self.assertEqual(res["drift"], [])

    def test_profile_without_skills_section_is_not_validated(self):
        baseline = textwrap.dedent("""\
            skills:
              - label: "Skills"
                items: "AnythingGoes"
            """)
        with tempfile.TemporaryDirectory() as t:
            bp, pp = self._write(Path(t), baseline, profile="# Profile\n\nNo skills here.\n")
            res = skill_drift.find_drift(bp, pp)
        self.assertFalse(res["canonical_available"])
        self.assertEqual(res["drift"], [])

    def test_run_is_report_only_and_exits_zero(self):
        # run() uses the config layer; with the tracked example config it is clean.
        self.assertEqual(skill_drift.run(), 0)


if __name__ == "__main__":
    unittest.main()
