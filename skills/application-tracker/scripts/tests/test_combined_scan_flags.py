"""`status.py`: `--check-metadata` and `--check-locations` both run when both are given.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -t skills/application-tracker/scripts/tests

Each scan flag used to own an `if` block ending in an unconditional `sys.exit`,
so the FIRST flag given always terminated the process. `--check-metadata
--check-locations` therefore never reached the location check: a run whose
metadata was clean exited 0 and printed nothing about locations, while
out-of-policy postings sat unexamined. `AGENTS.md` names `--check-locations` as
the way to verify the location guardrail, so a silent skip is a guardrail that
reports success without doing anything.

The decisive case is `test_valid_metadata_with_a_bad_location_fails`: metadata
passes, the location does not, and only a location check that actually ran can
turn that into a non-zero exit.

status.py resolves its applications root and location policy from config at
import time, so every case runs it as a subprocess with JOBHUNT_CONFIG pointed
at a throwaway config + applications tree — no case depends on whether a private
overlay is mounted.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

STATUS = Path(__file__).resolve().parents[1] / "status.py"

# A schema-valid meta.yaml (job_metadata_schema_version 6). `location` is the one
# field a case varies, so a metadata-clean application can still be out of policy.
_META = """\
job_metadata_schema_version: 6
company: "Example Corp"
company_key: example-corp
research_date: "2025-01-15"
channel: ""
referrer: ""
next_action: ""
notes: ""
jobs:
  - role: "Platform Engineer"
    jd_file: "JD-platform-engineer.md"
    status: "drafted"
    location: "{location}"
    workplace: "{workplace}"
    url: ""
    posted_date: ""
    sponsorship: "unknown"
    fit: "strong"
    job_level:
      normalized: senior
      min: 4.8
      max: 5.5
      confidence: medium
      source: company_reference
    required_yoe:
      min: 5
      max: 9
      confidence: high
      source: company_reference
    salary_range:
      min: 150000
      max: 195000
      confidence: high
      source: company_reference
    progress:
      phase: application_prep
      state: action_required
"""


class CombinedScanFlagTests(unittest.TestCase):
    def _run(self, argv, apps, *, valid_metadata=True):
        """Run status.py over a temp drafted/ tree; return the CompletedProcess.

        ``apps`` maps slug -> (location, workplace). With
        ``valid_metadata=False`` the meta.yaml omits the schema version so
        --check-metadata fails.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafted = root / "apps" / "6_drafted"
            for slug, (location, workplace) in apps.items():
                app = drafted / slug
                app.mkdir(parents=True)
                source = app / "source"
                source.mkdir()
                (source / "JD-platform-engineer.md").write_text(
                    "We are hiring a platform engineer.", encoding="utf-8")
                if valid_metadata:
                    text = _META.format(location=location, workplace=workplace)
                else:
                    text = f'company: "Example Corp"\nlocation: "{location}"\n'
                (app / "meta.yaml").write_text(text, encoding="utf-8")
            (root / "config.yaml").write_text(textwrap.dedent(f"""\
                paths:
                  applications_root: "{(root / 'apps').as_posix()}"
                location_policy:
                  metro: [springfield, fairview]
                  allow_us_remote: true
                  us_only: true
                """), encoding="utf-8")
            env = dict(os.environ, JOBHUNT_CONFIG=str(root / "config.yaml"))
            return subprocess.run(
                [sys.executable, str(STATUS), *argv],
                capture_output=True, text=True, env=env)

    IN_POLICY = {"good-app": ("Remote (US)", "remote")}
    OUT_OF_POLICY = {"bad-app": ("London, United Kingdom", "onsite")}

    def test_valid_metadata_with_a_bad_location_fails(self):
        """The regression: a clean metadata check must not mask a bad location.

        Before the fix this exited 0 — --check-metadata passed and exited before
        the location check could run.
        """
        proc = self._run(["--check-metadata", "--check-locations"],
                         self.OUT_OF_POLICY)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("London, United Kingdom", proc.stdout)

    def test_both_reports_are_printed(self):
        """Each check keeps its own output; neither is swallowed by the other."""
        proc = self._run(["--check-metadata", "--check-locations"],
                         self.IN_POLICY)
        # The metadata report...
        self.assertIn("Checked 1 applications", proc.stdout)
        # ...and the location table, in that order.
        self.assertIn("CATEGORY", proc.stdout)
        self.assertLess(proc.stdout.index("Checked 1 applications"),
                        proc.stdout.index("CATEGORY"))

    def test_both_clean_exits_zero(self):
        proc = self._run(["--check-metadata", "--check-locations"],
                         self.IN_POLICY)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_bad_metadata_still_fails_and_the_location_check_still_runs(self):
        """A failing FIRST check must not stop the second one from running.

        The exit code is non-zero if EITHER check fails, and the accumulator is
        the right operand of `and` precisely so that neither call is
        short-circuited away.
        """
        proc = self._run(["--check-metadata", "--check-locations"],
                         self.IN_POLICY, valid_metadata=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("INVALID", proc.stdout)
        self.assertIn("CATEGORY", proc.stdout)

    def test_each_flag_alone_is_unchanged(self):
        for argv, apps, expected in (
            (["--check-metadata"], self.IN_POLICY, 0),
            (["--check-locations"], self.IN_POLICY, 0),
            (["--check-locations"], self.OUT_OF_POLICY, 1),
        ):
            with self.subTest(argv=argv, expected=expected):
                proc = self._run(argv, apps)
                self.assertEqual(proc.returncode, expected,
                                 proc.stdout + proc.stderr)

    def test_check_metadata_alone_does_not_print_a_location_table(self):
        proc = self._run(["--check-metadata"], self.OUT_OF_POLICY)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("CATEGORY", proc.stdout)


if __name__ == "__main__":
    unittest.main()
