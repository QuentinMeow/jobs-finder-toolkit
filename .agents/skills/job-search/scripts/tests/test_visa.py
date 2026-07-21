"""Tests for the visa-sponsorship heuristic and the --visa-policy binding.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s .agents/skills/job-search/scripts/tests \
        -t .agents/skills/job-search/scripts/tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Make the skill's own scripts/ (+ its _vendor/) importable, mirroring how
# search_jobs.py bootstraps itself when run directly.
_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import JobPosting  # noqa: E402
from scoring import visa_ok  # noqa: E402
from search_jobs import apply_visa_policy  # noqa: E402
from visa import classify_visa, visa_tags  # noqa: E402


class NegatedSponsorshipTests(unittest.TestCase):
    """Negated-sponsorship phrasings must classify as 'no', not 'yes'."""

    def test_immigration_sponsorship_support_not_available(self):
        label, _ = classify_visa(
            "Immigration Sponsorship support will NOT be available for this position")
        self.assertEqual(label, "no")

    def test_unable_to_provide_visa_sponsorship(self):
        label, _ = classify_visa("We are unable to provide visa sponsorship.")
        self.assertEqual(label, "no")

    def test_visa_sponsorship_will_not_be_available(self):
        label, _ = classify_visa("Visa sponsorship will not be available.")
        self.assertEqual(label, "no")

    def test_genuine_offer_still_yes(self):
        label, _ = classify_visa(
            "We offer visa sponsorship and are happy to sponsor H-1B transfers.")
        self.assertEqual(label, "yes")

    def test_non_immigration_sponsorship_copy_is_not_positive(self):
        label, _ = classify_visa(
            "We sponsor employee learning programs and community events.")
        self.assertEqual(label, "unclear")

    def test_perm_does_not_match_inside_unrelated_words(self):
        self.assertNotIn(
            "green_card_mentioned",
            visa_tags("You will perform reliability work with proper permissions."),
        )

    def test_explicit_perm_process_still_tags_green_card(self):
        self.assertIn(
            "green_card_mentioned",
            visa_tags("We support the PERM process for eligible employees."),
        )


class VisaPolicyBindingTests(unittest.TestCase):
    """--visa-policy must bind even when the profile ships needs_sponsorship: false."""

    def _posting(self, description: str) -> JobPosting:
        return JobPosting(source="test", company="ExampleCorp",
                          title="Senior Engineer", url="https://example.com/job",
                          description=description)

    def test_apply_visa_policy_implies_needs_sponsorship(self):
        profile = {"visa": {"needs_sponsorship": False}}
        apply_visa_policy(profile, "require_positive")
        self.assertEqual(profile["visa"]["policy"], "require_positive")
        self.assertTrue(profile["visa"]["needs_sponsorship"])

    def test_no_policy_leaves_profile_untouched(self):
        profile = {"visa": {"needs_sponsorship": False}}
        apply_visa_policy(profile, None)
        self.assertFalse(profile["visa"].get("needs_sponsorship"))

    def test_require_positive_binds_after_flag(self):
        # Before the flag: a profile that "does not need sponsorship" keeps
        # everything (visa gate is off) — including a silent/unclear posting.
        silent = self._posting("Build backend services.")
        profile = {"visa": {"needs_sponsorship": False}}
        self.assertTrue(visa_ok(silent, profile))

        # The CLI flag now implies needs_sponsorship, so require_positive binds and
        # diverts a posting that never states sponsorship to manual review rather
        # than silently dropping it.
        apply_visa_policy(profile, "require_positive")
        review = self._posting("Build backend services.")
        self.assertTrue(visa_ok(review, profile))
        self.assertIn("sponsorship_requires_review", review.review_reasons)
        # ...while keeping one that explicitly offers sponsorship.
        offer = self._posting("We provide visa sponsorship for this role.")
        self.assertTrue(visa_ok(offer, profile))


if __name__ == "__main__":
    unittest.main()
