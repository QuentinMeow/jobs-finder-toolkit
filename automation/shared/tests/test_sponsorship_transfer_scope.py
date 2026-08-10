"""A denial scoped to NEW petitions, in a posting that welcomes transfers.

"We are unable to sponsor new H-1B petitions; H-1B transfer candidates are
encouraged to apply" is one sentence that says both things, and the classifier
read only the first half: `no_match`/`unlikely`/high, dropped under BOTH visa
policies with an empty `review_reasons`. A posting addressed to exactly this
candidate, deleted without a trace.

The repair is the move `memory/decisions/sponsorship-an-unsettled-denial-is-
review-not-a-silent-drop.md` settled for the quantifier ambiguity, applied to a
different one: the EVIDENCE layer keeps the denial and only the VERDICT layer's
confidence changes. So this suite is written around one property above all — no
promotion is reachable — and then the two bounds that keep the demotion narrow.

Every sentence is fictional.

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
    _SPONSOR_NEW_PETITION_RE,
    _SPONSOR_TRANSFER_FRIENDLY_RE,
    assess_sponsorship,
)

TRANSFER_WELCOME = " H-1B transfer candidates are encouraged to apply."


class NewPetitionScopeTests(unittest.TestCase):

    def test_a_new_petition_denial_beside_a_transfer_welcome_is_unsettled(self):
        for text in (
            "We are unable to sponsor new H-1B petitions;" + TRANSFER_WELCOME,
            "We do not sponsor initial H-1B petitions. Candidates who can "
            "transfer their H-1B are welcome.",
            "This role cannot sponsor cap-subject H-1B petitions; we are "
            "cap-exempt for transfers.",
            "We will not sponsor first-time petitions." + TRANSFER_WELCOME,
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["decision"], "review")
                self.assertEqual(assessment["verdict"], "unknown")
                self.assertEqual(assessment["confidence"], "low")

    def test_the_denial_is_kept_as_evidence_not_deleted(self):
        """The evidence layer's half of the split: the denial never leaves.

        Anything that removes it from the ``denial`` list dissolves the
        `denial + positive -> review` conflict branch, which is a two-step
        promotion — the exact failure the quantifier rule was rewritten to stop.
        """
        assessment = assess_sponsorship(
            "We are unable to sponsor new H-1B petitions;" + TRANSFER_WELCOME)
        self.assertEqual(assessment["evidence"], ["unsettled: unable to sponsor"])
        self.assertEqual(assessment["rule_ids"],
                         ["sponsorship.unsettled_denial.unable to sponsor"])

    def test_no_promotion_is_reachable_through_this_pattern(self):
        """The invariant, asserted over the shapes most likely to break it."""
        for text in (
            "We are unable to sponsor new H-1B petitions;" + TRANSFER_WELCOME,
            "We are cap-exempt. We cannot sponsor new H-1B petitions.",
            "H-1B transfers are welcome. We do not sponsor initial petitions "
            "and do not sponsor new petitions.",
            "Transfer your H-1B to us. We will not sponsor new petitions.",
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertNotEqual(assessment["decision"], "match")
                self.assertNotEqual(assessment["verdict"], "likely")

    def test_a_settled_denial_elsewhere_still_wins_outright(self):
        assessment = assess_sponsorship(
            "We are unable to sponsor new H-1B petitions. This role does not "
            "offer sponsorship." + TRANSFER_WELCOME)
        self.assertEqual(assessment["decision"], "no_match")
        self.assertEqual(assessment["confidence"], "high")

    def test_the_reason_names_the_ambiguity_it_found(self):
        assessment = assess_sponsorship(
            "We are unable to sponsor new H-1B petitions;" + TRANSFER_WELCOME)
        self.assertIn("NEW petitions", assessment["reason"])
        quantified = assess_sponsorship("We do not sponsor all roles.")
        self.assertIn("quantifier", quantified["reason"])


class NewPetitionScopeBoundsTests(unittest.TestCase):
    """Both halves are required, and each is a separate bound."""

    def test_without_a_transfer_signal_the_denial_stands(self):
        for text in (
            "We are unable to sponsor new H-1B petitions for this position.",
            "We do not sponsor initial H-1B petitions.",
            "This role cannot sponsor cap-subject H-1B petitions.",
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["decision"], "no_match")
                self.assertEqual(assessment["confidence"], "high")

    def test_a_denial_not_scoped_to_petitions_stands(self):
        for text in (
            "We do not offer sponsorship of any kind. Please do not ask about "
            "transferring your H-1B.",
            "We cannot sponsor visas." + TRANSFER_WELCOME,
            "Sponsorship is not available for this role." + TRANSFER_WELCOME,
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["decision"], "no_match")
                self.assertEqual(assessment["confidence"], "high")

    def test_new_hires_is_not_a_new_petition_scope(self):
        """The petition noun is load-bearing, and this is why.

        "for new hires" is a flat refusal that happens to contain "new". A bare
        new/initial cue would demote it, which is the same class of mistake as
        reading a collective "all" as a distributive one.
        """
        for text in (
            "We are unable to sponsor visas for new hires. H-1B transfer "
            "candidates should not apply.",
            "We do not sponsor visas for new employees; transfer your H-1B "
            "elsewhere.",
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["decision"], "no_match")
                self.assertEqual(assessment["confidence"], "high")

    def test_the_petition_pattern_requires_a_petition_noun(self):
        for text in ("new hires", "initial screening", "new team members"):
            with self.subTest(text):
                self.assertIsNone(_SPONSOR_NEW_PETITION_RE.search(text))
        for text in ("new h-1b petitions", "initial petition",
                     "cap-subject filings", "first-time cases"):
            with self.subTest(text):
                self.assertIsNotNone(_SPONSOR_NEW_PETITION_RE.search(text))

    def test_the_petition_scope_does_not_cross_a_sentence_break(self):
        """A petition noun in the NEXT sentence does not bound this denial."""
        assessment = assess_sponsorship(
            "We do not sponsor visas. New petitions are handled by our "
            "immigration team." + TRANSFER_WELCOME)
        self.assertEqual(assessment["decision"], "no_match")

    def test_the_transfer_signal_matches_the_wordings_a_posting_uses(self):
        for text in ("h-1b transfer candidates", "h1b transfers welcome",
                     "transfer your h-1b", "transfer their h-1b",
                     "transferring an existing visa", "we are cap-exempt"):
            with self.subTest(text):
                self.assertIsNotNone(_SPONSOR_TRANSFER_FRIENDLY_RE.search(text))

    def test_the_transfer_signal_is_not_a_generic_transfer_word(self):
        for text in ("internal transfers between teams are common",
                     "you will transfer data between regions",
                     "transfer learning experience is a plus"):
            with self.subTest(text):
                self.assertIsNone(_SPONSOR_TRANSFER_FRIENDLY_RE.search(text))


if __name__ == "__main__":
    unittest.main()
