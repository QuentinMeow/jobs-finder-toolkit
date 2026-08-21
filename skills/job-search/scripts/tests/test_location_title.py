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
from location import assess_location, classify_location  # noqa: E402
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


class WeirdLocationFormatTests(unittest.TestCase):
    POLICY = {
        "metro": ["seattle"],
        "allow_us_remote": True,
        "us_only": True,
        "require_match": True,
    }

    def test_region_bucket_only_location_gets_distinct_review_reason(self):
        assessment = assess_location("West", self.POLICY)
        self.assertEqual(assessment.decision, "review")
        self.assertIn("weird_location_format", assessment.review_reasons)
        self.assertNotIn("unclassified_location", assessment.review_reasons)

    def test_known_geographies_keep_their_existing_decisions(self):
        cases = (
            ("Seattle, WA", "metro", "match"),
            ("United States (Remote)", "us_remote", "match"),
            ("London, United Kingdom", "foreign", "no_match"),
        )
        for raw, category, decision in cases:
            with self.subTest(raw=raw):
                assessment = assess_location(raw, self.POLICY)
                self.assertEqual(assessment.category, category)
                self.assertEqual(assessment.decision, decision)
                self.assertNotIn(
                    "weird_location_format", assessment.review_reasons)

    def test_established_region_and_workplace_signals_are_not_relabelled(self):
        for raw, decision in (
            ("EMEA", "no_match"),
            ("APAC", "no_match"),
            ("NAMER", "match"),
            ("Americas", "match"),
            ("Global Region", "match"),
        ):
            with self.subTest(raw=raw):
                assessment = assess_location(raw, self.POLICY)
                self.assertEqual(assessment.decision, decision)
                self.assertNotIn(
                    "weird_location_format", assessment.review_reasons)

        assessment = assess_location(
            "West", self.POLICY, workplace_hint="remote")
        self.assertEqual(assessment.decision, "match")
        self.assertNotIn("weird_location_format", assessment.review_reasons)


def _posting(location, *, title="Senior Software Engineer", remote="",
             source="board", description=""):
    return JobPosting(
        source=source,
        company="Example",
        title=title,
        url="https://example.test/jobs/x",
        location=location,
        remote=remote,
        description=description,
    )


class TokenBoundaryGateTests(unittest.TestCase):
    """The search gate must not drop a posting on a token matched mid-word.

    ``location_ok`` is the hard filter: a ``no_match`` here removes the posting
    from the run entirely, with nothing written anywhere. These four are the
    shapes that were being removed (or wrongly kept) by an unanchored match.
    """

    def test_us_city_containing_a_country_name_survives_the_gate(self):
        posting = _posting("Remote (Indianapolis)")
        self.assertTrue(location_ok(posting, PROFILE))
        self.assertNotEqual(
            posting.filter_assessments["location"]["category"], "foreign")

    def test_a_title_word_cannot_drop_a_us_remote_posting(self):
        # "apac" inside "Capacity" / "turin" inside "Turing".
        for title in ("Software Engineer, Capacity Planning",
                      "Software Engineer, Turing Compiler Team"):
            with self.subTest(title=title):
                posting = _posting("Remote - US", title=title)
                self.assertTrue(location_ok(posting, PROFILE))
                self.assertEqual(
                    posting.filter_assessments["location"]["decision"], "match")

    def test_foreign_city_with_its_own_country_code_is_dropped(self):
        posting = _posting("Bangalore, IN")
        self.assertFalse(location_ok(posting, PROFILE))
        self.assertEqual(
            posting.filter_assessments["location"]["category"], "foreign")

    def test_someone_elses_remote_work_does_not_make_a_role_remote(self):
        posting = _posting(
            "Columbus, OH",
            description=("The job may also involve mentoring remote interns "
                         "during the summer."))
        self.assertFalse(location_ok(posting, PROFILE))
        # The JD was read and states no work mode of its own, so the gate
        # reports the workplace as unstated instead of inferring an office
        # (#237). The gate verdict — a hard drop — is unchanged.
        self.assertNotEqual(posting.workplace, "remote")


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


class ManagerProductSuffixTests(unittest.TestCase):
    """A delimited trailing PRODUCT-name "… Manager" on an IC-role title is
    routed to `review` (not hard-dropped by the `manager` exclude); genuine
    management titles and any co-occurring exclude (staff/principal/…) still
    hard-drop. Regression for the 2026-07-25 title-gate false-negative audit
    (Palantir "… Mission Manager", OpenAI "… Ads Manager")."""

    TITLES = {
        "include": [
            "software engineer", "infrastructure engineer", "platform engineer",
            "infrastructure", "platform", "compute",
        ],
        "exclude": ["staff", "principal", "manager", "director", "head of", "vp"],
        "exclude_neutralize": ["member of technical staff"],
    }

    def _assess(self, title):
        return assess_title(title, self.TITLES)

    def test_product_manager_suffix_comma_is_reviewed(self):
        a = self._assess("Software Engineer, Ads Manager")
        self.assertEqual(a["decision"], "review")
        self.assertIn("title.manager_product_suffix_ambiguous", a["rule_ids"])
        self.assertIn(
            "title_manager_product_suffix_ambiguous", a["review_reasons"])

    def test_product_manager_suffix_dash_variants_are_reviewed(self):
        for dash in ("-", "\u2013", "\u2014"):
            with self.subTest(dash=dash):
                self.assertEqual(
                    self._assess(f"Software Engineer {dash} Mission Manager")[
                        "decision"], "review")

    def test_infra_engineer_product_manager_suffix_is_reviewed(self):
        self.assertEqual(
            self._assess("Infrastructure Engineer, Secrets Manager")["decision"],
            "review")

    def test_plain_manager_title_stays_no_match(self):
        self.assertEqual(self._assess("Engineering Manager")["decision"], "no_match")

    def test_definite_manager_suffix_stays_no_match(self):
        for title in (
            "Software Engineer - Product Manager",
            "Software Engineer - Program Manager",
            "Software Engineer, Engineering Manager",
            "Software Engineer - Technical Project Manager",
        ):
            with self.subTest(title=title):
                self.assertEqual(self._assess(title)["decision"], "no_match")

    def test_staff_dominates_manager_product_suffix(self):
        # `staff` is an independent exclude, so the manager-only exception cannot fire.
        self.assertEqual(
            self._assess("Staff Software Engineer, Lakebase Manager")["decision"],
            "no_match")

    def test_engineer_manager_without_delimiter_stays_no_match(self):
        # "Engineer Manager" (no comma/dash before Manager, not the final segment)
        # is a real engineering-manager shape, not a product suffix.
        self.assertEqual(
            self._assess("Software Engineer Manager, Developer Foundation")[
                "decision"], "no_match")

    def test_project_manager_prefix_stays_no_match(self):
        self.assertEqual(
            self._assess(
                "Technical Project Manager / IT Infrastructure Engineer")[
                "decision"], "no_match")

    def test_title_ok_keeps_the_reviewed_product_manager_role(self):
        posting = JobPosting(
            source="board", company="Example",
            title="Software Engineer - Mission Manager",
            url="https://example.test/jobs/mm")
        self.assertTrue(title_ok(posting, {"titles": self.TITLES}))
        self.assertIn(
            "title_manager_product_suffix_ambiguous", posting.review_reasons)


class MemberOfStaffNeutralizeFamilyTests(unittest.TestCase):
    """``exclude_neutralize`` names an IC title FAMILY, not one spelling of it.

    The profile listed "member of technical staff", so "Member of Technical Staff,
    Software Engineer" survived the ``staff`` exclude while a real board's "Member
    of Data Staff" — the same non-Staff-level IC title — was hard-dropped. A
    literal list is always one spelling short, so the declared intent now covers
    the family (the same move the ``new grad`` expansion already makes).
    """

    TITLES = {
        "include": ["software engineer", "data engineer"],
        "exclude": ["staff", "principal", "manager", "director"],
        "exclude_neutralize": ["member of technical staff"],
    }
    UNDECLARED = {**TITLES, "exclude_neutralize": []}

    def _decision(self, title, cfg=None):
        return assess_title(title, cfg or self.TITLES)["decision"]

    def test_other_spellings_of_the_family_survive(self):
        for title in (
            "Member of Technical Staff, Software Engineer",
            "Member of Data Staff, Software Engineer",
            "Member of Research Staff, Software Engineer",
            "Member of the Technical Staff, Software Engineer",
            "Members of Applied Research Staff, Software Engineer",
        ):
            with self.subTest(title=title):
                self.assertEqual(self._decision(title), "match")

    def test_genuine_staff_and_principal_titles_still_drop(self):
        for title in ("Staff Software Engineer", "Principal Software Engineer",
                      "Senior Staff Data Engineer",
                      "Principal Member of Technical Staff, Software Engineer"):
            with self.subTest(title=title):
                self.assertEqual(self._decision(title), "no_match")

    def test_a_seniority_prefix_inside_the_family_still_reads(self):
        assessment = assess_title(
            "Senior Member of Data Staff, Software Engineer", self.TITLES)
        self.assertEqual(assessment["decision"], "match")
        self.assertEqual(assessment["level"], "senior")

    def test_the_expansion_is_gated_on_the_profile_declaring_it(self):
        # A profile that never asked to neutralize the family keeps the plain
        # `staff` exclude; the generalization honors intent, it does not impose it.
        for title in ("Member of Technical Staff, Software Engineer",
                      "Member of Data Staff, Software Engineer"):
            with self.subTest(title=title):
                self.assertEqual(
                    self._decision(title, self.UNDECLARED), "no_match")


if __name__ == "__main__":
    unittest.main()
