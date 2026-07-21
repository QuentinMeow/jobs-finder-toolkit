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
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import skills_diff  # noqa: E402


PROFILE = """# Profile

## Skills

### Approved (include in most resumes, if not all)

- Programming Languages: Python, Java, Go
- Skills: Docker, Kubernetes, PostgreSQL, REST APIs

### Weak (user-facing: Weak or Selective — include ONLY when the JD mentions it)

- Cloud: AWS (Lambda, SQS, SNS), service mesh
- APIs: REST/gRPC APIs

### Never (never include in any resume)

- Languages: Rust, Scala

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


if __name__ == "__main__":
    unittest.main()
