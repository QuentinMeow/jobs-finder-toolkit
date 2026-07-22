"""Location regressions where boards hide the country in the title."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _path in (_SCRIPTS, _SCRIPTS / "_vendor"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from common import JobPosting  # noqa: E402
from location import classify_location  # noqa: E402
from scoring import assess_title, location_ok, title_ok  # noqa: E402


PROFILE = {
    "location": {
        "preferred": ["seattle"],
        "allow_remote": True,
        "us_only": True,
        "require_match": True,
    }
}

# A profile that (like the shipped example/real profiles) lists the generic
# workplace word "remote" among its preferred locations. This used to leak a
# foreign posting such as "Canada (Remote)" into a US-only shortlist because the
# word "remote" was treated as a preferred-metro token.
PROFILE_REMOTE_PREFERRED = {
    "location": {
        "preferred": ["san francisco", "austin", "remote"],
        "allow_remote": True,
        "us_only": True,
        "require_match": True,
    }
}


def _posting(location, *, title="Senior Software Engineer", remote="", source="board"):
    return JobPosting(
        source=source,
        company="Example",
        title=title,
        url="https://example.test/jobs/x",
        location=location,
        remote=remote,
    )


class PreferredRemoteWordTests(unittest.TestCase):
    """`remote`/`hybrid`/etc. in preferred[] must never match as a metro."""

    def test_canada_remote_does_not_match_via_remote_preferred_word(self):
        posting = _posting("Canada (Remote)", remote="remote")
        self.assertFalse(location_ok(posting, PROFILE_REMOTE_PREFERRED))
        self.assertEqual(
            posting.filter_assessments["location"]["category"], "foreign")

    def test_remote_us_still_matches(self):
        posting = _posting("Remote - US", remote="remote")
        self.assertTrue(location_ok(posting, PROFILE_REMOTE_PREFERRED))
        self.assertEqual(
            posting.filter_assessments["location"]["category"], "us_remote")

    def test_mixed_us_foreign_scope_is_reviewed(self):
        posting = _posting(
            "Remote - US / London, United Kingdom", remote="remote")
        self.assertTrue(location_ok(posting, PROFILE_REMOTE_PREFERRED))  # kept for review
        assessment = posting.filter_assessments["location"]
        self.assertEqual(assessment["decision"], "review")
        self.assertIn("mixed_us_foreign_scope", assessment["review_reasons"])

    def test_genuine_preferred_metro_beats_foreign_alternative(self):
        # A real preferred US metro still wins even if another listed alternative
        # is foreign (San Francisco is preferred; Toronto is not disqualifying).
        posting = _posting("San Francisco, CA / Toronto, Canada")
        self.assertTrue(location_ok(posting, PROFILE_REMOTE_PREFERRED))
        self.assertEqual(
            posting.filter_assessments["location"]["category"], "metro")

    def test_distributed_with_canada_title_is_foreign(self):
        posting = _posting(
            "Distributed", title="Senior Software Engineer, Canada", remote="remote")
        self.assertFalse(location_ok(posting, PROFILE_REMOTE_PREFERRED))
        self.assertEqual(
            posting.filter_assessments["location"]["category"], "foreign")


class ForeignTitleLocationTests(unittest.TestCase):
    def test_distributed_canada_title_is_not_us_remote(self):
        posting = JobPosting(
            source="board",
            company="Example",
            title="Senior Software Engineer, Canada",
            url="https://example.test/jobs/ca",
            location="Distributed",
            remote="remote",
        )
        self.assertFalse(location_ok(posting, PROFILE))

    def test_distributed_foreign_city_or_region_title_is_not_us_remote(self):
        for suffix in ("Canberra", "Nordics"):
            with self.subTest(suffix=suffix):
                posting = JobPosting(
                    source="board",
                    company="Example",
                    title=f"Senior Software Engineer, {suffix}",
                    url=f"https://example.test/jobs/{suffix.casefold()}",
                    location="Distributed",
                    remote="remote",
                )
                self.assertFalse(location_ok(posting, PROFILE))

    def test_distributed_us_title_remains_eligible(self):
        posting = JobPosting(
            source="board",
            company="Example",
            title="Senior Software Engineer, United States",
            url="https://example.test/jobs/us",
            location="Distributed",
            remote="remote",
        )
        self.assertTrue(location_ok(posting, PROFILE))

    def test_remote_italy_location_is_foreign(self):
        category = classify_location(
            "Remote (Italy) / TURIN, ITA / Bologna, ITA",
            {
                "metro": ["seattle"],
                "allow_us_remote": True,
                "us_only": True,
            },
        )
        self.assertEqual(category, "foreign")

    def test_full_jd_us_remote_alternative_passes_strict_location_gate(self):
        posting = JobPosting(
            source="greenhouse",
            company="Example",
            title="Senior Software Engineer",
            url="https://example.test/jobs/remote-alternative",
            location="San Francisco, CA • New York, NY • United States",
            remote="unknown",
            description=(
                "x" * 1900
                + " This role can be held from one of our US hubs or remotely "
                  "in the United States."
            ),
        )
        self.assertTrue(location_ok(posting, PROFILE))
        self.assertEqual(posting.workplace, "remote")
        self.assertEqual(
            posting.filter_assessments["location"]["decision"], "match")

    def test_nonpreferred_hybrid_is_not_treated_as_remote(self):
        posting = JobPosting(
            source="board",
            company="Example",
            title="Senior Software Engineer",
            url="https://example.test/jobs/hybrid",
            location="Austin, TX (Hybrid)",
            remote="hybrid",
        )
        self.assertFalse(location_ok(posting, PROFILE))


class TitleRoleGuardTests(unittest.TestCase):
    """Broad single-word domain includes must not admit non-engineering roles."""

    TITLES = {
        "include": [
            "software engineer", "platform engineer", "infrastructure engineer",
            "infrastructure", "platform", "compute", "sre",
        ],
        "exclude": ["manager", "director", "head of", "vp"],
        "exclude_neutralize": ["member of technical staff"],
    }

    def _decision(self, title):
        return assess_title(title, self.TITLES)["decision"]

    def test_finance_infrastructure_use_is_rejected(self):
        self.assertEqual(
            self._decision("Capital Markets Infrastructure Financing Associate"),
            "no_match")

    def test_business_platform_use_is_rejected(self):
        self.assertEqual(
            self._decision("Platform Partnerships Lead, Advertising Business"),
            "no_match")

    def test_infrastructure_engineer_is_accepted(self):
        self.assertEqual(self._decision("Infrastructure Engineer"), "match")

    def test_platform_engineer_is_accepted(self):
        self.assertEqual(self._decision("Senior Platform Engineer"), "match")

    def test_sre_standalone_family_is_accepted(self):
        self.assertEqual(self._decision("SRE"), "match")

    def test_mts_neutralization_is_preserved(self):
        self.assertEqual(
            self._decision("Member of Technical Staff, Software Engineer"), "match")

    def test_engineering_leader_ambiguity_is_review(self):
        titles = {"include": ["software engineer", "engineering"],
                  "exclude": ["manager", "director", "head of", "vp"]}
        assessment = assess_title("Engineering Leader", titles)
        self.assertEqual(assessment["decision"], "review")
        self.assertIn("title_leadership_ambiguous", assessment["review_reasons"])

    def test_explicit_manager_title_is_rejected(self):
        titles = {"include": ["software engineer", "engineering"],
                  "exclude": ["manager", "director", "head of", "vp"]}
        self.assertEqual(assess_title("Engineering Manager", titles)["decision"],
                         "no_match")

    def test_title_ok_keeps_review_but_drops_no_match(self):
        review = JobPosting(
            source="board", company="Example", title="Engineering Leader",
            url="https://example.test/jobs/lead")
        keep_profile = {"titles": {
            "include": ["software engineer", "engineering"],
            "exclude": ["manager"]}}
        self.assertTrue(title_ok(review, keep_profile))
        self.assertIn("title_leadership_ambiguous", review.review_reasons)

        finance = JobPosting(
            source="board", company="Example",
            title="Capital Markets Infrastructure Financing Associate",
            url="https://example.test/jobs/fin")
        self.assertFalse(title_ok(finance, {"titles": self.TITLES}))


if __name__ == "__main__":
    unittest.main()
