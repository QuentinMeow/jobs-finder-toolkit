"""Negation that sits AFTER the sponsorship head, and the bounds around it.

THE DEFECT. Every negation rule in `job_metadata` read backward from the
sponsorship phrase, because that is where an English negation usually sits. But
the head noun's own PREDICATE comes after it, and a JD writes the refusal there:

    H-1B sponsorship is unavailable.      -> match / likely / HIGH
    H-1B sponsorship is not offered.      -> match / likely / HIGH
    Green card sponsorship is unavailable.-> match / likely / HIGH

Through `scoring.visa_ok` with `needs_sponsorship: true`, under BOTH policies,
those came back `kept=True label=yes review_reasons=[]`. An employer stating in
writing that it does not sponsor, recommended without a flag to the one candidate
who cannot take the job. That is the most expensive answer this module can give,
and nothing under it caught the shape.

WHY IT IS EASY TO REOPEN. A forward rule is one relative clause away from
inventing denials out of real offers — "sponsorship is available for candidates
WHO ARE NOT yet authorized to work here" is an OFFER — so every guardrail below
is paired with the shape it must not touch. Every sentence is fictional.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/shared/tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from job_metadata import (  # noqa: E402
    _SPONSOR_NEGATION_CUE_RE,
    _sponsor_forward_negation,
    assess_sponsorship,
    classify_sponsorship,
)


def _denial(testcase, text):
    assessment = assess_sponsorship(text)
    testcase.assertEqual(assessment["decision"], "no_match", text)
    testcase.assertEqual(assessment["verdict"], "unlikely", text)
    testcase.assertEqual(assessment["confidence"], "high", text)
    testcase.assertTrue(assessment["evidence"], text)


def _offer(testcase, text):
    assessment = assess_sponsorship(text)
    testcase.assertEqual(assessment["decision"], "match", text)
    testcase.assertEqual(assessment["verdict"], "likely", text)
    testcase.assertEqual(assessment["confidence"], "high", text)


def _review(testcase, text):
    assessment = assess_sponsorship(text)
    testcase.assertEqual(assessment["decision"], "review", text)
    testcase.assertEqual(assessment["verdict"], "unknown", text)


class ReportedShapeTests(unittest.TestCase):
    """The exact sentences that reproduced, in the exact wording they used."""

    REPORTED = (
        "H-1B sponsorship is unavailable.",
        "H-1B sponsorship is not offered.",
        "Green card sponsorship is unavailable.",
        "Immigration sponsorship is not offered for this role.",
    )

    def test_the_reported_sentences_are_denials(self):
        for text in self.REPORTED:
            with self.subTest(text):
                _denial(self, text)

    def test_they_are_never_reported_as_offers(self):
        """The property that matters even if the confidence rules move later."""
        for text in self.REPORTED:
            with self.subTest(text):
                self.assertNotEqual(classify_sponsorship(text), "likely")


class ForwardCueCoverageTests(unittest.TestCase):
    """The cue vocabulary a refusal actually uses, on the head's own predicate."""

    def test_each_required_cue_reaches_the_head(self):
        for text in (
            "Visa sponsorship is unavailable for this role.",
            "Visa sponsorship is not offered for this position.",
            "Visa sponsorship is not available at this time.",
            "Visa sponsorship is not provided.",
            "Employment-visa sponsorship is unavailable through this employer.",
            "Sponsorship for this position is never offered.",
            "Sponsorship is no longer offered for new hires.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_unavailable_is_a_negation_cue(self):
        """Its negation is a PREFIX, so no separate 'not' exists to be found."""
        self.assertTrue(_SPONSOR_NEGATION_CUE_RE.search("sponsorship is unavailable"))

    def test_the_cue_forms_that_precede_the_head_still_work(self):
        """The backward direction is untouched by any of this."""
        for text in (
            "We do not offer visa sponsorship.",
            "We cannot offer visa sponsorship.",
            "We no longer offer visa sponsorship.",
            "We are unable to sponsor visas.",
            "All roles require work authorization without sponsorship.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_a_field_row_writes_its_predicate_after_a_separator(self):
        """"Visa sponsorship: not available" is a row, not a sentence."""
        for text in ("Visa sponsorship: not available.",
                     "Sponsorship - none.",
                     "Visa sponsorship: no."):
            with self.subTest(text):
                _denial(self, text)


class ForwardScopeBoundsTests(unittest.TestCase):
    """Each bound, and the shape one character outside it."""

    def test_a_relative_clause_does_not_negate_the_head(self):
        """The bound a forward-only rule cannot do without.

        "not" here modifies the CANDIDATES, not the sponsorship, and the
        relative pronoun is the only thing that says so. Without this break the
        clearest offer wording a sponsoring employer writes becomes a refusal.
        """
        for text in (
            "H-1B sponsorship is available for candidates who are not "
            "currently authorized to work in the United States.",
            "Visa sponsorship is available for engineers who cannot obtain a "
            "green card yet.",
        ):
            with self.subTest(text):
                _offer(self, text)

    def test_a_coordinated_second_statement_does_not_reach_back(self):
        """The second sentence is why the expletive "there" is a break forward.

        The shared break set recognizes a coordinated clause by its SUBJECT and
        lists referring expressions only, so "and there is ..." read as part of
        the sponsorship predicate and demoted an unambiguous offer to `review`.
        """
        for text in (
            "We offer visa sponsorship and do not require prior US work "
            "experience.",
            "Visa sponsorship is available, and there is no relocation budget.",
            "Visa sponsorship is available; relocation is not covered.",
        ):
            with self.subTest(text):
                _offer(self, text)

    def test_a_coordinated_noun_phrase_is_not_a_new_clause(self):
        """...and the shape that keeps that break from becoming a loophole.

        "for research and engineering roles" coordinates a NOUN, not a clause,
        so the refusal after it is still the head's own predicate. It lands
        `review` rather than `match`: the adjacency test refuses to assert a
        denial across a coordinator, but nothing here is evidence of an offer.
        """
        _review(self, "H-1B sponsorship for research and engineering roles is "
                      "not offered.")

    def test_a_sentence_break_ends_the_forward_scope(self):
        _offer(self, "We sponsor visas for this role. We do not offer "
                     "relocation assistance.")

    def test_a_contrastive_conjunction_ends_it_too(self):
        _offer(self, "Visa sponsorship is available for this role, though "
                     "sponsorship is not guaranteed.")

    def test_a_cue_the_budget_refuses_lands_review_not_offer(self):
        """The unsafe-direction backstop, and why the rule is a two-step.

        A single strict test would have left this scored as an explicit OFFER;
        a single loose one would turn the coordinated sentences above into
        refusals. `review` is kept and flagged, so it costs neither.
        """
        _review(self, "H-1B sponsorship for engineering roles based in our "
                      "Austin, Texas office is not offered.")

    def test_the_helper_reports_the_three_readings(self):
        self.assertEqual(
            _sponsor_forward_negation("visa sponsorship is unavailable", 17),
            "reachable")
        self.assertIsNone(
            _sponsor_forward_negation("visa sponsorship is available", 17))


class ForwardNegationMeetsTheQuantifierLayersTests(unittest.TestCase):
    """A forward denial is graded by the SAME readings as a backward one.

    Skipping these would make the quantifier rules mean one thing on the left of
    the head and another on the right, which is how this module's earlier
    revisions each reopened the direction the previous one closed.
    """

    def test_a_distributive_quantifier_still_limits_scope(self):
        _offer(self, "Visa sponsorship is available; it is not offered for "
                     "every opening.")

    def test_an_ambiguous_quantifier_still_withholds_confidence(self):
        assessment = assess_sponsorship("Sponsorship is not offered for all "
                                        "contract roles.")
        self.assertNotEqual(assessment["confidence"], "high")
        self.assertNotEqual(assessment["verdict"], "likely")


class UsPersonRequirementTests(unittest.TestCase):
    """GH #238: who may hold the job, written as a sentence rather than a field."""

    def test_a_status_list_stated_as_a_requirement_is_a_denial(self):
        for text in (
            "Applicants for this role must be U.S. citizens.",
            "The successful candidate must establish U.S. Citizen, National, "
            "Lawful Permanent Resident, Refugee, or Asylee status.",
            "Candidates must hold a green card or U.S. citizenship.",
            "Engineers must be lawful permanent residents for this customer.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_eeo_copy_is_never_a_requirement(self):
        for text in (
            "We are an equal opportunity employer and do not discriminate on "
            "the basis of citizenship or national origin.",
            "All qualified applicants receive consideration without regard to "
            "national origin.",
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertNotEqual(assessment["decision"], "no_match", text)

    def test_an_inclusive_status_list_is_not_a_bar(self):
        """GH #265's shape: the same nouns, offered rather than required."""
        assessment = assess_sponsorship(
            "U.S. Citizens, Green Card Holders, EAD Holders, and H-1B transfer "
            "candidates are encouraged to apply.")
        self.assertNotEqual(assessment["decision"], "no_match")

    def test_a_work_authorization_escape_defuses_the_bar(self):
        """An H-1B holder IS authorized to work, so this is not a US-person bar."""
        assessment = assess_sponsorship(
            "Candidates must be U.S. citizens or otherwise authorized to work "
            "in the United States.")
        self.assertNotEqual(assessment["decision"], "no_match")


class ConditionalOfferTests(unittest.TestCase):
    """GH #304: an undecided offer is not a settled one."""

    def test_a_fronted_condition_makes_the_offer_unknown(self):
        for text in (
            "If approved by counsel, the company will sponsor H-1B candidates.",
            "Once legal signs off, we provide immigration support.",
            "Subject to internal approval, we sponsor work visas for this role.",
            "Provided that a business need is established, we will sponsor visas.",
        ):
            with self.subTest(text):
                _review(self, text)

    def test_an_ordinary_fronted_clause_leaves_the_offer_alone(self):
        """The bound: the subordinator alone is not a condition on the offer."""
        _offer(self, "If you are interested in this role, we offer visa "
                     "sponsorship.")

    def test_a_frequency_hedge_is_a_hedge(self):
        _review(self, "We cannot promise sponsorship, though we sometimes "
                      "sponsor H-1B transfers.")


class ExportControlSenseTests(unittest.TestCase):
    """GH #286 (visa half): the second sense belongs to one word only."""

    def test_export_licensing_still_neutralizes_a_sponsorship_word(self):
        assessment = assess_sponsorship(
            "Candidates must be eligible to obtain the required authorizations "
            "without sponsorship for an export license.")
        self.assertEqual(assessment["decision"], "review")

    def test_a_citizenship_bar_keeps_its_meaning_inside_export_control_copy(self):
        """A status bar has no second legal sense to be confused with.

        Gating it too suppressed the only evidence a firmware posting carried,
        and the row became final match #1 for a candidate who needs H-1B.
        """
        _denial(self, "Applicants must be a U.S. citizen, lawful permanent "
                      "resident, or protected individual, and must be eligible "
                      "for a security clearance under the International Traffic "
                      "in Arms Regulations (ITAR).")


class SignalPresenceTests(unittest.TestCase):
    """`signal_present` gates the review flag, so silence there is a silent drop."""

    def test_evidence_without_a_sponsorship_word_still_counts_as_signal(self):
        assessment = assess_sponsorship("US citizens only.")
        self.assertTrue(assessment["rule_ids"])
        self.assertTrue(assessment["signal_present"])

    def test_a_posting_that_says_nothing_reports_no_signal(self):
        assessment = assess_sponsorship("Build reliable backend services.")
        self.assertEqual(assessment["rule_ids"], [])
        self.assertFalse(assessment["signal_present"])


class OfferRecallTests(unittest.TestCase):
    """GH #233 / #304: offers the phrase lists could not see."""

    def test_the_copula_and_transfer_forms_are_offers(self):
        for text in (
            "We support H-1B transfers for qualified candidates.",
            "H-1B transfer candidates are encouraged to apply.",
            "Sponsorship is available to applicants requiring H-1B status.",
            "We provide successful candidates with immigration assistance.",
            "We are open to sponsoring employment-based visas.",
            "The employer will sponsor successful applicants for employment "
            "visas.",
        ):
            with self.subTest(text):
                _offer(self, text)

    def test_the_same_wordings_negated_are_denials(self):
        """Added recall must not become a new way to miss a refusal."""
        for text in (
            "We do not support H-1B transfers.",
            "Sponsorship is not available to applicants requiring H-1B status.",
            "Successful applicants will receive no immigration assistance from "
            "the employer.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_a_bare_sponsorship_offer_without_immigration_context_stays_unknown(self):
        """The deliberate limit on the #233 repair.

        "Sponsorship is available." with no immigration word anywhere is the
        same wording a conference-booth or employee-program sentence uses, so it
        earns a positive only with immigration context in the window — exactly
        the rule its contiguous twin "sponsorship available" already follows.
        """
        _review(self, "Sponsorship is available.")


class DenialRelationTests(unittest.TestCase):
    """GH #304: the relation between the negation and the head is not one verb."""

    def test_synonyms_of_the_offer_verb_reach_the_head(self):
        for text in (
            "The organization is unable to arrange work-visa sponsorship.",
            "This employer does not arrange or fund visa sponsorship.",
            "We will never fund or arrange employment-visa sponsorship.",
            "This employer has no program for visa sponsorship.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_need_and_require_are_not_offer_relations(self):
        """The tripwire: they invert the relation, and EEO copy uses them."""
        for text in (
            "We do not discriminate against candidates who need visa "
            "sponsorship.",
            "We do not require that candidates hold visa sponsorship already.",
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertNotEqual(assessment["decision"], "no_match", text)


if __name__ == "__main__":
    unittest.main()
