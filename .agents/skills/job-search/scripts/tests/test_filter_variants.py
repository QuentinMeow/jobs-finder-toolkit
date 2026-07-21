"""Deterministic corpus and snapshot-audit tests (no network)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
for path in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from filter_variants import (  # noqa: E402
    audit_postings,
    check_corpus,
    lint_corpus,
    load_corpus,
    structural_signature,
)
from job_metadata import assess_sponsorship  # noqa: E402

PROFILE = {
    "titles": {"include": ["software engineer", "platform engineer"]},
    "location": {
        "preferred": ["springfield"],
        "allow_remote": True,
        "us_only": True,
        "require_match": True,
    },
}


class FilterVariantCorpusTests(unittest.TestCase):
    def test_corpus_lints_and_matches_current_classifiers(self):
        corpus = load_corpus()
        self.assertEqual(lint_corpus(corpus), [])
        self.assertEqual(check_corpus(corpus), [])

    def test_known_office_or_remote_shape_does_not_need_review(self):
        corpus = load_corpus()
        postings = [{
            "source": "greenhouse",
            "company": "Example Corp",
            "title": "Platform Engineer",
            "url": "https://example.test/jobs/remote",
            "location": "San Francisco, CA • New York, NY • United States",
            "remote": "unknown",
            "description": (
                "This role can be held from one of our US hubs or remotely "
                "in the United States."
            ),
        }]
        self.assertEqual(audit_postings(postings, PROFILE, corpus), [])

    def test_new_signal_bearing_shape_emits_pending_stub(self):
        # Remove one known family to model a newly introduced rule shape. The same
        # posting is clean with the real corpus, but must fail while its fictional
        # label is absent.
        corpus = load_corpus()
        corpus = {
            **corpus,
            "variants": [
                case for case in corpus["variants"]
                if case["id"] != "location-hybrid-tag-vs-jd-remote"
            ],
        }
        postings = [{
            "source": "greenhouse",
            "company": "Example Corp",
            "title": "Software Engineer",
            "url": "https://example.test/jobs/new-shape",
            "location": "Austin, TX (Hybrid)",
            "remote": "unknown",
            "description": "This role is fully remote across the United States.",
        }]
        pending = audit_postings(postings, PROFILE, corpus)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["domain"], "location")
        self.assertIn("label_required", pending[0])

    def test_rejected_title_short_circuits_downstream_variant_noise(self):
        corpus = load_corpus()
        postings = [{
            "source": "greenhouse",
            "company": "Example Corp",
            "title": "Capital Markets Financing Associate",
            "url": "https://example.test/jobs/irrelevant",
            "location": "Hybrid",
            "remote": "remote",
            "description": (
                "This role is fully remote but also requires five office days. "
                "Applicants need 12 years of finance experience. "
                "Visa sponsorship may be discussed."
            ),
        }]
        self.assertEqual(audit_postings(postings, PROFILE, corpus), [])

    def test_known_intentional_review_family_is_not_unlabeled(self):
        corpus = load_corpus()
        postings = [{
            "source": "greenhouse",
            "company": "Example Corp",
            "title": "Software Engineer",
            "url": "https://example.test/jobs/known-review",
            "location": "Hybrid",
            "remote": "unknown",
            "description": "Build reliable distributed services.",
        }]
        self.assertEqual(audit_postings(postings, PROFILE, corpus), [])

    def test_cosmetic_sponsorship_variants_share_one_signature(self):
        # Punctuation- and capitalization-only variants of the same denial must
        # collapse to a single structural signature (grouping, not novelty).
        base = "This role does not offer sponsorship."
        loud = "THIS ROLE DOES NOT OFFER SPONSORSHIP!!!"
        wrapped = (
            "Acme Robotics — Widget Team. This role does not offer sponsorship; "
            "apply at https://acme.example/jobs/42."
        )
        sig = structural_signature(
            "sponsorship", {"text": base}, assess_sponsorship(base))
        self.assertEqual(
            sig,
            structural_signature(
                "sponsorship", {"text": loud}, assess_sponsorship(loud)))
        self.assertEqual(
            sig,
            structural_signature(
                "sponsorship", {"text": wrapped}, assess_sponsorship(wrapped)))

    def test_signatures_do_not_leak_raw_company_title_or_jd_text(self):
        # No literal company/title/URL/JD token appears inside any signature.
        text = (
            "GloboMegaCorp Quantum Widget Team: this role does not offer "
            "sponsorship. See https://globomega.example/reqs/hush-hush-7."
        )
        secrets = [
            "globomegacorp", "quantum", "widget", "globomega.example",
            "hush-hush-7",
        ]
        sig = structural_signature(
            "sponsorship", {"text": text}, assess_sponsorship(text))
        self.assertRegex(sig, r"^[0-9a-f]{16}$")
        for secret in secrets:
            self.assertNotIn(secret, sig)

    def test_untrusted_scraper_remote_hint_is_known_review_family(self):
        corpus = load_corpus()
        postings = [{
            "source": "jobspy:indeed",
            "company": "Example Corp",
            "title": "Software Engineer",
            "url": "https://example.test/jobs/scraper",
            "location": "Austin, TX",
            "remote": "remote",
            "description": "Build backend systems.",
        }]
        self.assertEqual(audit_postings(postings, PROFILE, corpus), [])


if __name__ == "__main__":
    unittest.main()
