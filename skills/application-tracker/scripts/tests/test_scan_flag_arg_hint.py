"""`status.py`: a scan flag handed a path says what the fix is.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -t skills/application-tracker/scripts/tests

The scan flags (`--check-metadata`, `--backfill-metadata`, `--check-locations`,
`--company-keys`) walk every application under the active config's applications
root and accept no path or slug. Before this hint existed the misuse produced a
bare argparse "unrecognized arguments", which reads like a bad path rather than a
wrong call shape; three measured subject-agent runs each burned a retry on it.

Each case runs status.py as a subprocess because it resolves its applications root
from config at import time. JOBHUNT_CONFIG points at a throwaway config so no case
depends on whether a private overlay is mounted.
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


class ScanFlagArgHintTests(unittest.TestCase):
    @staticmethod
    def _hint_line(stderr: str) -> str:
        """The one `hint:` line, isolated from the usage block above it."""
        for line in stderr.splitlines():
            if "hint:" in line:
                return line
        return ""

    def _run(self, *argv: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "applications" / "6_drafted").mkdir(parents=True)
            config = root / "config.yaml"
            config.write_text(textwrap.dedent(f"""\
                candidate:
                  name: Test Candidate
                paths:
                  applications_root: {root / 'applications'}
                """), encoding="utf-8")
            env = dict(os.environ, JOBHUNT_CONFIG=str(config))
            return subprocess.run(
                [sys.executable, str(STATUS), *argv],
                capture_output=True, text=True, env=env, cwd=tmp,
            )

    def test_check_metadata_with_a_path_names_the_fix(self):
        proc = self._run("--check-metadata", "applications/6_drafted/acme-swe-20260101/")
        self.assertEqual(proc.returncode, 2)
        err = proc.stderr
        # The original rejection is unchanged...
        self.assertIn("unrecognized arguments: applications/6_drafted/acme-swe-20260101/", err)
        # ...and it is now followed by the instruction.
        self.assertIn("hint: --check-metadata scans every application", err)
        self.assertIn("takes no path argument", err)
        self.assertIn("--statuses <folder>", err)
        self.assertIn("--enrich-metadata <slug-or-path>", err)

    def test_backfill_metadata_also_names_the_per_application_flag(self):
        proc = self._run("--backfill-metadata", "acme-swe-20260101")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("hint: --backfill-metadata scans every application", proc.stderr)
        self.assertIn("--enrich-metadata <slug-or-path>", proc.stderr)

    def test_scan_flags_without_a_per_application_counterpart_only_offer_statuses(self):
        for flag in ("--check-locations", "--company-keys"):
            with self.subTest(flag=flag):
                proc = self._run(flag, "acme-swe-20260101")
                self.assertEqual(proc.returncode, 2)
                hint = self._hint_line(proc.stderr)
                self.assertIn(f"{flag} scans every application", hint)
                self.assertIn("--statuses <folder>", hint)
                # No per-application counterpart exists for these two, so the hint
                # must not point at one (the usage block above it names them all).
                self.assertNotIn("--enrich-metadata", hint)

    def test_unknown_argument_without_a_scan_flag_is_unchanged(self):
        proc = self._run("--no-such-flag")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unrecognized arguments: --no-such-flag", proc.stderr)
        self.assertNotIn("hint:", proc.stderr)

    def test_correct_scan_form_still_runs(self):
        proc = self._run("--check-metadata")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("hint:", proc.stderr)
        self.assertIn("No applications found under:", proc.stdout)

    def test_a_flag_that_does_take_a_value_is_untouched(self):
        # --statuses still consumes its value rather than landing in `extras`.
        proc = self._run("--check-metadata", "--statuses", "drafted")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("unrecognized arguments", proc.stderr)
        self.assertNotIn("hint:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
