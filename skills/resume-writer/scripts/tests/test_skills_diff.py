"""Tests for skills_diff.py — the Step-7 uncategorized-skill queue.

Constructed JD + profile fixtures. Queue membership must match the render gate
exactly (it reuses check.py's helpers), including the component-wise Weak match.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import skills_diff  # noqa: E402


PROFILE = """# Profile

## Skills

### Approved (include in most resumes, if not all)

- Programming Languages: Python, Java, Go, C++
- Skills: Docker, Kubernetes, PostgreSQL, REST APIs

### Weak (user-facing: Weak or Selective — include ONLY when the JD mentions it)

- Cloud: AWS (Lambda, SQS, SNS), service mesh
- APIs: REST/gRPC APIs

### Never (never include in any resume)

- Languages: Rust, Scala, C language, R language
- Extractor artifacts: LinkedIn non-skill

## Experience

Nothing else here.
"""


def _queue(jd_text: str) -> list[str]:
    return skills_diff.uncategorized_queue(jd_text, PROFILE)


class SkillsDiffTests(unittest.TestCase):
    def test_approved_only_jd_yields_empty_queue(self):
        jd = "We use Python, Docker, and Kubernetes with PostgreSQL in production."
        self.assertEqual(_queue(jd), [])

    def test_uncategorized_hits_preserve_verbatim_phrasing(self):
        jd = "Experience with OpenTelemetry and ClickHouse is required."
        self.assertEqual(_queue(jd), ["OpenTelemetry", "ClickHouse"])

    def test_compound_weak_token_matched_component_wise_is_not_queued(self):
        # Profile Weak has "REST/gRPC APIs"; a JD naming only "REST APIs" is
        # covered component-wise (same gate logic) and must NOT be queued.
        jd = "You will design and own REST APIs for internal teams."
        self.assertNotIn("REST APIs", _queue(jd))
        self.assertEqual(_queue(jd), [])

    def test_never_token_present_is_categorized_not_queued(self):
        jd = "Prior Rust experience is a welcome bonus."
        self.assertNotIn("Rust", _queue(jd))
        self.assertEqual(_queue(jd), [])

    def test_nested_weak_member_is_categorized(self):
        # "Lambda" is a member of the Weak "AWS (Lambda, SQS, SNS)" token.
        jd = "Build event handlers with Lambda."
        self.assertEqual(_queue(jd), [])

    def test_mixed_jd_queues_only_the_uncategorized(self):
        jd = ("Stack: Python, Kubernetes, REST APIs, and OpenTelemetry. "
              "Rust is a plus. Familiarity with WebAssembly helps.")
        self.assertEqual(_queue(jd), ["OpenTelemetry", "WebAssembly"])

    def test_company_and_header_words_are_not_flagged(self):
        # Precision guard: bare capitalized words / acronyms are not skills.
        jd = ("About Example Corp\nSenior Software Engineer, Platform\n"
              "Partner with SRE teams and design public APIs and client SDKs.")
        self.assertEqual(_queue(jd), [])

    def test_explicit_non_skill_suppression_does_not_queue_company_name(self):
        jd = "Coordinate integrations with LinkedIn."
        self.assertEqual(_queue(jd), [])

    def test_slash_separated_degree_requirements_are_not_skills(self):
        jd = ("A BS/MS/PhD in computer science or equivalent practical "
              "experience is required.")
        self.assertEqual(_queue(jd), [])

    def test_standalone_degree_requirement_is_not_a_skill(self):
        jd = "A PhD in computer science or equivalent practical experience is preferred."
        self.assertEqual(_queue(jd), [])

    def test_single_letter_language_uses_safe_profile_alias(self):
        jd = "Experience programming in C or R is useful."
        self.assertEqual(_queue(jd), [])

    def test_slash_compound_queues_only_uncategorized_components(self):
        jd = "Experience with Docker/LXC/LXD and C/C++ is useful."
        self.assertEqual(_queue(jd), ["LXC", "LXD"])

    def test_slash_compound_drops_plain_english_components(self):
        jd = "Partner with SRE/CRE/production teams."
        self.assertEqual(_queue(jd), ["SRE", "CRE"])

    def test_cli_empty_queue_prints_message_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            jd = Path(tmp) / "JD-x.md"
            jd.write_text("We use Python and Docker.", encoding="utf-8")
            prof = Path(tmp) / "profile.md"
            prof.write_text(PROFILE, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "skills_diff.py"),
                 str(jd), "--profile", str(prof)],
                capture_output=True, text=True, env=dict(os.environ))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "no uncategorized skills")

    def test_cli_reports_queue_with_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            jd = Path(tmp) / "JD-x.md"
            jd.write_text("Experience with OpenTelemetry required.", encoding="utf-8")
            prof = Path(tmp) / "profile.md"
            prof.write_text(PROFILE, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "skills_diff.py"),
                 str(jd), "--profile", str(prof)],
                capture_output=True, text=True, env=dict(os.environ))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("OpenTelemetry", proc.stdout)
            self.assertIn("1 uncategorized skill", proc.stdout)


class MetadataIsNotASkillTests(unittest.TestCase):
    """Issue #261 — provenance URLs and location/time-zone metadata are not skills.

    The queue is a BLOCKING user decision (Step 7 asks the user to categorize
    every item), so a token that came from a URL query string or an office
    address manufactures a false decision and teaches a novice that the
    extractor cannot be trusted.
    """

    def test_url_query_parameter_is_not_a_skill(self):
        jd = ("Source: https://jobs.example.com/acme/01b3e311-43a1?includeCompensation=true\n"
              "You will run Kubernetes and Docker in production.")
        self.assertEqual(_queue(jd), [])

    def test_bare_host_with_path_and_query_is_stripped(self):
        jd = ("Apply: jobs.ashbyhq.com/acme/fe0576f6?includeCompensation=true&sortBy=postedAt\n"
              "We use Python and PostgreSQL.")
        self.assertEqual(_queue(jd), [])

    def test_timezone_abbreviations_are_never_skills(self):
        jd = "Core collaboration hours are 9am-5pm ET/PT for the whole team."
        self.assertEqual(_queue(jd), [])

    def test_location_metadata_line_is_ignored(self):
        jd = ("Location: San Francisco, CA / New York, NY — hybrid, ET/PT overlap\n"
              "Time zone: ET\n"
              "The stack is Python and Docker.")
        self.assertEqual(_queue(jd), [])

    def test_metadata_field_drops_its_value_not_the_whole_line(self):
        # A one-line header keeps the half that names the stack.
        jd = "Location: NYC, NY | Stack: OpenTelemetry and ClickHouse"
        self.assertEqual(_queue(jd), ["OpenTelemetry", "ClickHouse"])

    def test_city_state_pair_outside_a_labelled_line_is_ignored(self):
        jd = "Our engineers sit in Seattle, WA/Remote and use Docker daily."
        self.assertEqual(_queue(jd), [])

    def test_uppercase_conjunction_is_not_read_as_a_state(self):
        # "OR" is Oregon and also a shouted conjunction — stripping the second
        # would silently drop the skill in front of it.
        jd = "Experience with ClickHouse, OR OpenTelemetry, is required."
        self.assertEqual(_queue(jd), ["ClickHouse", "OpenTelemetry"])

    def test_real_skills_next_to_the_metadata_still_surface(self):
        jd = ("Source: https://jobs.example.com/acme/01b3?includeCompensation=true\n"
              "Location: Remote (US) — San Francisco, CA. Core hours 9am-5pm ET/PT.\n"
              "You will partner with SRE/DevOps teams on OpenTelemetry and "
              "ClickHouse.")
        self.assertEqual(_queue(jd), ["SRE", "DevOps", "OpenTelemetry", "ClickHouse"])

    def test_dotted_technology_name_is_not_mistaken_for_a_url(self):
        # "socket.io" carries a URL-shaped TLD but no path — it, and everything
        # after it on the line, must survive the URL stripper.
        jd = "Experience with socket.io and ClickHouse is required."
        self.assertEqual(_queue(jd), ["socket.io", "ClickHouse"])


class CompoundAndQualifiedAliasTests(unittest.TestCase):
    """Issue #272 — compound skills stay whole and qualified profile entries match.

    A qualified profile entry ("Java basics", "MySQL administration") is already
    a truthful decision about that concept. Re-queueing the bare token pressures
    the user into adding a second, BROADER entry — the opposite of the skill
    gate's purpose.
    """

    PROFILE = """# Profile

## Skills

### Approved (include in most resumes, if not all)

- Testing: manual testing, test cases, basic SQL queries

### Weak (user-facing: Weak or Selective — include ONLY when the JD mentions it)

- Languages: Java basics

### Never (never include in any resume)

- Out of scope: CI/CD work, MySQL administration, A/B testing
"""

    def queue(self, jd_text: str) -> list[str]:
        return skills_diff.uncategorized_queue(jd_text, self.PROFILE)

    def test_slash_compound_is_not_split_when_categorized(self):
        # Never lists "CI/CD work" — the JD's "CI/CD" is that same concept.
        self.assertEqual(self.queue("Familiarity with CI/CD pipelines is a plus."), [])

    def test_qualified_profile_entries_cover_the_bare_jd_token(self):
        jd = "Basic Java and SQL knowledge; MySQL experience is helpful."
        self.assertEqual(self.queue(jd), [])

    def test_ab_testing_variants_resolve_to_one_concept(self):
        jd = "Support A/B-testing, A/B testing, and A/B experiments."
        self.assertEqual(self.queue(jd), [])

    def test_generic_uppercase_word_is_not_a_skill(self):
        jd = "Write manual test cases for our WEB/mobile products."
        self.assertEqual(self.queue(jd), [])

    def test_the_full_reported_queue_collapses_to_real_skills(self):
        jd = ("Source: https://jobs.example.com/qa/12345?includeCompensation=true\n"
              "Location: San Francisco, CA / New York, NY — 9am-5pm ET/PT\n"
              "- Write and run manual test cases for our WEB/mobile products.\n"
              "- Familiarity with CI/CD pipelines is a plus.\n"
              "- Basic Java and SQL knowledge; MySQL experience helpful.\n"
              "- Support A/B-testing and A/B experiments.\n"
              "- Partner with SRE/DevOps on release readiness.\n")
        self.assertEqual(self.queue(jd), ["SRE", "DevOps"])

    def test_uncategorized_compound_stays_one_concept(self):
        # Nothing in the profile covers A/B when the Never entry is removed:
        # the ask must still be ONE concept, not "A/B" plus "A/B-testing".
        profile = self.PROFILE.replace(", A/B testing", "")
        queue = skills_diff.uncategorized_queue(
            "Run A/B-testing and A/B experiments for the team.", profile)
        self.assertEqual(len(queue), 1, queue)
        self.assertIn("A/B", queue[0])

    def test_matching_never_broadens_the_declared_proficiency(self):
        # The tool reports; it never rewrites the profile or restates a
        # qualified entry as a bare, broader claim.
        with tempfile.TemporaryDirectory() as tmp:
            jd = Path(tmp) / "JD-x.md"
            jd.write_text("Basic Java and MySQL experience helps.", encoding="utf-8")
            prof = Path(tmp) / "profile.md"
            prof.write_text(self.PROFILE, encoding="utf-8")
            before = prof.read_text(encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "skills_diff.py"),
                 str(jd), "--profile", str(prof)],
                capture_output=True, text=True, env=dict(os.environ))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "no uncategorized skills")
            self.assertEqual(prof.read_text(encoding="utf-8"), before)

    def test_admin_entry_does_not_cover_an_unrelated_database(self):
        jd = "Operate MySQL and CockroachDB clusters."
        self.assertEqual(self.queue(jd), ["CockroachDB"])

    def test_uncategorized_compound_without_known_components_is_still_split(self):
        jd = "Experience with Docker/LXC/LXD is useful."
        self.assertEqual(self.queue(jd), ["Docker", "LXC", "LXD"])


if __name__ == "__main__":
    unittest.main()
