"""Denial shapes written as patterns, and the tripwires that bound them.

Four wordings reached the candidate as `review`/`unknown` with empty evidence —
the JD refused sponsorship in writing and the shortlist reported silence. They
cannot be phrases, because each carries an optional segment ("cannot CURRENTLY
sponsor", "without the need for CURRENT OR FUTURE sponsorship") and enumerating
the variants is how a phrase list reaches 67 entries without covering the next
wording.

These are the first rules in this module that can CREATE a denial from a wording
no list contains, and a denial drops the posting under both visa policies. So
every rule is tested from both sides: the shape it is for, and the shape one
character away from it that must stay untouched. Every sentence is fictional.

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
    _SPONSOR_GENERIC_DENIALS,
    _SPONSOR_NEGATIVE,
    _SPONSOR_PATTERN_RULES,
    _SPONSOR_POSITIVE,
    _bounded_phrase_matches,
    _bounded_word_set,
    _sponsor_pattern_denials,
    assess_sponsorship,
)


def _denial(testcase, text, *, label=None):
    assessment = assess_sponsorship(text)
    testcase.assertEqual(assessment["decision"], "no_match", text)
    testcase.assertEqual(assessment["verdict"], "unlikely", text)
    testcase.assertEqual(assessment["confidence"], "high", text)
    if label is not None:
        testcase.assertIn(label, assessment["evidence"], text)


def _not_a_denial(testcase, text):
    assessment = assess_sponsorship(text)
    testcase.assertNotEqual(assessment["decision"], "no_match", text)
    testcase.assertNotEqual(assessment["verdict"], "unlikely", text)


class SponsorPatternRuleShapeTests(unittest.TestCase):
    """Properties of the rule objects themselves, not of any one wording."""

    def test_every_rule_gate_is_its_own_anchor(self):
        """The gate cannot disagree with the pattern: one string builds both."""
        for rule in _SPONSOR_PATTERN_RULES:
            with self.subTest(rule.label):
                self.assertEqual(len(rule.words), 1)
                anchor = next(iter(rule.words))
                self.assertRegex(anchor, r"\A[a-z0-9]+\Z")
                self.assertIn(anchor, rule.pattern.pattern)

    def test_a_multi_word_anchor_is_refused(self):
        """An anchor that is not one word run would break the gate's proof."""
        rule_type = type(_SPONSOR_PATTERN_RULES[0])
        with self.assertRaises(ValueError):
            rule_type("bad", r"", "green card", r"")

    def test_rule_labels_are_unique_and_do_not_collide_with_phrases(self):
        labels = [rule.label for rule in _SPONSOR_PATTERN_RULES]
        self.assertEqual(len(labels), len(set(labels)))
        listed = set(_SPONSOR_NEGATIVE) | set(_SPONSOR_POSITIVE)
        self.assertEqual(listed.intersection(labels), set())

    def test_the_bare_verb_rule_is_the_only_gated_one(self):
        """Only a rule whose "sponsor" is a bare verb needs immigration context.

        Every other rule names sponsorship, a visa, or citizenship outright,
        where the object IS the thing — gating those turns real refusals into
        silence, which is the mistake the phrase side already made once.
        """
        gated = {rule.label for rule in _SPONSOR_PATTERN_RULES if rule.generic}
        self.assertEqual(gated, {"negated coordinated sponsor verb"})
        self.assertTrue(gated <= _SPONSOR_GENERIC_DENIALS)

    def test_every_rule_is_a_fallback_behind_the_phrase_lists(self):
        """A wording the tuples already answer keeps its existing path.

        The off-list denial rule had to learn this the hard way: a rule that
        fires over a listed phrase steals its rule ids.
        """
        text = "citizenship is required for this position."
        words = _bounded_word_set(text)
        covered = [
            (match.start(), match.end())
            for _phrase, match in _bounded_phrase_matches(
                text, _SPONSOR_NEGATIVE, words=words)
        ]
        self.assertTrue(covered)
        self.assertEqual(list(_sponsor_pattern_denials(text, covered, words)), [])
        # ... and with nothing covered, the rule DOES see it — so the emptiness
        # above is the fallback working, not the pattern failing to match.
        self.assertTrue(list(_sponsor_pattern_denials(text, [], words)))

    def test_the_word_gate_never_hides_a_rule_from_its_own_shape(self):
        for rule, text in zip(_SPONSOR_PATTERN_RULES, (
            "we cannot currently sponsor or support visa transfers.",
            "authorized to work without the need for visa sponsorship.",
            "we are not currently sponsoring employment-based visas.",
            "citizenship required: yes",
            "u.s. citizen: required",
            "applicants for this role must be u.s. citizens.",
            "visa: gc/citizens",
        )):
            with self.subTest(rule.label):
                gated = list(_sponsor_pattern_denials(
                    text, [], _bounded_word_set(text)))
                ungated = list(_sponsor_pattern_denials(text, [], None))
                self.assertEqual([label for label, _m in gated],
                                 [label for label, _m in ungated])
                self.assertIn(rule.label, [label for label, _m in gated])


class CoordinatedSponsorVerbTests(unittest.TestCase):
    """"cannot currently sponsor or support visa transfers"."""

    def test_the_adverb_no_longer_hides_the_denial(self):
        _denial(self, "We cannot currently sponsor or support visa transfers.",
                label="negated coordinated sponsor verb")

    def test_other_cues_and_second_verbs_read_the_same_way(self):
        for text in (
            "We are not able to sponsor or provide visa transfers.",
            "This team will not sponsor nor support work visas.",
            "We do not presently sponsor or facilitate immigration transfers.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_a_non_immigration_sponsee_is_still_not_a_denial(self):
        """The bare verb keeps the immigration gate the phrase side has."""
        for text in (
            "We do not sponsor or support local charities.",
            "We cannot currently sponsor or support community sports teams.",
        ):
            with self.subTest(text):
                _not_a_denial(self, text)

    def test_the_shape_without_the_adverb_keeps_its_existing_path(self):
        """Already answered by the "cannot sponsor" phrase; the rule stands off."""
        assessment = assess_sponsorship(
            "This team cannot sponsor or support visa transfers.")
        self.assertEqual(assessment["evidence"], ["cannot sponsor"])


class SponsorshipStatedAsUnnecessaryTests(unittest.TestCase):
    """"authorized to work without the need for ... sponsorship"."""

    def test_the_requirement_is_read_as_the_refusal_it_is(self):
        for text in (
            "Applicants must be authorized to work in the U.S. without the "
            "need for current or future visa sponsorship.",
            "Candidates must be authorized to work without the need for "
            "employer sponsorship now or at any time in the future.",
            "You must be able to work without need for immigration sponsorship.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_eeo_copy_naming_the_same_words_is_not_a_denial(self):
        """"who NEED visa sponsorship" is the opposite polarity of "WITHOUT the
        need for visa sponsorship", and one word separates them."""
        _not_a_denial(
            self,
            "We do not discriminate against candidates who need visa sponsorship.")

    def test_a_stated_need_for_sponsorship_is_not_a_denial(self):
        _not_a_denial(
            self,
            "Tell us in your application whether you will need visa sponsorship.")


class NotSponsoringVisasTests(unittest.TestCase):
    """"not currently sponsoring employment-based visas"."""

    def test_the_gerund_form_is_a_denial(self):
        for text in (
            "We are not currently sponsoring employment-based visas.",
            "We are not sponsoring employment-based visas in the foreseeable "
            "future.",
            "This company is not sponsoring work visas at this time.",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_the_positive_form_is_untouched(self):
        """The negation lives in the pattern, so an offer cannot reach it."""
        assessment = assess_sponsorship(
            "We are open to sponsoring an employment-based visa for this role.")
        self.assertEqual(assessment["decision"], "match")
        self.assertEqual(assessment["verdict"], "likely")


class CitizenshipRequirementFieldTests(unittest.TestCase):
    """Q/A rows and table cells, which are not sentences at all."""

    def test_a_required_citizenship_field_is_a_denial(self):
        for text in (
            "Citizenship required: Yes",
            "U.S. Citizenship Required? Yes",
            "Citizenship: required",
            "US Citizenship required",
            "U.S. citizen: required",
        ):
            with self.subTest(text):
                _denial(self, text)

    def test_the_opposite_answer_is_not_a_denial(self):
        for text in (
            "Citizenship required: No",
            "Citizenship required? No",
            "Citizenship required: N/A",
            "Citizenship is not required for this role.",
            "US citizenship is not required.",
        ):
            with self.subTest(text):
                _not_a_denial(self, text)

    def test_citizenship_named_without_a_requirement_is_not_a_denial(self):
        for text in (
            "We consider all applicants regardless of citizenship or national "
            "origin.",
            "Citizenship or work authorization documents are verified after an "
            "offer.",
        ):
            with self.subTest(text):
                _not_a_denial(self, text)

    def test_the_two_field_rules_do_not_double_report_one_field(self):
        """``\\bcitizen\\b`` cannot reach inside "citizenship"."""
        assessment = assess_sponsorship("Citizenship required: Yes")
        self.assertEqual(assessment["evidence"],
                         ["citizenship stated as required"])


class VisaStatusFieldTests(unittest.TestCase):
    """"Visa: GC/Citizens" — and the version that also offers H-1B."""

    def test_a_citizens_only_visa_field_is_a_denial(self):
        for text in (
            "Visa: GC/Citizens",
            "Visa: Green Card, US Citizens",
            "Visa: Permanent Residents & Citizens",
        ):
            with self.subTest(text):
                _denial(self, text, label="visa field limited to citizens")

    def test_a_field_already_answered_by_a_phrase_keeps_that_answer(self):
        """"Visa: Citizens/GC only" contains the listed phrase "gc only".

        Still a denial — through the path it always used. The fallback rule
        standing off is the point.
        """
        assessment = assess_sponsorship("Visa: Citizens/GC only")
        self.assertEqual(assessment["decision"], "no_match")
        self.assertEqual(assessment["evidence"], ["gc only"])

    def test_a_field_that_also_lists_a_visa_is_not_a_denial(self):
        """The value list must be EXHAUSTED by citizen/green-card terms.

        The trailing position matters as much as the leading one: without a word
        boundary after each status term, ``citizens?`` matches "citizen" inside
        "Citizens" and strands an "s" that ends the list early, so
        "Visa: GC/Citizens/H-1B" graded a confident denial while offering H-1B.
        """
        for text in (
            "Visa: H-1B, OPT, GC, Citizens",
            "Visa: GC/Citizens/H-1B",
            "Visa: Citizens, GC, H1B transfer",
            "Visa: GC/Citizens/OPT",
        ):
            with self.subTest(text):
                _not_a_denial(self, text)

    def test_an_unrelated_visa_field_is_not_a_denial(self):
        for text in (
            "Visa: sponsorship available",
            "Visa: all statuses considered",
        ):
            with self.subTest(text):
                _not_a_denial(self, text)


class PatternDenialsDoNotPromoteTests(unittest.TestCase):
    """No new rule may move a posting toward an OFFER.

    Every rule here produces a DENIAL, and a denial preempts every branch that
    can reach ``match``/``likely``. This asserts the property directly rather
    than trusting the shape of the code, because the one invariant five passes
    over this classifier kept was "a change here never promotes".
    """

    def test_a_new_denial_beside_an_offer_is_a_conflict_not_an_offer(self):
        assessment = assess_sponsorship(
            "Visa sponsorship is available for some roles. We cannot currently "
            "sponsor or support visa transfers.")
        self.assertEqual(assessment["decision"], "review")
        self.assertEqual(assessment["verdict"], "unknown")

    def test_a_settled_phrase_denial_still_wins_outright(self):
        assessment = assess_sponsorship(
            "Citizenship required: Yes. This role does not offer sponsorship.")
        self.assertEqual(assessment["decision"], "no_match")
        self.assertEqual(assessment["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
