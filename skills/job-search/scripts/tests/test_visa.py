"""Tests for the visa-sponsorship heuristic and the --visa-policy binding.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests
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


class NegatedOfferTests(unittest.TestCase):
    """A denial that contains an offer substring must not score 'yes'.

    Every sentence is fictional. Each used to return ``yes`` because the denial
    wording was not in the phrase list while an offer substring inside it was.
    """

    CASES = (
        "This role does not currently offer visa sponsorship.",
        "We will not consider applicants for employment immigration sponsorship "
        "or support for this position.",
        "Must be eligible to work in the United States; no H1-B visa "
        "sponsorship available.",
        "We are not able to offer visa sponsorship for this position at this time.",
    )

    def test_negated_offers_score_no(self):
        for text in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(classify_visa(text)[0], "no")

    def test_double_negative_is_unclear(self):
        self.assertEqual(
            classify_visa("It is not true that we cannot sponsor work visas.")[0],
            "unclear",
        )

    def test_export_control_boilerplate_is_unclear_not_no(self):
        # Export-licensing language is not an immigration denial. Under the
        # default exclude_negative policy a "no" here would drop the posting.
        self.assertEqual(
            classify_visa(
                "Candidates must be eligible to obtain the required "
                "authorizations without sponsorship for an export license.")[0],
            "unclear",
        )

    def test_work_authorization_boilerplate_is_unclear(self):
        self.assertEqual(
            classify_visa(
                "Applicants must be authorized to work in the United States.")[0],
            "unclear",
        )

    def test_genuine_offer_after_an_unrelated_negation_is_yes(self):
        self.assertEqual(
            classify_visa(
                "There is no relocation budget, and visa sponsorship is "
                "available for this role.")[0],
            "yes",
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

    def test_require_positive_drops_a_negated_offer(self):
        # The reported defect end to end: the strictest policy, chosen by someone
        # who needs sponsorship, used to return this posting as an explicit offer.
        profile = {"visa": {"needs_sponsorship": True, "policy": "require_positive"}}
        denial = self._posting(
            "This role does not currently offer visa sponsorship.")
        self.assertFalse(visa_ok(denial, profile))
        self.assertEqual(denial.visa_label, "no")

    def test_require_positive_never_presents_a_quantified_denial_as_an_offer(self):
        # The regression this pins, end to end. A quantifier inside the DENIAL
        # ("for all new hires") was read as a limit on an offer, which deleted the
        # denial; the JD's unrelated positive phrase was then unopposed, so the
        # posting came back `yes`/likely with no review flag — an employer that
        # refuses sponsorship in writing, recommended to the one candidate who
        # cannot take the job. Fictional wording.
        profile = {"visa": {"needs_sponsorship": True, "policy": "require_positive"}}
        posting = self._posting(
            "We offer green card sponsorship to existing employees after two "
            "years. We are unable to sponsor visas for all new hires.")
        visa_ok(posting, profile)
        self.assertNotEqual(posting.visa_label, "yes")
        self.assertEqual(posting.sponsorship, "unknown")
        self.assertIn("sponsorship_requires_review", posting.review_reasons)

    def test_require_positive_never_drops_a_quantified_denial_silently(self):
        # The mirror, and the reason this pair is one test file rather than two.
        # With nothing positive beside it the same sentence used to be a confident
        # `no` — dropped under both policies, unflagged — even though the
        # quantifier that made it a denial is the one the comment above calls
        # ambiguous. An employer whose offer is worded outside the phrase list
        # ("our immigration team supports H-1B and green card cases") was deleted
        # from the shortlist with no trace. Both policies now keep it and flag it.
        for policy in ("exclude_negative", "require_positive"):
            for text in (
                "We are unable to sponsor visas for all new hires.",
                "Our immigration team supports H-1B and green card cases, but "
                "we do not sponsor all roles.",
            ):
                with self.subTest(policy=policy, text=text):
                    profile = {"visa": {"needs_sponsorship": True,
                                        "policy": policy}}
                    posting = self._posting(text)
                    self.assertTrue(visa_ok(posting, profile))
                    self.assertEqual(posting.visa_label, "unclear")
                    self.assertIn("sponsorship_requires_review",
                                  posting.review_reasons)

    def test_a_settled_denial_is_still_dropped_under_both_policies(self):
        # The guard: unsettling a quantified denial must not make the classifier
        # soft on the refusals it can actually read.
        for policy in ("exclude_negative", "require_positive"):
            for text in (
                "We are unable to sponsor visas.",
                "We cannot sponsor visas at all for this position.",
                "We are unable to sponsor visas for all new hires. This role "
                "does not offer sponsorship.",
            ):
                with self.subTest(policy=policy, text=text):
                    profile = {"visa": {"needs_sponsorship": True,
                                        "policy": policy}}
                    posting = self._posting(text)
                    self.assertFalse(visa_ok(posting, profile))
                    self.assertEqual(posting.visa_label, "no")

    def test_a_non_immigration_sponsor_is_never_dropped_as_a_denial(self):
        # The false-denial shape end to end. `do not sponsor` carried no
        # immigration-context gate, so a sentence about a street fair graded a
        # confident refusal and the default policy DELETED the posting.
        for policy in ("exclude_negative", "require_positive"):
            with self.subTest(policy=policy):
                profile = {"visa": {"needs_sponsorship": True, "policy": policy}}
                posting = self._posting("We do not sponsor community events.")
                self.assertTrue(visa_ok(posting, profile))
                self.assertEqual(posting.visa_label, "unclear")
                self.assertIn("sponsorship_requires_review",
                              posting.review_reasons)

    def test_a_denial_naming_sponsorship_itself_is_still_dropped(self):
        # The tripwire: this sentence carries no immigration word either, and a
        # symmetric gate would turn a real refusal into `unclear`.
        for policy in ("exclude_negative", "require_positive"):
            with self.subTest(policy=policy):
                profile = {"visa": {"needs_sponsorship": True, "policy": policy}}
                posting = self._posting("This role does not offer sponsorship.")
                self.assertFalse(visa_ok(posting, profile))
                self.assertEqual(posting.visa_label, "no")

    def test_an_off_list_denial_is_dropped_under_both_policies(self):
        # Detection, end to end. The denial matched no phrase in either list, so
        # the posting reached the candidate as if sponsorship were merely
        # unstated. Fictional wording.
        for policy in ("exclude_negative", "require_positive"):
            with self.subTest(policy=policy):
                profile = {"visa": {"needs_sponsorship": True, "policy": policy}}
                posting = self._posting(
                    "We do not offer relocation or visa sponsorship.")
                self.assertFalse(visa_ok(posting, profile))
                self.assertEqual(posting.visa_label, "no")

    def test_eeo_copy_is_never_dropped_as_a_denial(self):
        # The misfire the tight window and the offer-verb requirement exist to
        # prevent: this sentence is the OPPOSITE of a denial, and reading it as
        # one would delete an employer that sponsors.
        for policy in ("exclude_negative", "require_positive"):
            with self.subTest(policy=policy):
                profile = {"visa": {"needs_sponsorship": True, "policy": policy}}
                posting = self._posting(
                    "We do not discriminate against candidates who need visa "
                    "sponsorship.")
                self.assertTrue(visa_ok(posting, profile))
                self.assertEqual(posting.visa_label, "unclear")

    def test_require_positive_never_presents_an_unreachable_cue_as_an_offer(self):
        # The high-severity reproduction end to end. The clause break inside the
        # parenthetical cut `unable` out of the offer phrase's scope, and an
        # unreachable cue used to leave the phrase scored as an explicit OFFER —
        # so the strictest policy returned a posting that refuses sponsorship in
        # writing, with no review flag on it. Fictional wording.
        profile = {"visa": {"needs_sponsorship": True, "policy": "require_positive"}}
        posting = self._posting(
            "We are unable, given current headcount constraints and the "
            "timeline for this particular opening, to offer visa sponsorship.")
        visa_ok(posting, profile)
        self.assertNotEqual(posting.visa_label, "yes")
        self.assertEqual(posting.sponsorship, "unknown")
        self.assertIn("sponsorship_requires_review", posting.review_reasons)

    def test_an_unreachable_cue_is_kept_and_flagged_under_both_policies(self):
        # The mirror: an unreadable sentence is not a refusal either, so neither
        # policy may drop it silently.
        for policy in ("exclude_negative", "require_positive"):
            with self.subTest(policy=policy):
                profile = {"visa": {"needs_sponsorship": True, "policy": policy}}
                posting = self._posting(
                    "We are unable, given current headcount constraints and "
                    "the timeline for this particular opening, to offer visa "
                    "sponsorship.")
                self.assertTrue(visa_ok(posting, profile))
                self.assertEqual(posting.visa_label, "unclear")
                self.assertIn("sponsorship_requires_review",
                              posting.review_reasons)

    def test_require_positive_still_keeps_an_offer_with_a_distributive_limit(self):
        # The counterpart: an employer that sponsors but not universally is still
        # a sponsor, and the strict policy must still surface it.
        profile = {"visa": {"needs_sponsorship": True, "policy": "require_positive"}}
        posting = self._posting(
            "Visa sponsorship: we do sponsor visas. That said, we are not able "
            "to sponsor visas for every role and every candidate.")
        self.assertTrue(visa_ok(posting, profile))
        self.assertEqual(posting.visa_label, "yes")

    def test_default_policy_keeps_an_export_control_posting(self):
        # exclude_negative drops denials, so mislabelling export-licensing
        # boilerplate as a denial removed these postings entirely.
        profile = {"visa": {"needs_sponsorship": True}}
        posting = self._posting(
            "Candidates must be eligible to obtain the required authorizations "
            "without sponsorship for an export license.")
        self.assertTrue(visa_ok(posting, profile))
        self.assertEqual(posting.visa_label, "unclear")
        self.assertIn("sponsorship_requires_review", posting.review_reasons)

    def test_a_new_petition_denial_beside_a_transfer_welcome_is_kept_and_flagged(self):
        # GH #265, end to end and in the direction that costs a real job. The JD
        # says both things in one sentence — no NEW petitions, transfers welcome
        # — and the classifier read only the first half: dropped under BOTH
        # policies with an EMPTY review_reasons, so the posting vanished with no
        # trace, from the one candidate it was addressed to. The transfer half
        # was not even hard to see: `visa_tags` on this same text already
        # returns `h1b_transfer_friendly`. Fictional wording.
        for policy in ("exclude_negative", "require_positive"):
            with self.subTest(policy=policy):
                profile = {"visa": {"needs_sponsorship": True, "policy": policy}}
                posting = self._posting(
                    "We are unable to sponsor new H-1B petitions; H-1B transfer "
                    "candidates are encouraged to apply.")
                self.assertIn("h1b_transfer_friendly",
                              visa_tags(posting.description))
                self.assertTrue(visa_ok(posting, profile))
                self.assertEqual(posting.visa_label, "unclear")
                self.assertEqual(posting.sponsorship, "unknown")
                self.assertIn("sponsorship_requires_review",
                              posting.review_reasons)

    def test_a_new_petition_denial_is_never_promoted_to_an_offer(self):
        # The invariant every pass over this classifier has kept: a demotion may
        # withdraw confidence, never create an offer. `require_positive` is the
        # policy that would surface one.
        profile = {"visa": {"needs_sponsorship": True, "policy": "require_positive"}}
        posting = self._posting(
            "We are unable to sponsor new H-1B petitions; H-1B transfer "
            "candidates are encouraged to apply.")
        visa_ok(posting, profile)
        self.assertNotEqual(posting.visa_label, "yes")
        self.assertNotEqual(posting.sponsorship, "likely")

    def test_a_denial_that_is_not_scoped_to_new_petitions_is_still_dropped(self):
        # Half the rule is the OTHER half. A flat refusal beside a transfer
        # mention is still a flat refusal, under both policies.
        for policy in ("exclude_negative", "require_positive"):
            with self.subTest(policy=policy):
                profile = {"visa": {"needs_sponsorship": True, "policy": policy}}
                posting = self._posting(
                    "We do not offer sponsorship of any kind. Please do not ask "
                    "about transferring your H-1B.")
                self.assertFalse(visa_ok(posting, profile))
                self.assertEqual(posting.visa_label, "no")


if __name__ == "__main__":
    unittest.main()
