import sys
import unittest
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from location import assess_location, classify_location, classify_locations  # noqa: E402

# A representative us_only policy with a couple of preferred metros.
_POLICY = {
    "metro": ["springfield", "fairview"],
    "allow_us_remote": True,
    "us_only": True,
}


class DistributedTagTests(unittest.TestCase):
    """A bare 'Distributed' location tag is unverified, not a US-remote match."""

    def test_bare_distributed_is_unknown_not_us_remote(self):
        self.assertEqual(classify_location("Distributed", _POLICY), "unknown")

    def test_distributed_hybrid_tag_is_unknown(self):
        self.assertEqual(
            classify_location("Distributed; Hybrid", _POLICY), "unknown")

    def test_distributed_does_not_grant_a_match(self):
        # The globally-pinned-role false positive: "Distributed" tag on a role
        # that is really a foreign city must not classify as a match.
        _, matched = classify_locations(["Distributed"], _POLICY)
        self.assertFalse(matched)

    def test_foreign_city_still_foreign(self):
        self.assertEqual(classify_location("Melbourne", _POLICY), "foreign")


class RemoteRegressionTests(unittest.TestCase):
    """Genuine remote / US signals must keep matching after the fix."""

    def test_explicit_remote_still_us_remote(self):
        self.assertEqual(classify_location("Remote", _POLICY), "us_remote")
        self.assertEqual(classify_location("Remote (US)", _POLICY), "us_remote")

    def test_country_level_us_still_us_remote(self):
        self.assertEqual(classify_location("United States", _POLICY), "us_remote")

    def test_preferred_metro_still_matches(self):
        self.assertEqual(classify_location("Springfield, ST", _POLICY), "metro")

    def test_worldwide_and_anywhere_remain_remote(self):
        self.assertEqual(classify_location("Anywhere", _POLICY), "us_remote")
        self.assertEqual(classify_location("Worldwide", _POLICY), "us_remote")


class FullEvidenceAssessmentTests(unittest.TestCase):
    def test_office_list_or_us_remote_uses_full_jd(self):
        description = (
            "x" * 1900
            + " This role can be held from one of our US hubs or remotely "
              "in the United States."
        )
        result = assess_location(
            "San Francisco, CA • New York, NY • United States",
            {**_POLICY, "require_match": True},
            title="Platform Engineer",
            description=description,
            workplace_hint="unknown",
        )
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")
        self.assertEqual(result.workplace, "remote")
        self.assertIn("jd_office_or_remote", result.evidence)

    def test_hybrid_outside_preferred_metro_is_not_generic_remote(self):
        result = assess_location(
            "Austin, TX (Hybrid)",
            {**_POLICY, "require_match": True},
            title="Platform Engineer",
        )
        self.assertEqual(result.decision, "no_match")
        self.assertEqual(result.workplace, "hybrid")

    def test_remote_onsite_conflict_requires_review(self):
        result = assess_location(
            "Remote (US)",
            {**_POLICY, "require_match": True},
            description="This role must work in-office five days per week.",
        )
        self.assertEqual(result.decision, "review")
        self.assertIn("remote_onsite_conflict", result.review_reasons)

    def test_optional_hybrid_alongside_remote_is_not_a_conflict(self):
        result = assess_location(
            "United States",
            {**_POLICY, "require_match": True},
            description=(
                "This role can be based remotely anywhere in the US, with "
                "opportunities for hybrid work at our office hubs."
            ),
            workplace_hint="hybrid",
        )
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")
        self.assertEqual(result.workplace, "remote")
        self.assertNotIn("remote_hybrid_conflict", result.review_reasons)

    def test_negated_in_office_requirement_is_not_onsite(self):
        result = assess_location(
            "Remote (US)",
            {**_POLICY, "require_match": True},
            description=(
                "This role can be based remotely. There is no minimum "
                "in-office qualification requirement."
            ),
            workplace_hint="remote",
        )
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.workplace, "remote")
        self.assertNotIn("jd_onsite_required", result.evidence)

    def test_mixed_us_foreign_scope_requires_review(self):
        result = assess_location(
            "Remote - US / London, United Kingdom",
            {**_POLICY, "require_match": True},
        )
        self.assertEqual(result.decision, "review")
        self.assertIn("mixed_us_foreign_scope", result.review_reasons)


if __name__ == "__main__":
    unittest.main()
