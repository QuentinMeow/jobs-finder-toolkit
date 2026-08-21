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
        self.assertIn("unsettled: unable to sponsor", assessment["evidence"])
        self.assertIn("sponsorship.unsettled_denial.unable to sponsor",
                      assessment["rule_ids"])
        # The transfer welcome is now read as the OFFER it is (GH #233/#265), so
        # it appears beside the denial rather than only in the invisible
        # transfer-friendly probe. The denial is still there, which is what this
        # test is for.
        self.assertIn("h-1b transfer", assessment["evidence"])

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
        """Precedence between the two DENIAL readings, with no offer in the way.

        The transfer signal here is phrased so it feeds the petition-scope probe
        WITHOUT matching an offer phrase, which is what isolates this property:
        a flat refusal beside a petition-scoped one settles the posting.
        """
        assessment = assess_sponsorship(
            "We are unable to sponsor new H-1B petitions. This role does not "
            "offer sponsorship. Candidates who can transfer their H-1B may "
            "still write to us.")
        self.assertEqual(assessment["decision"], "no_match")
        self.assertEqual(assessment["confidence"], "high")

    def test_a_settled_denial_beside_a_transfer_offer_is_a_conflict(self):
        """The same posting when the transfer welcome IS an offer phrase.

        "H-1B transfer candidates are encouraged to apply" is a sponsorship
        commitment — a transfer is a petition the employer has to file — and it
        is now read as one (GH #233/#265). A posting that both refuses and
        invites is contradictory on its face, so it lands in the branch this
        module keeps for contradictions: kept, flagged, and NEVER promoted.
        Reading it as a flat refusal is what GH #265 filed: a posting addressed
        to exactly this candidate, deleted under both policies.
        """
        assessment = assess_sponsorship(
            "We are unable to sponsor new H-1B petitions. This role does not "
            "offer sponsorship." + TRANSFER_WELCOME)
        self.assertEqual(assessment["decision"], "review")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertIn("does not offer sponsorship", assessment["evidence"])

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
        """A transfer SIGNAL alone never softens a denial that names no petition.

        The signal has to be inert here — a mention the petition-scope probe
        sees but the offer scan does not — or the demotion under test would be
        the offer/denial conflict rather than the petition scope.
        """
        for text in (
            "We do not offer sponsorship of any kind. Please do not ask about "
            "transferring your H-1B.",
            "We cannot sponsor visas. Do not write to us about transferring "
            "your H-1B.",
            "Sponsorship is not available for this role, including for anyone "
            "hoping to transfer their H-1B.",
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["decision"], "no_match")
                self.assertEqual(assessment["confidence"], "high")

    def test_a_flat_denial_beside_a_transfer_offer_is_never_promoted(self):
        """The same shapes with an explicit transfer OFFER beside the refusal.

        These postings contradict themselves, so they are kept and flagged
        rather than dropped — but the denial stays in the evidence and the
        verdict may never reach ``match``/``likely``. That invariant is what
        makes the extra recall safe.
        """
        for text in (
            "We cannot sponsor visas." + TRANSFER_WELCOME,
            "Sponsorship is not available for this role." + TRANSFER_WELCOME,
        ):
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["decision"], "review")
                self.assertNotEqual(assessment["verdict"], "likely")
                self.assertTrue(
                    [rule for rule in assessment["rule_ids"]
                     if rule.startswith("sponsorship.negative.")
                     or rule.startswith("sponsorship.negated_offer.")],
                    assessment["rule_ids"])

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
        """A petition noun in the NEXT sentence does not bound this denial.

        The transfer signal is again written so it is inert to the offer scan,
        which keeps this row measuring the petition scope and nothing else.
        """
        assessment = assess_sponsorship(
            "We do not sponsor visas. New petitions are handled by our "
            "immigration team. Do not write about transferring your H-1B.")
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
