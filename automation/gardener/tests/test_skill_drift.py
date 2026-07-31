"""Tests for the skill-drift gardener routine.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests

``find_drift`` is path-injected (it takes explicit baseline/profile paths), so most of
these tests use throwaway fixture files and never touch the config layer. ``run()`` is
the exception: it resolves both paths through the accessors, so its test PINS
``JOBHUNT_CONFIG`` at a fixture config and asserts the resolved paths land inside that
fixture. ``test_fixture_isolation.py`` is the standing guard for the whole folder.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import textwrap
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import skill_drift  # noqa: E402
import config  # noqa: E402  (bootstrapped onto sys.path by skill_drift's _common)

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

# A complete config whose every path is relative to the config file's own directory,
# so pinning JOBHUNT_CONFIG at a temp copy confines every accessor to that temp tree.
FIXTURE_CONFIG = textwrap.dedent("""\
    candidate:
      name: "Fixture Candidate"
    paths:
      profile_md: "profile.md"
      baseline_yaml: "baseline.yaml"
      applications_root: "applications"
    """)


@contextmanager
def _pinned_config(tmp: Path):
    """Run with ``JOBHUNT_CONFIG`` pinned at ``tmp/config.yaml`` and the cache cleared.

    Without the pin, discovery walks up from the module's directory and finds the
    checkout's own git-ignored ``config.yaml`` — which on a maintainer machine points
    every accessor into the private overlay.
    """
    saved = os.environ.get(config.ENV_VAR)
    os.environ[config.ENV_VAR] = str(tmp / "config.yaml")
    config._load.cache_clear()
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(config.ENV_VAR, None)
        else:
            os.environ[config.ENV_VAR] = saved
        config._load.cache_clear()


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

    def test_run_is_report_only_and_resolves_inside_its_fixture(self):
        """``run()`` resolves both accessors, so it needs a pinned config.

        Unpinned on a maintainer checkout this read the owner's real baseline and
        profile and printed a drift report about them to stdout — into CI logs and
        any terminal that ran the suite. The resolution is asserted, not assumed:
        an accessor that escaped the fixture fails here rather than silently
        succeeding against real data.
        """
        baseline = textwrap.dedent("""\
            skills:
              - label: "Programming Languages"
                items: "Python, Go, SQL"
            """)
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t).resolve()
            (tmp / "config.yaml").write_text(FIXTURE_CONFIG, encoding="utf-8")
            self._write(tmp, baseline)
            with _pinned_config(tmp):
                self.assertEqual(config.baseline_path(), tmp / "baseline.yaml")
                self.assertEqual(config.profile_md_path(), tmp / "profile.md")
                res = skill_drift.analyze()
                self.assertEqual(Path(res["baseline"]), tmp / "baseline.yaml")
                self.assertEqual(Path(res["profile"]), tmp / "profile.md")
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = skill_drift.run()
        self.assertEqual(rc, 0)                       # report-only
        self.assertIn("clean", out.getvalue())        # read the fixture, not the overlay


if __name__ == "__main__":
    unittest.main()
