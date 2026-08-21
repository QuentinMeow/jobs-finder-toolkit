"""Tests for build_tailoring_card.py — deterministic, no network, no real config.yaml.

Each test builds a temp overlay: copies of the public Jordan Rivers career fixture
(``examples/me/career/``) plus a throwaway ``config.yaml`` whose
``applications_root`` is the temp dir. The script is driven by subprocess with
``JOBHUNT_CONFIG`` pointing at that temp config, so config discovery never reaches a
real overlay and every run is deterministic on the fixture (timestamp aside).

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
SCRIPTS = _HERE.parents[1]
BUILD_SCRIPT = SCRIPTS / "build_tailoring_card.py"
for _p in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_tailoring_card  # noqa: E402  (import after the sys.path bootstrap)
PROFILE_FIXTURE = REPO_ROOT / "examples" / "me" / "career" / "profile.example.md"
BASELINE_FIXTURE = (REPO_ROOT / "examples" / "me" / "career" / "resume"
                    / "baseline.example.yaml")

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
            sb = tmp / "me" / "interviews" / "story-bank"
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

    def test_card_key_numbers_keep_their_units(self):
        # #260 end to end: the corrupted units must not reach a rendered card.
        tmp, cfg = self._setup()
        baseline = yaml.safe_load((tmp / "baseline.yaml").read_text())
        baseline["summary_bullets"] = [
            "Operated 18 Kubernetes clusters at 99.95% availability",
            "Cut incident recovery from 54 minutes to 31 minutes",
            "Supported 120 services and 14 APIs, trimming pages from "
            "1,200 to 430 pages a quarter",
        ]
        (tmp / "baseline.yaml").write_text(
            yaml.safe_dump(baseline, sort_keys=False, allow_unicode=True),
            encoding="utf-8")
        self.assertEqual(self._run(cfg)[0], 0)
        lines = self._card(tmp).read_text(encoding="utf-8").splitlines()
        head = lines.index("## Key numbers")
        key_line = next(l for l in lines[head + 1:] if l.strip())
        self.assertIn("18 Kubernetes clusters", key_line)
        self.assertIn("54 minutes", key_line)
        self.assertIn("1,200 to 430 pages", key_line)
        for fragment in ("18 K,", "54 m,", "18 K ", " 54 m,"):
            self.assertNotIn(fragment, key_line)

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
        self.assertIn("me/interviews/story-bank/payments-migration.md", text)

    def test_story_bank_resolved_from_explicit_overlay_root_not_config_dir(self):
        # Real-deployment shape: config.yaml at the repo root, with applications
        # nested at private/me/applications and the overlay root pinned to private/.
        # Resolving from the config directory would find no story bank and stamp the
        # card "(0 stories)", hiding a real story bank.
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        overlay = tmp / "private"
        apps = overlay / "me" / "applications"
        (apps / "0_profile").mkdir(parents=True)
        career = overlay / "me" / "career"
        (career / "resume").mkdir(parents=True)
        shutil.copy(PROFILE_FIXTURE, career / "profile.md")
        shutil.copy(BASELINE_FIXTURE, career / "resume" / "baseline.yaml")
        sb = overlay / "me" / "interviews" / "story-bank"
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
            '  profile_md: "private/me/career/profile.md"\n'
            '  baseline_yaml: "private/me/career/resume/baseline.yaml"\n'
            '  applications_root: "private/me/applications"\n'
            '  overlay_root: "private"\n',
            encoding="utf-8")
        rc, out, err = self._run(cfg)
        self.assertEqual(rc, 0, err)
        card = apps / "0_profile" / "tailoring-card.md"
        text = card.read_text(encoding="utf-8")
        self.assertNotIn("No story bank found", text)
        self.assertIn("Payments platform microservices migration", text)
        self.assertIn("(1 story)", text)
        # Digest pointer stays config-relative (absolute-free), reaching into the overlay.
        self.assertIn(
            "private/me/interviews/story-bank/payments-migration.md", text)

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


class KeyNumberUnitTests(unittest.TestCase):
    """Issue #260 — a metric must never lose (or invent) its unit.

    The old magnitude pattern was compiled case-insensitively, so the ``K``/``M``
    of the FOLLOWING WORD was read as a magnitude suffix: ``18 Kubernetes
    clusters`` became ``18 K`` and ``54 minutes`` became ``54 m``. The card is the
    default context for every resume draft and ``check.py`` cannot catch it (the
    digits are real), so a wrong unit ships as a silent 1000x overclaim.
    """

    # A single trailing letter after the digits is the corruption signature
    # ("18 K", "54 m") — no correct metric ever looks like that.
    FRAGMENT_RE = re.compile(r"^\$?\d[\d,]*(?:\.\d+)?\s?[A-Za-z]$")

    def nums(self, text: str) -> list[str]:
        return build_tailoring_card._key_numbers(text)

    def assertNoBareUnitFragment(self, values: list[str]):
        for value in values:
            self.assertNotRegex(
                value, self.FRAGMENT_RE,
                f"{value!r} is a number glued to a bare unit letter (#260)")

    # ── bare units that are really the next word ─────────────
    def test_word_initial_is_never_read_as_a_magnitude(self):
        got = self.nums("Operated 18 Kubernetes clusters across three regions.")
        self.assertEqual(got, ["18 Kubernetes clusters"])
        self.assertNoBareUnitFragment(got)

    def test_minutes_are_not_read_as_millions(self):
        got = self.nums("Cut incident recovery from 54 minutes to 31 minutes.")
        self.assertEqual(got, ["54 minutes", "31 minutes"])
        self.assertNoBareUnitFragment(got)

    def test_qa_word_initials_keep_their_nouns(self):
        got = self.nums("Wrote 24 manual test cases, filed 18 defect reports, "
                        "and automated 12 local smoke tests.")
        self.assertEqual(got, ["24 manual test cases", "18 defect reports",
                               "12 local smoke tests"])
        self.assertNoBareUnitFragment(got)

    def test_lowercase_unit_is_not_a_magnitude(self):
        got = self.nums("Held p99 latency under 250 ms during peak and rode "
                        "an 18 km commute.")
        self.assertNoBareUnitFragment(got)
        self.assertIn("250 ms", got)
        self.assertNotIn("18 k", [v.lower() for v in got])
        self.assertTrue(any(v.startswith("18 km") for v in got), got)

    # ── real magnitudes must survive ─────────────────────────
    def test_attached_magnitudes_are_kept(self):
        self.assertEqual(self.nums("Owned a $1.2M cloud budget."),
                         ["$1.2M cloud budget"])
        self.assertEqual(self.nums("Raised $1.2M in seed funding."), ["$1.2M"])
        self.assertEqual(self.nums("Grew to 3.5K users."), ["3.5K users"])
        self.assertEqual(self.nums("Processed 50M+ daily events reliably."),
                         ["50M+ daily events"])
        self.assertEqual(self.nums("Negotiated an $18K annual discount."),
                         ["$18K annual discount"])

    def test_spaced_magnitude_needs_a_unit_noun(self):
        # "50 M requests" is a real magnitude; "Tier 3 B, C" is not.
        self.assertEqual(self.nums("Served 50 M requests a day."), ["50 M requests"])
        self.assertNoBareUnitFragment(self.nums("Audited tier 3 B, C, and D controls."))

    def test_trailing_adverb_dropped_but_frequency_kept(self):
        self.assertEqual(self.nums("Processed 50M+ daily events reliably."),
                         ["50M+ daily events"])
        self.assertEqual(self.nums("Filed 12 monthly reports."), ["12 monthly reports"])
        # Trimming must never leave a bare, unit-less number behind.
        self.assertEqual(self.nums("Shipped 12 quarterly."), ["12 quarterly"])

    # ── percentages / percentiles / durations ────────────────
    def test_percentages_are_intact(self):
        got = self.nums("Reduced failed payments by 40% while holding 99.95% "
                        "availability at the 99th percentile.")
        self.assertIn("40%", got)
        self.assertIn("99.95%", got)
        self.assertIn("99th percentile", got)
        self.assertNoBareUnitFragment(got)

    def test_years_and_under_seconds_keep_their_unit(self):
        got = self.nums("Senior engineer with 8+ years shipping services "
                        "under two seconds end to end.")
        self.assertIn("8+ years", got)
        self.assertIn("under two seconds", got)

    # ── ranges ───────────────────────────────────────────────
    def test_range_keeps_both_endpoints_and_the_unit(self):
        got = self.nums("Cut the on-call load from 1,200 to 430 pages a quarter.")
        self.assertIn("1,200 to 430 pages", got)
        # The endpoint alone must not also be queued as a separate metric.
        self.assertNotIn("430 pages", got)

    def test_dash_range_and_year_range_guard(self):
        self.assertIn("120 – 45 seconds",
                      self.nums("Trimmed the job from 120 – 45 seconds."))
        # A bare year range is a date, not a metric.
        self.assertEqual(self.nums("Owned the platform from 2019 to 2022."), [])

    # ── omitted-metric regression + ranking ──────────────────
    def test_plain_counts_are_no_longer_dropped(self):
        got = self.nums("Supported 120 services and 14 APIs for the platform.")
        self.assertEqual(got, ["120 services", "14 APIs"])

    def test_headline_metrics_rank_above_plain_counts(self):
        got = self.nums("Supported 120 services and 14 APIs, cutting error "
                        "rates by 40%.")
        self.assertEqual(got[0], "40%")

    def test_selection_is_deterministic_across_repeat_builds(self):
        text = ("Operated 18 Kubernetes clusters at 99.95% availability, cut "
                "MTTR from 54 minutes to 31 minutes, and reduced pages from "
                "1,200 to 430 pages across 120 services and 14 APIs.")
        first = self.nums(text)
        self.assertEqual(first, self.nums(text))
        self.assertNoBareUnitFragment(first)
        self.assertIn("18 Kubernetes clusters", first)
        self.assertIn("1,200 to 430 pages", first)

    def test_a_tail_never_crosses_a_line_break(self):
        got = self.nums("Reviewed 12\nKubernetes hardened every service.")
        self.assertNotIn("12 Kubernetes hardened every", got)

    def test_example_fixture_card_has_no_bare_unit_fragments(self):
        baseline = yaml.safe_load(BASELINE_FIXTURE.read_text(encoding="utf-8"))
        profile = PROFILE_FIXTURE.read_text(encoding="utf-8")
        got = build_tailoring_card._key_numbers(
            build_tailoring_card._numbers_text(baseline, profile))
        self.assertNoBareUnitFragment(got)
        self.assertIn("40%", got)
        self.assertIn("under two seconds", got)


if __name__ == "__main__":
    unittest.main()
