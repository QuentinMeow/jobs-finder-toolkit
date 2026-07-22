"""Exit-code tests for `status.py --check-locations`.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -t skills/application-tracker/scripts/tests

status.py reads its applications root + location policy from config at import
time, so each case runs it as a subprocess with JOBHUNT_CONFIG pointed at a
throwaway config + applications tree (no private overlay, generic fixtures).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

STATUS = Path(__file__).resolve().parents[1] / "status.py"


class CheckLocationsExitCodeTests(unittest.TestCase):
    def _run(self, apps: dict[str, object]):
        """Run --check-locations over a temp drafted/ tree; return (rc, parsed_json)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafted = root / "apps" / "6_drafted"
            for slug, spec in apps.items():
                app = drafted / slug
                app.mkdir(parents=True)
                if isinstance(spec, dict):
                    source = app / "source"
                    source.mkdir()
                    jd_file = "JD-platform-engineer.md"
                    (source / jd_file).write_text(
                        str(spec.get("description") or ""), encoding="utf-8")
                    meta = {
                        "company": "ExampleCorp",
                        "jobs": [{
                            "role": "Platform Engineer",
                            "jd_file": jd_file,
                            "location": spec.get("location", ""),
                            "workplace": spec.get("workplace", "unknown"),
                        }],
                    }
                    (app / "meta.yaml").write_text(
                        json.dumps(meta), encoding="utf-8")
                else:
                    (app / "meta.yaml").write_text(
                        f'company: ExampleCorp\nlocation: "{spec}"\n',
                        encoding="utf-8")
            (root / "config.yaml").write_text(textwrap.dedent(f"""\
                paths:
                  applications_root: "{(root / 'apps').as_posix()}"
                location_policy:
                  metro: [springfield, fairview]
                  allow_us_remote: true
                  us_only: true
                """), encoding="utf-8")
            env = dict(os.environ, JOBHUNT_CONFIG=str(root / "config.yaml"))
            proc = subprocess.run(
                [sys.executable, str(STATUS), "--check-locations", "--json"],
                capture_output=True, text=True, env=env)
            return proc.returncode, json.loads(proc.stdout)

    def test_all_matching_exits_zero(self):
        rc, data = self._run({"match-app": "Remote (US)"})
        self.assertEqual(rc, 0)
        self.assertEqual(data["mismatches"], [])

    def test_unknown_location_is_review_not_failure(self):
        # A blank/unrecognized location is surfaced for review but must NOT fail.
        rc, data = self._run({"match-app": "Remote (US)", "unknown-app": ""})
        self.assertEqual(rc, 0, "unknown/blank location must not fail the check")
        self.assertEqual(data["mismatches"], [])
        self.assertEqual(len(data["review"]), 1)

    def test_real_mismatch_exits_nonzero(self):
        rc, data = self._run({
            "match-app": "Remote (US)",
            "foreign-app": "London, United Kingdom",
        })
        self.assertEqual(rc, 1, "a definite foreign location must fail the check")
        self.assertEqual(len(data["mismatches"]), 1)

    def test_mismatch_and_unknown_still_fails_on_mismatch_only(self):
        rc, data = self._run({
            "match-app": "Remote (US)",
            "foreign-app": "Toronto, Canada",
            "unknown-app": "",
        })
        self.assertEqual(rc, 1)
        self.assertEqual(len(data["mismatches"]), 1)
        self.assertEqual(len(data["review"]), 1)

    def test_office_list_with_jd_remote_alternative_matches(self):
        rc, data = self._run({
            "office-or-remote": {
                "location": "San Francisco, CA • New York, NY • United States",
                "workplace": "remote",
                "description": (
                    "This role can be held from one of our US hubs or remotely "
                    "in the United States."
                ),
            },
        })
        self.assertEqual(rc, 0)
        self.assertEqual(data["rows"][0]["category"], "us_remote")
        self.assertEqual(data["rows"][0]["workplace"], "remote")


if __name__ == "__main__":
    unittest.main()
