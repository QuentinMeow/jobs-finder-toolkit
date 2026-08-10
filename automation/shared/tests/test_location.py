import sys
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from location import (  # noqa: E402
    assess_location, classify_location, classify_locations,
    _onsite_rule_hits, _remote_rule_hits,
)

# A representative us_only policy with a couple of preferred metros.
_POLICY = {
    "metro": ["springfield", "fairview"],
    "allow_us_remote": True,
    "us_only": True,
}


class TokenBoundaryTests(unittest.TestCase):
    """No keyword list may match INSIDE a longer word.

    Every list in this module is a bag of place words scanned against short,
    noisy strings. A bare substring test therefore fails in both directions: it
    invents a foreign posting out of a US city ("india" inside "Indianapolis")
    and a US posting out of nothing ("usa" inside "thousand"). The drop
    direction is the serious half — it hides a real opening and tells nobody.
    """

    def test_us_city_containing_a_country_name_is_not_foreign(self):
        for raw in ("Indianapolis", "Indianapolis Metro Area",
                    "Remote (Indianapolis)"):
            with self.subTest(raw=raw):
                result = assess_location(raw, _POLICY)
                self.assertNotEqual(result.category, "foreign")
                self.assertNotEqual(result.decision, "no_match")
                self.assertNotIn("foreign_scope", result.evidence)

    def test_us_state_containing_a_country_name_keeps_its_us_scope(self):
        # "india" inside "Indiana", "mexico" inside "New Mexico": both used to
        # collide with the foreign list and land on mixed-scope review.
        for raw in ("Remote - Indiana", "Remote - New Mexico"):
            with self.subTest(raw=raw):
                result = assess_location(raw, _POLICY)
                self.assertEqual(result.category, "us_remote")
                self.assertEqual(result.decision, "match")
                self.assertNotIn(
                    "mixed_us_foreign_scope", result.review_reasons)

    def test_a_title_word_cannot_manufacture_a_foreign_scope(self):
        # The title joins the foreign-scope context, so "apac" inside "Capacity"
        # and "turin" inside "Turing" used to demote a clean US posting.
        for title in ("Software Engineer, Capacity Planning",
                      "Software Engineer, Turing Compiler Team"):
            with self.subTest(title=title):
                result = assess_location("Remote - US", _POLICY, title=title)
                self.assertEqual(result.category, "us_remote")
                self.assertEqual(result.decision, "match")
                self.assertNotIn(
                    "mixed_us_foreign_scope", result.review_reasons)

    def test_a_us_signal_may_not_ride_inside_a_word_either(self):
        # "usa" inside "thoUSAnd" manufactured `broad_us_scope` (and a match)
        # for a string carrying no US signal at all.
        result = assess_location("Thousand Oaks", _POLICY)
        self.assertNotIn("broad_us_scope", result.evidence)
        self.assertEqual(result.decision, "review")


class StateAbbreviationVersusCountryCodeTests(unittest.TestCase):
    """26 US state abbreviations are also ISO-3166 country codes.

    ``Bangalore, IN`` and ``Indianapolis, IN`` are the same shape, so position
    cannot separate them. What separates them is whether the rest of the SAME
    field already names the country the code stands for.
    """

    def test_foreign_city_with_its_own_country_code_is_foreign(self):
        for raw in ("Bangalore, IN", "Berlin, DE", "Toronto, CA",
                    "Tel Aviv, IL", "Munich, DE", "Mumbai, IN (Remote)"):
            with self.subTest(raw=raw):
                result = assess_location(raw, _POLICY)
                self.assertEqual(result.category, "foreign")
                self.assertEqual(result.decision, "no_match")

    def test_us_city_with_the_same_code_keeps_its_us_reading(self):
        onsite = assess_location("Indianapolis, IN", _POLICY)
        self.assertEqual(onsite.category, "other_us")
        remote = assess_location("Remote - Indianapolis, IN", _POLICY)
        self.assertEqual(remote.category, "us_remote")
        self.assertEqual(remote.decision, "match")

    def test_a_code_is_only_resolved_by_its_own_field(self):
        # The code sits in the location, so only the location may resolve it. A
        # foreign country in the TITLE is a coverage descriptor and must not
        # turn a US state code into a country code and drop the posting.
        result = assess_location(
            "Sacramento, CA", _POLICY, title="Solutions Architect, Canada")
        self.assertNotEqual(result.decision, "no_match")
        self.assertIn("mixed_us_foreign_scope", result.review_reasons)

    def test_a_city_shared_by_both_countries_stays_undecided(self):
        # Vancouver WA and Vancouver BC are both real. The code decides it when
        # it corroborates the country; otherwise a human does.
        canada = assess_location("Vancouver, CA", _POLICY)
        self.assertEqual(canada.category, "foreign")
        shared = assess_location("Vancouver, WA", _POLICY)
        self.assertEqual(shared.decision, "review")
        self.assertIn("mixed_us_foreign_scope", shared.review_reasons)

    def test_a_contested_code_alone_is_undecidable(self):
        # Nothing but a code that reads as a state AND as a country: neither
        # verdict is earned, so neither is given.
        for raw in ("Remote - CA", "Remote (DE)", "IN"):
            with self.subTest(raw=raw):
                result = assess_location(raw, _POLICY)
                self.assertEqual(result.decision, "review")
                self.assertIn("ambiguous_state_or_country_code",
                              result.review_reasons)

    def test_a_named_city_or_an_uncontested_code_is_decided(self):
        for raw in ("Remote - Sacramento, CA", "Remote - WA", "Remote - US, CA"):
            with self.subTest(raw=raw):
                result = assess_location(raw, _POLICY)
                self.assertEqual(result.decision, "match")
                self.assertNotIn("ambiguous_state_or_country_code",
                                 result.review_reasons)


class RemoteGrantQualifierTests(unittest.TestCase):
    """"can/may/could … remote" needs a verb binding remote to THIS role."""

    def test_someone_elses_remote_work_is_not_a_remote_grant(self):
        for description in (
            "The job may also involve mentoring remote interns during the "
            "summer.",
            "The role may require you to collaborate with remote teams across "
            "several time zones.",
            "This position can be filled by a remote contractor agency.",
        ):
            with self.subTest(description=description[:40]):
                result = assess_location(
                    "Columbus, OH", _POLICY, description=description)
                self.assertNotIn("jd_role_can_be_remote", result.evidence)
                self.assertEqual(result.workplace, "onsite")
                self.assertEqual(result.category, "other_us")

    def test_genuine_remote_grants_still_read_as_remote(self):
        for description in (
            "This role can be performed remotely from anywhere in the United "
            "States.",
            "This position may be based remotely.",
            "This role can be fully remote.",
            "The job can be done remotely.",
            "This position can be held remotely.",
            "This role may be worked remotely.",
            "This role, which reports to the Director of Platform "
            "Engineering, can be performed remotely.",
        ):
            with self.subTest(description=description[:40]):
                result = assess_location(
                    "Columbus, OH", _POLICY, description=description)
                self.assertIn("jd_role_can_be_remote", result.evidence)
                self.assertEqual(result.workplace, "remote")
                self.assertEqual(result.decision, "match")


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

    def test_remote_with_a_us_signal_is_still_us_remote(self):
        self.assertEqual(classify_location("Remote (US)", _POLICY), "us_remote")
        self.assertEqual(classify_location("Remote - US", _POLICY), "us_remote")
        self.assertEqual(
            classify_location("Remote, United States", _POLICY), "us_remote")

    def test_bare_remote_alone_is_not_a_us_signal(self):
        # Reversal of an earlier assertion here. "Remote" is a work MODE, not a
        # place: a foreign employer writes the bare word exactly as a US one does,
        # and one did — a European agency's posting scored a confident US-remote
        # match on a location field whose entire content was "remote". With no
        # country in the location, the title or the JD, the honest answer is
        # review, which preserves the posting for a human read.
        self.assertEqual(classify_location("Remote", _POLICY), "unknown")
        self.assertEqual(classify_location("remote", _POLICY), "unknown")

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


class ResidencyRestrictedRemoteTests(unittest.TestCase):
    """A remote grant that names its own residency metro is not open US-remote.

    A JD grants remote work and then, in the same breath, requires the candidate
    to live in one metro. The grant fired ``jd_remote_role``, the restriction was
    read by nothing, and the posting came back a CONFIDENT us_remote match the
    caller had no reason to re-read. In one live single-company re-check three of
    the four confident matches were this shape, each pinned to a different
    non-preferred metro.
    """

    POLICY = {"metro": ["springfield", "fairview"], "allow_us_remote": True,
              "us_only": True, "require_match": True}

    def _assess(self, description, location="Remote"):
        return assess_location(
            location, self.POLICY, title="Software Engineer",
            description=description, workplace_hint="")

    def test_non_preferred_residency_metro_is_no_match(self):
        result = self._assess(
            "This is a remote role but the location requirement is that you "
            "reside in the Dallas Fort Worth Area.")
        self.assertEqual(result.decision, "no_match")
        self.assertEqual(result.category, "other_us")
        self.assertIn("jd_remote_bound_to_residency", result.evidence)

    def test_preferred_residency_metro_still_matches(self):
        result = self._assess(
            "This is a remote role but you must reside in the Springfield area.")
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "metro")
        self.assertIn("jd_residency_preferred_metro", result.evidence)

    def test_foreign_residency_requirement_is_no_match(self):
        result = self._assess(
            "This is a remote role; you must reside in Warsaw.")
        self.assertEqual(result.decision, "no_match")
        self.assertEqual(result.category, "foreign")

    def test_unreadable_residency_place_goes_to_review_not_us_remote(self):
        # Never fall back to us_remote: the JD said the grant is bounded, and a
        # place this module cannot parse is a human's call.
        result = self._assess(
            "This is a remote role but you must reside in the Tri-Valley "
            "corridor.")
        self.assertEqual(result.decision, "review")
        self.assertIn("residency_restriction_unparsed", result.review_reasons)

    def test_somebody_elses_address_does_not_narrow_the_grant(self):
        # The requirement word is mandatory: a sentence about where colleagues
        # happen to live is not a restriction on this role.
        result = self._assess(
            "This is a fully remote role in the United States. Many of our "
            "engineers live in Austin and meet up monthly.",
            location="Remote - US")
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")

    def test_a_remote_grant_with_no_residency_clause_is_unchanged(self):
        result = self._assess("This is a fully remote role.",
                              location="Remote - US")
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")
        self.assertIn("remote_eligible", result.evidence)


class UsCountryResidencyTests(unittest.TestCase):
    """A residency requirement naming the COUNTRY confirms US-remote.

    The residency reader knew preferred metros, US states, US hubs and foreign
    places, and could not name the one place US-remote boilerplate always names:
    the United States. So the single most common sentence in a US-remote posting
    — "you must reside in the United States" — classified as an unreadable
    restriction and sent every such posting to manual review, even when the
    location field ALREADY said US. The residency branch runs before the location
    field is consulted, so it overrode that too.

    A country-wide residency rule cannot narrow anything: the whole country
    satisfies it, which is exactly the ``us_remote`` category. The rule stays
    asymmetric — it still never GRANTS remote, it only reads a grant's geography.
    """

    POLICY = {"metro": ["springfield", "fairview"], "allow_us_remote": True,
              "us_only": True, "require_match": True}

    def _assess(self, description, location="Remote"):
        return assess_location(
            location, self.POLICY, title="Software Engineer",
            description=description, workplace_hint="")

    def test_a_country_wide_residency_requirement_is_us_remote(self):
        for location in ("Remote", "Remote (US)", "Remote - US", ""):
            for sentence in (
                "You must reside in the United States.",
                "You must be located in the United States to be eligible.",
                "Candidates must be located in the US.",
                "You must be based in the USA.",
                "You must reside in US.",
            ):
                with self.subTest(location=location, sentence=sentence):
                    result = self._assess(
                        "This is a fully remote role. " + sentence,
                        location=location)
                    self.assertEqual(result.decision, "match")
                    self.assertEqual(result.category, "us_remote")
                    self.assertIn("jd_residency_us_scope", result.evidence)

    def test_a_bare_remote_field_needs_no_other_us_signal(self):
        # The residency sentence IS the US signal, so `remote_without_us_scope`
        # must not fire on a location field that is only the word "Remote".
        result = self._assess("You must reside in the United States.")
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")
        self.assertEqual(result.review_reasons, ())

    def test_a_narrower_place_still_wins_over_the_country(self):
        # The country reading is checked LAST. A clause that also names a state,
        # a hub, a preferred metro or a foreign country keeps the reading it
        # already had — the safe direction, and the one the corpus pins.
        for sentence, decision, category in (
            ("You must reside in California.", "no_match", "other_us"),
            ("You must reside in the Boston area.", "no_match", "other_us"),
            ("You must reside in the Springfield area.", "match", "metro"),
            ("You must reside in Canada.", "no_match", "foreign"),
            ("You must reside in the United States or Canada.",
             "no_match", "foreign"),
        ):
            with self.subTest(sentence=sentence):
                result = self._assess(sentence, location="Remote (US)")
                self.assertEqual(result.decision, decision)
                self.assertEqual(result.category, category)

    def test_a_negated_residency_clause_never_manufactures_a_match(self):
        # "You do not need to live in the US" is not a US residency requirement.
        # It stays a review, exactly as it was before the country reading
        # existed: the sentence says where you need NOT be, and says nothing
        # about whether this role is open in the US at all.
        for sentence in (
            "You do not need to reside in the United States.",
            "There is no requirement to reside in the United States.",
            "You are not required to reside in the United States.",
            "You must not reside in the United States.",
        ):
            with self.subTest(sentence=sentence):
                result = self._assess(sentence)
                self.assertEqual(result.decision, "review")
                self.assertIn("residency_restriction_unparsed",
                              result.review_reasons)

    def test_an_unrelated_negative_clause_does_not_cancel_the_requirement(self):
        # The negation window is anchored to the requirement word. A sentence-wide
        # search would read the negative half of each of these as "residency not
        # required" and drop a posting that plainly requires US residency.
        for sentence in (
            "We are not able to sponsor visas; you must reside in the "
            "United States.",
            "We do not have offices, so you must reside in the United States.",
        ):
            with self.subTest(sentence=sentence):
                result = self._assess(sentence)
                self.assertEqual(result.decision, "match")
                self.assertEqual(result.category, "us_remote")

    def test_the_pronoun_after_near_is_not_the_country(self):
        # "near us" is an office, not a country. Bare "us" is read as the US only
        # after "in"/"within"; anything else keeps its review.
        result = self._assess("You must live near us.")
        self.assertEqual(result.decision, "review")
        self.assertIn("residency_restriction_unparsed", result.review_reasons)

    def test_a_dotted_abbreviation_stays_at_review_on_purpose(self):
        # `_JD_RESIDENCY_RE`'s place capture excludes "." so a residency clause
        # cannot run past its own sentence. That also truncates "the U.S." to
        # "the U", so the dotted abbreviation never reaches the country reading
        # and keeps its review. Widening the capture is NOT the fix: "the U.S. or
        # Canada" truncates identically, so a dotted reading would call that
        # posting US-remote while the spelled-out "the United States or Canada"
        # correctly stays foreign. Pinned so the residual is a decision, not a
        # surprise.
        result = self._assess("You must reside in the U.S.")
        self.assertEqual(result.decision, "review")
        self.assertIn("residency_restriction_unparsed", result.review_reasons)

    def test_an_unreadable_place_is_still_unreadable(self):
        result = self._assess("You must reside in the Tri-Valley corridor.")
        self.assertEqual(result.decision, "review")
        self.assertIn("residency_restriction_unparsed", result.review_reasons)


class BareRemoteWithoutUsScopeTests(unittest.TestCase):
    """A work MODE with no country behind it is not a US-remote match.

    A European employer's posting scored us_remote because its entire location
    field was the word "remote". "Remote" says how the work is done; it asserts no
    geography, and a foreign board writes it exactly as a US one does.
    """

    POLICY = {"metro": ["springfield"], "allow_us_remote": True,
              "us_only": True, "require_match": True}

    def test_bare_remote_with_no_us_signal_anywhere_is_review(self):
        result = assess_location(
            "remote", self.POLICY, title="Travel Consultant",
            description="Join our agency team; we are growing fast.")
        self.assertEqual(result.decision, "review")
        self.assertIn("remote_without_us_scope", result.review_reasons)
        self.assertNotEqual(result.category, "us_remote")

    def test_a_us_signal_in_the_location_still_matches(self):
        for raw in ("Remote - US", "Remote (US)", "Remote, United States",
                    "Remote - Texas"):
            with self.subTest(raw=raw):
                result = assess_location(raw, self.POLICY,
                                         description="This is a remote role.")
                self.assertEqual(result.decision, "match")
                self.assertEqual(result.category, "us_remote")

    def test_a_us_signal_in_the_jd_body_still_matches(self):
        result = assess_location(
            "Remote", self.POLICY,
            description="This is a fully remote role open to candidates "
                        "anywhere in the United States.")
        self.assertEqual(result.decision, "match")
        self.assertEqual(result.category, "us_remote")

    def test_unrestricted_scope_words_keep_their_us_reading(self):
        # "Anywhere" / "Worldwide" name a scope that necessarily includes the US;
        # only the mode-only words lost their free pass.
        for raw in ("Anywhere", "Worldwide"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    assess_location(raw, self.POLICY).category, "us_remote")


class PolicyFlagIndependenceTests(unittest.TestCase):
    """`require_match` and `us_only` gate two DIFFERENT categories.

    The decision cascade used to read them conjoined — a single
    ``not require_match and not us_only`` branch — which made
    ``require_match: false`` a no-op for any policy that also set
    ``us_only: true``. That is exactly what both shipped search profiles set
    (``profiles/example.yaml``, ``profiles/_TEMPLATE.yaml``), so the documented
    "false = keep all US + remote, boost preferred" behaviour never happened and
    every non-preferred US city was dropped as ``no_match`` before review.

    The full 2x2 is pinned here because three of the four cells must NOT move:
    only ``require_match: false`` + ``us_only: true`` (the shipped profile) was
    wrong.
    """

    BASE = {
        "metro": ["san francisco", "new york", "boston", "austin"],
        "allow_us_remote": True,
    }
    OTHER_US = "Chicago, IL"
    FOREIGN = "Berlin, Germany"
    METRO = "San Francisco, CA"
    US_REMOTE = "Remote - US"

    def _decision(self, raw, *, require_match, us_only):
        return assess_location(
            raw,
            {**self.BASE, "require_match": require_match, "us_only": us_only},
        ).decision

    def test_shipped_profile_flags_keep_non_preferred_us_cities(self):
        """require_match: false + us_only: true — the shipped profile.

        This is the cell the conjunction broke: these are US cities, the policy
        does not hard-filter to preferred metros, and they must survive to the
        review queue rather than being dropped.
        """
        for raw in ("Chicago, IL", "Bellevue, WA", "Manhattan, NY",
                    "Denver, CO", "Seattle, WA", "Pittsburgh, PA",
                    "Raleigh, NC", "Miami, FL"):
            with self.subTest(raw=raw):
                result = assess_location(
                    raw, {**self.BASE, "require_match": False,
                          "us_only": True})
                self.assertEqual(result.category, "other_us")
                self.assertEqual(result.decision, "match")

    def test_shipped_profile_flags_still_drop_foreign(self):
        """us_only: true keeps doing its job when require_match is false.

        The point of splitting the flags is that relaxing the US-city filter
        must not also open the border.
        """
        for raw in ("Berlin, Germany", "London, United Kingdom",
                    "Toronto, Canada"):
            with self.subTest(raw=raw):
                result = assess_location(
                    raw, {**self.BASE, "require_match": False,
                          "us_only": True})
                self.assertEqual(result.category, "foreign")
                self.assertEqual(result.decision, "no_match")

    def test_require_match_true_still_hard_filters_us_cities(self):
        for us_only in (True, False):
            with self.subTest(us_only=us_only):
                self.assertEqual(
                    self._decision(self.OTHER_US, require_match=True,
                                   us_only=us_only),
                    "no_match")

    def test_both_flags_false_keeps_foreign_unchanged(self):
        """The pending decision's default path: change no default value.

        `message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md`
        is open, and its default path is "change nothing". Both flags false has
        always KEPT foreign postings, and this fix must not quietly narrow that
        while the owner is still deciding. Pinned so a later edit cannot move it
        silently.
        """
        for raw in ("Berlin, Germany", "London, United Kingdom",
                    "Toronto, Canada", "Singapore"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    self._decision(raw, require_match=False, us_only=False),
                    "match")

    def test_both_flags_false_keeps_us_cities(self):
        self.assertEqual(
            self._decision(self.OTHER_US, require_match=False, us_only=False),
            "match")

    def test_preferred_metro_and_us_remote_match_under_every_combination(self):
        for require_match in (True, False):
            for us_only in (True, False):
                for raw in (self.METRO, self.US_REMOTE):
                    with self.subTest(raw=raw, require_match=require_match,
                                      us_only=us_only):
                        self.assertEqual(
                            self._decision(raw, require_match=require_match,
                                           us_only=us_only),
                            "match")

    def test_us_only_alone_governs_foreign(self):
        """us_only: false admits foreign geography whatever require_match says.

        `require_match` is the preferred-metro/US-city filter; it carries no
        opinion about the border, so it cannot re-impose a US-only rule the
        policy has switched off.
        """
        self.assertEqual(
            self._decision(self.FOREIGN, require_match=True, us_only=False),
            "match")

    def test_an_unclassifiable_location_is_still_reviewed(self):
        """Splitting the flags must not turn `unknown` into a silent match.

        Only `other_us` and `foreign` moved out of the permissive catch-all; a
        location nothing could classify still has to reach a human.
        """
        result = assess_location(
            "", {**self.BASE, "require_match": True, "us_only": True})
        self.assertEqual(result.decision, "review")


class NegatedRemoteFieldTests(unittest.TestCase):
    """A remote field label whose VALUE is "No" is not a remote grant.

    Boards emit the workplace mode as a labelled field. `jd_remote_role` matched
    the "Remote Position" half of "Remote Position: No" and read an office-bound
    role as remote — the label is worded identically to a genuine grant, so only
    the value can tell them apart.
    """

    def test_negated_remote_field_is_not_remote_evidence(self):
        for text in ("Remote Position: No", "Remote: No", "Remote? No",
                     "Fully Remote: No", "Remote Role - No",
                     "Remote Position: None"):
            with self.subTest(text=text):
                self.assertEqual(_remote_rule_hits(text), [])

    def test_affirmative_remote_field_is_still_remote_evidence(self):
        self.assertIn("jd_remote_role",
                      _remote_rule_hits("Remote Position: Yes"))

    def test_ordinary_remote_prose_is_unaffected(self):
        self.assertIn("jd_remote_role",
                      _remote_rule_hits("This is a remote position."))

    def test_a_sentence_ending_before_no_is_not_a_negated_field(self):
        """The guard requires a field SEPARATOR, not merely a nearby "No".

        "...a fully remote role. No prior experience needed." is a remote grant
        followed by an unrelated sentence; a looser guard would silently discard
        it.
        """
        hits = _remote_rule_hits(
            "This is a fully remote role. No prior experience needed.")
        self.assertIn("jd_fully_remote", hits)

    def test_a_negated_label_does_not_suppress_a_real_grant_elsewhere(self):
        hits = _remote_rule_hits(
            "Remote Position: No\n\nHowever, this is a remote position for "
            "our support team.")
        self.assertIn("jd_remote_role", hits)

    def test_negated_remote_label_does_not_classify_the_role_remote(self):
        """End to end, not just the rule table."""
        result = assess_location(
            "Chicago, IL",
            {"metro": ["san francisco"], "allow_us_remote": True,
             "us_only": True, "require_match": True},
            description="Remote Position: No\nYou will join our Chicago team.",
        )
        self.assertNotEqual(result.workplace, "remote")
        self.assertNotIn("jd_remote_role", result.evidence)


class OnsiteVocabularyTests(unittest.TestCase):
    """Onsite phrasings the rule table did not carry.

    `jd_onsite_required` needs a requirement verb or a day count nearby, so an
    absolute ("100% onsite") or a structured field ("Position Role Type:
    Onsite") produced no workplace evidence at all and the posting read as
    having an unstated work mode.
    """

    def test_absolute_onsite_phrasings_are_recognized(self):
        for text in ("This role is 100% onsite.",
                     "This role is 100% on-site.",
                     "This is a fully onsite position.",
                     "The position is fully on-site.",
                     "This role is entirely in-office.",
                     "Work is 100 % in person."):
            with self.subTest(text=text):
                self.assertIn("jd_onsite_absolute", _onsite_rule_hits(text))

    def test_structured_onsite_fields_are_recognized(self):
        for text in ("Position Role Type: Onsite",
                     "Work Setting: In-office",
                     "Role Type: On-Site",
                     "Work Arrangement: In Office",
                     "Workplace Type - Onsite"):
            with self.subTest(text=text):
                self.assertIn("jd_onsite_field", _onsite_rule_hits(text))

    def test_a_negated_absolute_onsite_is_not_an_onsite_obligation(self):
        """The existing negation guard now covers the new absolute rule too."""
        self.assertNotIn(
            "jd_onsite_absolute",
            _onsite_rule_hits("This role is not 100% onsite."))

    def test_a_remote_field_value_does_not_fire_the_onsite_field_rule(self):
        self.assertEqual(_onsite_rule_hits("Work Setting: Remote"), [])

    def test_structured_onsite_field_drives_the_workplace_assessment(self):
        result = assess_location(
            "Chicago, IL",
            {"metro": ["san francisco"], "allow_us_remote": True,
             "us_only": True, "require_match": True},
            description="Position Role Type: Onsite\nYou will join our team.",
        )
        self.assertEqual(result.workplace, "onsite")


class WorkFromHomeVocabularyTests(unittest.TestCase):
    """"work from home" / "WFH" are remote grants too.

    The table carried only the ADVERB form ("work remotely"), so a JD whose only
    statement was "Work From Home 100% of the time" was not recognized as remote
    at all.
    """

    def test_work_from_home_phrasings_are_recognized(self):
        for text in ("Work From Home 100% of the time.",
                     "This role is WFH.",
                     "You may work from home.",
                     "The engineer works from home full time.",
                     "Working from home is supported."):
            with self.subTest(text=text):
                self.assertIn("jd_work_from_home", _remote_rule_hits(text))

    def test_a_work_from_home_perk_is_not_a_remote_grant(self):
        """A benefits line describes a stipend, not where the job is done."""
        for text in ("Benefits include a work from home stipend.",
                     "We offer a WFH allowance and a learning budget.",
                     "Perks: work from home equipment."):
            with self.subTest(text=text):
                self.assertEqual(_remote_rule_hits(text), [])

    def test_work_from_home_with_us_scope_classifies_us_remote(self):
        result = assess_location(
            "Remote",
            {"metro": ["san francisco"], "allow_us_remote": True,
             "us_only": True, "require_match": True},
            description="You will work from home 100% of the time, anywhere "
                        "in the United States.",
        )
        self.assertEqual(result.category, "us_remote")
        self.assertEqual(result.decision, "match")


if __name__ == "__main__":
    unittest.main()
