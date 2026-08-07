"""Tests for the configured-path doctor.

Two properties matter more than the row formatting. First, the check must FAIL
CLOSED: a report that validated the fictional ``config.example.yaml`` persona,
or one produced with no configuration at all, is worse than no report — it
certifies a tree nobody looked at. Second, the accessor list must be discovered
rather than typed, so a new accessor in ``automation/shared/config.py`` is
checked the day it lands instead of the day someone remembers.

Every case runs against a throwaway config and a throwaway tree — never the real
``config.yaml`` and never the private overlay.

Run with:
    .venv/bin/python -m unittest discover automation/cutover/tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling module importable (automation/cutover/).
_CUTOVER_DIR = Path(__file__).resolve().parents[1]
if str(_CUTOVER_DIR) not in sys.path:
    sys.path.insert(0, str(_CUTOVER_DIR))

import check_configured_paths as checker  # noqa: E402

SCRIPT = _CUTOVER_DIR / "check_configured_paths.py"
REPO_ROOT = checker.REPO_ROOT

CONFIG_TEMPLATE = """\
candidate:
  name: Test Person
  name_slug: Test_Person
  title_slug: Engineer
paths:
  profile_md: {profile}
  baseline_yaml: {baseline}
  reference_docx: {reference}
  applications_root: {applications_root}
  overlay_root: {overlay_root}
  candidate_dir: {candidate_dir}
"""


def clean_env(**overrides: str) -> dict[str, str]:
    """The ambient environment with every JOBHUNT_* knob dropped.

    A real checkout exports ``JOBHUNT_CONFIG`` / ``JOBHUNT_DATA_ROOT``; inheriting
    either would point a test at the owner's data.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("JOBHUNT_")}
    env.update(overrides)
    return env


class DoctorTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.overlay = self.root / "overlay"
        self.applications = self.overlay / "me" / "applications"
        self.candidate = self.applications / "0_profile"
        self.candidate.mkdir(parents=True)
        self.profile = self.candidate / "profile.md"
        self.baseline = self.candidate / "baseline.yaml"
        self.reference = self.candidate / "reference.docx"
        for path in (self.profile, self.baseline, self.reference):
            path.write_text("placeholder\n", encoding="utf-8")
        self.config = self.root / "config.yaml"
        self.write_config()

    def write_config(self, **overrides) -> None:
        values = {
            "profile": self.profile,
            "baseline": self.baseline,
            "reference": self.reference,
            "applications_root": self.applications,
            "overlay_root": self.overlay,
            "candidate_dir": self.candidate,
        }
        values.update(overrides)
        self.config.write_text(CONFIG_TEMPLATE.format(**values), encoding="utf-8")

    def run_cli(self, *, config: Path | None = None,
                extra_env: dict[str, str] | None = None
                ) -> subprocess.CompletedProcess:
        """A real subprocess with an argv LIST — no shell, no pipeline."""
        overrides = dict(extra_env or {})
        if config is not None:
            overrides["JOBHUNT_CONFIG"] = str(config)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=str(self.root), env=clean_env(**overrides),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)


class ResolutionTests(DoctorTestCase):
    def test_a_complete_configuration_is_green(self):
        result = self.run_cli(config=self.config)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ALL GREEN", result.stdout)
        self.assertIn("profile_md_path", result.stdout)

    def test_a_missing_required_file_is_red_and_named(self):
        self.profile.unlink()
        result = self.run_cli(config=self.config)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("MISSING", result.stdout)
        self.assertIn("profile_md_path", result.stdout)
        self.assertIn("RED:", result.stdout)
        self.assertNotIn("ALL GREEN", result.stdout)

    def test_a_directory_accessor_pointing_at_a_file_is_wrong_kind(self):
        wrong = self.root / "applications-but-a-file"
        wrong.write_text("not a directory\n", encoding="utf-8")
        self.write_config(applications_root=wrong)

        result = self.run_cli(config=self.config)

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("WRONG-KIND", result.stdout)
        self.assertIn("applications_root", result.stdout)

    def test_an_absent_optional_destination_skips_and_stays_green(self):
        result = self.run_cli(config=self.config)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skipped (NOT passes", result.stdout)
        self.assertIn("data_root", result.stdout)

    def test_an_optional_destination_that_exists_is_checked_not_ignored(self):
        (self.candidate / "calendar.md").write_text("# calendar\n", encoding="utf-8")
        result = self.run_cli(config=self.config)
        self.assertEqual(result.returncode, 0, result.stdout)
        line = next(row for row in result.stdout.splitlines()
                    if "calendar_path" in row)
        self.assertTrue(line.startswith("OK"), line)

    def test_an_optional_accessor_of_the_wrong_kind_is_still_red(self):
        """SKIP covers "not there yet", never "there, but wrong"."""
        (self.candidate / "calendar.md").mkdir()
        result = self.run_cli(config=self.config)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("WRONG-KIND", result.stdout)
        self.assertIn("calendar_path", result.stdout)


class FailClosedTests(DoctorTestCase):
    def test_the_example_persona_is_refused_not_validated(self):
        example = REPO_ROOT / "config.example.yaml"
        self.assertTrue(example.is_file(), example)

        result = self.run_cli(config=example)

        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("REFUSED", result.stdout)
        self.assertIn("example persona", result.stdout)
        self.assertNotIn("ALL GREEN", result.stdout)

    def test_an_unloadable_configuration_is_refused_not_defaulted(self):
        broken = self.root / "broken.yaml"
        broken.write_text("paths: [this is: not a mapping\n", encoding="utf-8")

        result = self.run_cli(config=broken)

        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("REFUSED", result.stdout)
        self.assertNotIn("ALL GREEN", result.stdout)

    def test_a_config_that_is_not_a_mapping_is_refused(self):
        broken = self.root / "list.yaml"
        broken.write_text("- one\n- two\n", encoding="utf-8")
        result = self.run_cli(config=broken)
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("REFUSED", result.stdout)


class DiscoveryTests(unittest.TestCase):
    """The anti-rot pin: discovery and classification check each other."""

    @classmethod
    def setUpClass(cls):
        cls.config_module = checker.load_config_module()
        cls.discovered = checker.discover_accessors(cls.config_module)

    def test_discovery_finds_the_real_accessors(self):
        for name in ("profile_md_path", "applications_root", "overlay_root",
                     "calendar_path", "data_root"):
            self.assertIn(name, self.discovered)

    def test_an_accessor_taking_a_required_argument_is_not_a_destination(self):
        # skill_references_dir(skill) names a family of folders, not one path.
        self.assertNotIn("skill_references_dir", self.discovered)

    def test_every_discovered_accessor_is_classified(self):
        unclassified = sorted(set(self.discovered) - set(checker.EXPECTED))
        self.assertEqual(
            unclassified, [],
            "config.py grew these accessors; add each to "
            "check_configured_paths.EXPECTED with its kind (file/dir) and whether "
            "it is required.")

    def test_no_expected_row_names_a_vanished_accessor(self):
        stale = sorted(set(checker.EXPECTED) - set(self.discovered))
        self.assertEqual(stale, [],
                         "check_configured_paths.EXPECTED names accessors config.py "
                         "no longer has.")

    def test_every_classification_uses_a_real_kind(self):
        for name, (kind, required, note) in checker.EXPECTED.items():
            with self.subTest(accessor=name):
                self.assertIn(kind, (checker.FILE, checker.DIR))
                self.assertIsInstance(required, bool)
                if not required:
                    self.assertTrue(note, "an optional accessor must say why")


if __name__ == "__main__":
    unittest.main()
