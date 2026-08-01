import sys
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

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


class WorkplaceWordLocationTests(unittest.TestCase):
    """Boards that park a workplace WORD where the location belongs.

    Fixtures for the two misclassifications a live single-company canary hit on a
    board whose postings carry "Hybrid" / "In-Office" / "Distributed" in the ATS
    location field and name the actual cities only inside the JD body.
    """

    POLICY = {**_POLICY, "require_match": True}

    HYBRID_JD = (
        "About the team\n"
        "We build the deployment platform.\n\n"
        "This is a hybrid role and you will work from one of our offices three\n"
        "days per week alongside your team.\n\n"
        "Available Locations: Chicago, IL; Denver, CO; Atlanta, GA; Dallas, TX\n"
    )
    REMOTE_JD = (
        "About the team\n"
        "We build the ingestion platform.\n\n"
        "This is a fully remote role. You may live anywhere you are authorized\n"
        "to work.\n\n"
        "Available Locations: Remote - United States\n"
    )

    def test_region_word_in_title_cannot_carry_a_us_remote_match(self):
        # FALSE POSITIVE: hybrid across four non-preferred US cities was reported
        # as a US-remote match because "Americas" in the TITLE supplied
        # `broad_us_scope`. A coverage region in a title is not a work grant.
        result = assess_location(
            "In-Office",
            self.POLICY,
            title="Solutions Architect, Americas",
            description=self.HYBRID_JD,
            workplace_hint="unknown",
        )
        self.assertNotEqual(result.decision, "match")
        self.assertEqual(result.decision, "review")
        self.assertEqual(result.workplace, "hybrid")
        self.assertNotIn("broad_us_scope", result.evidence)
        self.assertIn("workplace_tag_without_geography", result.review_reasons)

    def test_region_word_in_location_still_grants_us_scope(self):
        # The narrowing above is title-only: a region in the LOCATION field keeps
        # its historical us_remote reading.
        result = assess_location("Americas", self.POLICY)
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")

    def test_us_region_with_an_evidenced_office_obligation_is_reviewed(self):
        # Same defect family, no title involved: "United States" + a JD that
        # requires office days is not a US-remote match. The country is known and
        # the office is not, so it is reviewable — never a silent match.
        result = assess_location(
            "United States",
            self.POLICY,
            description="This is a hybrid role with three office days each week.",
        )
        self.assertEqual(result.decision, "review")
        self.assertIn("us_scope_without_remote_workplace", result.review_reasons)

    def test_foreign_title_scope_still_rejects(self):
        # The title keeps its REJECTING power — only its match-granting power went.
        result = assess_location(
            "Distributed", self.POLICY,
            title="Senior Software Engineer, Canberra", workplace_hint="unknown")
        self.assertEqual(result.category, "foreign")
        self.assertEqual(result.decision, "no_match")

    def test_bare_hybrid_tag_does_not_veto_an_explicit_jd_remote_grant(self):
        # FALSE NEGATIVE: an explicitly remote role was pushed to review because
        # the location field said "Hybrid". A bare workplace tag names no office,
        # so it cannot contradict the JD.
        result = assess_location(
            "Hybrid",
            self.POLICY,
            title="Senior Software Engineer, Platform",
            description=self.REMOTE_JD,
            workplace_hint="hybrid",
        )
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")
        self.assertEqual(result.workplace, "remote")
        self.assertNotIn(
            "location_hybrid_jd_remote_conflict", result.review_reasons)
        self.assertIn("jd_remote_over_bare_workplace_tag", result.evidence)

    def test_place_bearing_hybrid_location_still_conflicts_with_jd_remote(self):
        # The conflict rule survives where it earns its keep: this location names
        # an office to report to, so remote-vs-hybrid stays a human's call.
        result = assess_location(
            "Austin, TX (Hybrid)",
            self.POLICY,
            description=self.REMOTE_JD,
            workplace_hint="hybrid",
        )
        self.assertEqual(result.decision, "review")
        self.assertIn(
            "location_hybrid_jd_remote_conflict", result.review_reasons)

    def test_workplace_word_locations_report_a_specific_review_reason(self):
        for raw in ("Hybrid", "In-Office", "Distributed"):
            with self.subTest(raw=raw):
                result = assess_location(raw, self.POLICY)
                self.assertEqual(result.decision, "review")
                self.assertIn(
                    "workplace_tag_without_geography", result.review_reasons)
                self.assertNotIn(
                    "unclassified_location", result.review_reasons)


if __name__ == "__main__":
    unittest.main()
