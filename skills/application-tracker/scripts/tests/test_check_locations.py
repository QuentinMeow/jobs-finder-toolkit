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


class MultiPostingRollupTests(unittest.TestCase):
    """One folder, several postings: the WORST posting's verdict is the folder's.

    The rollup used to be best-match-wins, so a folder holding one Springfield
    posting and one London posting reported `ok / metro` and the command exited
    0 — while `handoff.check_location_policy`, the gate that CREATED the folder,
    already scored the same shape per posting, worst-wins. AGENTS.md's policy
    governs a POSTING; a folder is just the container one resume covers.
    """

    def _run(self, folders: dict[str, list[dict]]):
        """Run --check-locations over multi-posting folders; return (rc, json).

        Each posting dict is ``{role, location?, jd?}``. ``jd`` writes a JD file
        and points the posting's ``jd_file`` at it; a posting with no ``location``
        must still be assessed from that file.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafted = root / "apps" / "6_drafted"
            for slug, postings in folders.items():
                app = drafted / slug
                source = app / "source"
                source.mkdir(parents=True)
                jobs = []
                for posting in postings:
                    job = {"role": posting["role"],
                           "status": "drafted",
                           "location": posting.get("location", "")}
                    if "jd" in posting:
                        name = "JD-" + posting["role"].lower().replace(" ", "-") + ".md"
                        (source / name).write_text(posting["jd"], encoding="utf-8")
                        job["jd_file"] = name
                    jobs.append(job)
                (app / "meta.yaml").write_text(
                    json.dumps({"company": "ExampleCorp", "jobs": jobs}),
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

    def test_one_foreign_posting_fails_the_whole_folder(self):
        rc, data = self._run({"mixed-app": [
            {"role": "Platform Engineer", "location": "Springfield, ST"},
            {"role": "Infrastructure Engineer", "location": "London, United Kingdom"},
        ]})
        self.assertEqual(rc, 1, "a foreign sibling must not be masked by a match")
        self.assertEqual(len(data["mismatches"]), 1)
        self.assertEqual(
            [p["role"] for p in data["mismatches"][0]["offending"]],
            ["Infrastructure Engineer"],
            "the offending posting must be named, not collapsed into the folder",
        )

    def test_a_blank_location_posting_is_read_from_its_own_jd(self):
        # The sibling recorded a location, so the pooled-location fallback never
        # looked at any JD file and this posting was invisible to both the
        # verdict and the LOCATIONS column.
        rc, data = self._run({"blank-location-app": [
            {"role": "Data Engineer", "location": "Springfield, ST"},
            {"role": "ML Engineer", "jd": "Location: Berlin, Germany\n"},
        ]})
        self.assertEqual(rc, 1)
        self.assertEqual(
            [p["role"] for p in data["mismatches"][0]["offending"]],
            ["ML Engineer"])
        self.assertIn("Berlin, Germany", data["rows"][0]["locations"])

    def test_every_posting_in_policy_still_passes(self):
        rc, data = self._run({"all-good-app": [
            {"role": "Platform Engineer", "location": "Springfield, ST"},
            {"role": "Data Engineer", "location": "Remote (US)"},
            {"role": "ML Engineer", "jd": "Location: Fairview, ST\n"},
        ]})
        self.assertEqual(rc, 0, "worst-wins must not fail a folder that is fine")
        self.assertEqual(data["mismatches"], [])
        self.assertTrue(data["rows"][0]["match"])

    def test_an_unlocatable_posting_is_review_and_does_not_block(self):
        # `review` outranks `no_match` in the rollup but still never fails the
        # command: a genuinely unknown location blocking legitimate work is the
        # expensive direction.
        rc, data = self._run({"partly-unknown-app": [
            {"role": "Platform Engineer", "location": "Springfield, ST"},
            {"role": "Mystery Engineer"},
        ]})
        self.assertEqual(rc, 0)
        self.assertEqual(data["mismatches"], [])
        self.assertEqual(len(data["review"]), 1)
        self.assertEqual(
            [p["role"] for p in data["review"][0]["unclassified"]],
            ["Mystery Engineer"])

    def test_a_definite_mismatch_outranks_an_unknown_sibling(self):
        rc, data = self._run({"worst-wins-app": [
            {"role": "Mystery Engineer"},
            {"role": "Infrastructure Engineer", "location": "Toronto, Canada"},
        ]})
        self.assertEqual(rc, 1)
        self.assertEqual(len(data["mismatches"]), 1)
        self.assertEqual(data["mismatches"][0]["decision"], "no_match")


if __name__ == "__main__":
    unittest.main()
