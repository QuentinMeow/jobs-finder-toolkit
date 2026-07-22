"""Tests for build_tailoring_card.py — deterministic, no network, no real config.yaml.

Each test builds a temp overlay: copies of the public Jordan Rivers fixture
(``examples/profile/``) plus a throwaway ``config.yaml`` whose ``applications_root``
is the temp dir. The script is driven by subprocess with ``JOBHUNT_CONFIG`` pointing at
that temp config, so config discovery never reaches a real overlay and every run is
deterministic on the fixture (timestamp aside).

Run with:
    .venv/bin/python -m unittest discover -s skills/resume-writer/scripts/tests
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

# tests/ -> scripts/ -> resume-writer/ -> skills/ -> .agents/ -> repo root
_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[4]
BUILD_SCRIPT = _HERE.parents[1] / "build_tailoring_card.py"
PROFILE_FIXTURE = REPO_ROOT / "examples" / "profile" / "profile.example.md"
BASELINE_FIXTURE = REPO_ROOT / "examples" / "profile" / "baseline.example.yaml"

CEILING_BYTES = 8192

CONFIG_YAML = (
    'candidate:\n'
    '  name: "Jordan Rivers"\n'
    '  contact_line: "City, ST • jordan.rivers@example.com • linkedin.com/in/jordanrivers"\n'
    '  name_slug: "Jordan_Rivers"\n'
    '  title_slug: "Software_Engineer"\n'
    'paths:\n'
    '  profile_md: "profile.md"\n'
    '  baseline_yaml: "baseline.yaml"\n'
    '  applications_root: "applications"\n'
)


def _profile_never_bullets() -> list[str]:
    """Raw ``- ...`` bullet lines of the profile's Skills > Never subsection."""
    out: list[str] = []
    in_skills = in_never = False
    for line in PROFILE_FIXTURE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_skills = line.strip().lower().startswith("## skills")
            in_never = False
            continue
        if in_skills and line.startswith("### "):
            in_never = line[4:].strip().lower().startswith("never")
            continue
        if in_never and line.lstrip().startswith("- "):
            out.append(line.rstrip())
    return out


def _strip_timestamp(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith("_Generated "))


class TailoringCardTests(unittest.TestCase):
    def _setup(self, with_story: bool = False) -> tuple[Path, Path]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copy(PROFILE_FIXTURE, tmp / "profile.md")
        shutil.copy(BASELINE_FIXTURE, tmp / "baseline.yaml")
        if with_story:
            sb = tmp / "interviews" / "behavioral-story-bank"
            sb.mkdir(parents=True)
            (sb / "payments-migration.md").write_text(
                "# Payments platform microservices migration\n\n"
                "Split a monolithic payments service into independently deployable "
                "services, reducing failed-payment incidents by 40%.\n",
                encoding="utf-8")
        cfg = tmp / "config.yaml"
        cfg.write_text(CONFIG_YAML, encoding="utf-8")
        return tmp, cfg

    def _run(self, cfg: Path, *args: str):
        env = dict(os.environ)
        env["JOBHUNT_CONFIG"] = str(cfg)
        proc = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), *args],
            capture_output=True, text=True, env=env, cwd=str(cfg.parent))
        return proc.returncode, proc.stdout, proc.stderr

    @staticmethod
    def _card(tmp: Path) -> Path:
        return tmp / "applications" / "0_profile" / "tailoring-card.md"

    # ── generation ───────────────────────────────────────────
    def test_build_succeeds_and_reports_stdout(self):
        tmp, cfg = self._setup()
        rc, out, err = self._run(cfg)
        self.assertEqual(rc, 0, err)
        self.assertTrue(self._card(tmp).is_file())
        # stdout: card path + byte count + est tokens.
        self.assertIn("tailoring-card.md", out)
        self.assertRegex(out, r"\d+ bytes\s+~\d+ tokens")

    def test_deterministic_generation(self):
        # Two independent builds from identical fixtures differ only by timestamp.
        tmp1, cfg1 = self._setup()
        tmp2, cfg2 = self._setup()
        self.assertEqual(self._run(cfg1)[0], 0)
        self.assertEqual(self._run(cfg2)[0], 0)
        a = _strip_timestamp(self._card(tmp1).read_text(encoding="utf-8"))
        b = _strip_timestamp(self._card(tmp2).read_text(encoding="utf-8"))
        self.assertEqual(a, b)

    def test_header_has_hashes_timestamp_and_no_absolute_paths(self):
        tmp, cfg = self._setup()
        self.assertEqual(self._run(cfg)[0], 0)
        text = self._card(tmp).read_text(encoding="utf-8")
        # A UTC-ISO generation timestamp.
        self.assertRegex(text, r"_Generated \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z \(UTC\)")
        # Each source carries a 64-hex SHA-256; config-relative, absolute-free paths.
        self.assertRegex(text, r"- `profile\.md` sha256:[0-9a-f]{64}")
        self.assertRegex(text, r"- `baseline\.yaml` sha256:[0-9a-f]{64}")
        self.assertNotIn("/Users/", text)
        self.assertNotIn(str(tmp), text)

    def test_identity_and_key_numbers_present(self):
        tmp, cfg = self._setup()
        self.assertEqual(self._run(cfg)[0], 0)
        text = self._card(tmp).read_text(encoding="utf-8")
        self.assertIn("Jordan Rivers", text)
        self.assertIn("Northwind Systems", text)          # locked employer
        self.assertIn("Software Engineer", text)          # target title
        self.assertIn("Payments platform microservices migration", text)  # locked title
        self.assertIn("40%", text)                        # a key number

    def test_multi_employer_baseline_lists_every_locked_job_and_metric(self):
        tmp, cfg = self._setup()
        baseline = yaml.safe_load((tmp / "baseline.yaml").read_text())
        first = baseline.pop("employer")
        second = {
            "company": "Fictional Labs",
            "role": "Software Engineer",
            "dates": "2014 – 2016",
            "location": "City, ST",
            "bullets": [
                "Improved a synthetic batch workflow by 25% for a public test fixture."
            ],
            "projects": [],
        }
        baseline["employers"] = [first, second]
        (tmp / "baseline.yaml").write_text(
            yaml.safe_dump(baseline, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self.assertEqual(self._run(cfg)[0], 0)
        text = self._card(tmp).read_text(encoding="utf-8")
        self.assertIn("Northwind Systems", text)
        self.assertIn("Fictional Labs", text)
        self.assertIn("25%", text)

    # ── size ceiling ─────────────────────────────────────────
    def test_size_ceiling(self):
        tmp, cfg = self._setup(with_story=True)
        rc, out, _ = self._run(cfg)
        self.assertEqual(rc, 0)
        size = len(self._card(tmp).read_bytes())
        self.assertLessEqual(size, CEILING_BYTES,
                             f"card {size} bytes exceeds the {CEILING_BYTES} ceiling")
        self.assertNotIn("WARN", out)

    # ── Never blocklist is verbatim + complete ───────────────
    def test_never_list_verbatim_and_complete(self):
        tmp, cfg = self._setup()
        self.assertEqual(self._run(cfg)[0], 0)
        text = self._card(tmp).read_text(encoding="utf-8")
        never = _profile_never_bullets()
        self.assertTrue(never, "fixture must define a Never list")
        for line in never:
            # The whole bullet line appears verbatim (a blocklist is never summarized).
            self.assertIn(line, text, f"Never line missing verbatim: {line!r}")
            # And every individual skill within it appears exactly.
            payload = line.split(":", 1)[1] if ":" in line else line[2:]
            for skill in (s.strip() for s in payload.split(",")):
                self.assertIn(skill, text, f"Never entry missing: {skill!r}")

    # ── story-bank digest ────────────────────────────────────
    def test_story_bank_absent_is_graceful(self):
        tmp, cfg = self._setup(with_story=False)
        self.assertEqual(self._run(cfg)[0], 0)
        text = self._card(tmp).read_text(encoding="utf-8")
        self.assertIn("No story bank found", text)

    def test_story_bank_present_is_digested(self):
        tmp, cfg = self._setup(with_story=True)
        self.assertEqual(self._run(cfg)[0], 0)
        text = self._card(tmp).read_text(encoding="utf-8")
        self.assertIn("Payments platform microservices migration", text)
        self.assertIn("Read the full story", text)
        self.assertIn("interviews/behavioral-story-bank/payments-migration.md", text)

    def test_story_bank_resolved_from_overlay_root_not_config_dir(self):
        # Real-deployment shape: config.yaml at the repo root, the private overlay
        # (applications tree + story bank) mounted under private/. The story bank must
        # be resolved via applications_root().parent, NOT the config file's directory —
        # otherwise the builder looks under the repo root, finds nothing, and stamps the
        # card "(0 stories)", hiding a real story bank. Before the fix this test fails.
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        overlay = tmp / "private"
        (overlay / "applications" / "0_profile").mkdir(parents=True)
        shutil.copy(PROFILE_FIXTURE, overlay / "profile.md")
        shutil.copy(BASELINE_FIXTURE, overlay / "baseline.yaml")
        sb = overlay / "interviews" / "behavioral-story-bank"
        sb.mkdir(parents=True)
        (sb / "payments-migration.md").write_text(
            "# Payments platform microservices migration\n\n"
            "Split a monolithic payments service into independently deployable "
            "services, reducing failed-payment incidents by 40%.\n",
            encoding="utf-8")
        cfg = tmp / "config.yaml"          # config at the repo root, NOT in the overlay
        cfg.write_text(
            'candidate:\n'
            '  name: "Jordan Rivers"\n'
            '  name_slug: "Jordan_Rivers"\n'
            '  title_slug: "Software_Engineer"\n'
            'paths:\n'
            '  profile_md: "private/profile.md"\n'
            '  baseline_yaml: "private/baseline.yaml"\n'
            '  applications_root: "private/applications"\n',
            encoding="utf-8")
        rc, out, err = self._run(cfg)
        self.assertEqual(rc, 0, err)
        card = overlay / "applications" / "0_profile" / "tailoring-card.md"
        text = card.read_text(encoding="utf-8")
        self.assertNotIn("No story bank found", text)
        self.assertIn("Payments platform microservices migration", text)
        self.assertIn("(1 story)", text)
        # Digest pointer stays config-relative (absolute-free), reaching into the overlay.
        self.assertIn(
            "private/interviews/behavioral-story-bank/payments-migration.md", text)

    # ── staleness / no-op protection ─────────────────────────
    def test_check_reports_current_then_stale_after_mutation(self):
        tmp, cfg = self._setup()
        self.assertEqual(self._run(cfg)[0], 0)
        rc, out, _ = self._run(cfg, "--check")
        self.assertEqual(rc, 0, out)
        self.assertIn("current", out)
        # Mutate a temp copy of a source; --check must flag exactly that source.
        with (tmp / "baseline.yaml").open("a", encoding="utf-8") as fh:
            fh.write("\n# touched\n")
        rc, out, _ = self._run(cfg, "--check")
        self.assertNotEqual(rc, 0)
        self.assertIn("baseline.yaml", out)

    def test_check_on_missing_card_is_nonzero(self):
        _, cfg = self._setup()
        rc, out, _ = self._run(cfg, "--check")
        self.assertNotEqual(rc, 0)
        self.assertIn("no card", out)

    def test_no_op_protection_and_force(self):
        tmp, cfg = self._setup()
        self.assertEqual(self._run(cfg)[0], 0)
        # Unchanged sources: default build refuses (no-op protection).
        rc, out, err = self._run(cfg)
        self.assertNotEqual(rc, 0)
        self.assertIn("already current", err)
        # --force overrides the no-op protection.
        self.assertEqual(self._run(cfg, "--force")[0], 0)

    def test_build_rebuilds_when_sources_change(self):
        tmp, cfg = self._setup()
        self.assertEqual(self._run(cfg)[0], 0)
        (tmp / "profile.md").write_text(
            PROFILE_FIXTURE.read_text(encoding="utf-8") + "\n<!-- edit -->\n",
            encoding="utf-8")
        # Changed sources: default build rebuilds without --force.
        rc, out, _ = self._run(cfg)
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
