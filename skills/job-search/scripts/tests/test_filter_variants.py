"""Deterministic corpus and snapshot-audit tests (no network)."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
for path in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from filter_variants import (  # noqa: E402
    audit_postings,
    check_corpus,
    first_reject_census,
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

    def test_unfilled_ats_template_is_dropped_before_title_gate(self):
        # Decision (e): Gate 0 (quality) runs BEFORE title, mirroring production
        # (posting_quality_ok -> title_ok). A template whose placeholder title
        # would otherwise also fail the title gate must show up as a quality
        # rejection, never generate a downstream title/location variant.
        corpus = load_corpus()
        postings = [{
            "source": "greenhouse",
            "company": "Example Telecom",
            "title": "<Job Title>",
            "url": "https://example.test/jobs/template",
            "location": "Remote (US)",
            "remote": "remote",
            "description": (
                "<Job Title> at Example Telecom. Insert the job title here. "
                "Insert the job title here. Insert the job title here."
            ),
        }]
        self.assertEqual(audit_postings(postings, PROFILE, corpus), [])


class FirstRejectCensusTests(unittest.TestCase):
    """Decision 3b: the audit reports a first-reject census + bounded samples
    rather than silently skipping every hard `no_match` (as `audit_postings`
    does by design for its own review-only purpose)."""

    def test_census_counts_by_first_rule_family_in_gate_order(self):
        postings = [
            {  # quality: unfilled ATS template -> rejected at Gate 0
                "source": "greenhouse", "company": "Example Telecom",
                "title": "<Job Title>",
                "url": "https://example.test/jobs/template-1",
                "location": "Remote (US)",
                "description": (
                    "<Job Title> at Example Telecom. Insert the job title here. "
                    "Insert the job title here. Insert the job title here."
                ),
            },
            {  # title: definite non-technical occupation -> rejected at Gate 1
                "source": "greenhouse", "company": "Example Corp",
                "title": "Senior Technical Recruiter",
                "url": "https://example.test/jobs/recruiter-1",
                "location": "Remote (US)",
                "description": "Own full-cycle recruiting for engineering teams.",
            },
            {  # a second recruiter posting -> same family, count accumulates
                "source": "greenhouse", "company": "Example Corp",
                "title": "Technical Recruiter II",
                "url": "https://example.test/jobs/recruiter-2",
                "location": "Remote (US)",
                "description": "Own full-cycle recruiting for engineering teams.",
            },
            {  # a clean match -> never counted in the census
                "source": "greenhouse", "company": "Example Corp",
                "title": "Platform Engineer",
                "url": "https://example.test/jobs/clean-1",
                "location": "Springfield, US",
                "description": "Build reliable platform services.",
            },
        ]
        report = first_reject_census(postings, PROFILE, sample_size=5)
        self.assertEqual(report["total_rejected"], 3)
        families = {row["family"]: row for row in report["families"]}
        self.assertEqual(
            families["quality:quality.placeholder_title"]["count"], 1)
        self.assertEqual(
            families["title:title.nontechnical_occupation"]["count"], 2)
        # Sample rows carry an excerpt/URL for false-negative recall checks.
        sample = families["title:title.nontechnical_occupation"]["sample"]
        self.assertEqual(len(sample), 2)
        self.assertIn("url", sample[0])

    def test_sample_is_bounded_and_deterministic(self):
        postings = [{
            "source": "greenhouse", "company": "Example Corp",
            "title": f"Technical Recruiter {i}",
            "url": f"https://example.test/jobs/recruiter-{i}",
            "location": "Remote (US)",
            "description": "Own full-cycle recruiting for engineering teams.",
        } for i in range(8)]
        report_a = first_reject_census(postings, PROFILE, sample_size=3)
        report_b = first_reject_census(list(reversed(postings)), PROFILE,
                                        sample_size=3)
        family = "title:title.nontechnical_occupation"
        row_a = next(r for r in report_a["families"] if r["family"] == family)
        row_b = next(r for r in report_b["families"] if r["family"] == family)
        self.assertEqual(row_a["count"], 8)
        self.assertEqual(len(row_a["sample"]), 3)          # bounded
        self.assertEqual(row_a["sample"], row_b["sample"])  # order-independent

    def test_location_family_names_the_reject_category_not_hint_evidence(self):
        postings = [
            {
                "source": "ashby", "company": "Example Corp",
                "title": "Platform Engineer",
                "url": "https://example.test/jobs/other-us",
                "location": "Austin, TX",
                "remote": "onsite",
                "description": "This is an onsite role.",
            },
            {
                "source": "ashby", "company": "Example Corp",
                "title": "Platform Engineer",
                "url": "https://example.test/jobs/foreign",
                "location": "Toronto, Canada",
                "remote": "hybrid",
                "description": "This is a hybrid role.",
            },
        ]
        report = first_reject_census(postings, PROFILE, sample_size=5)
        families = {row["family"] for row in report["families"]}
        self.assertEqual(families, {"location:other_us", "location:foreign"})

    def test_date_gate_precedes_location_in_the_census(self):
        postings = [{
            "source": "ashby", "company": "Example Corp",
            "title": "Platform Engineer",
            "url": "https://example.test/jobs/stale-foreign",
            "location": "Toronto, Canada",
            "posted_at": "2026-07-10T00:00:00Z",
            "description": "Build platform services.",
        }]
        report = first_reject_census(
            postings, PROFILE, sample_size=5, max_age=7,
            now=datetime(2026, 7, 22, tzinfo=timezone.utc))
        self.assertEqual(report["families"][0]["family"],
                         "date:older_than_window")

    def test_a_gate_never_double_counts_a_posting_rejected_earlier(self):
        # A quality-template posting that would ALSO fail the title gate must
        # be attributed only to its FIRST reject (quality), never counted
        # again downstream — production drops it before title ever runs.
        postings = [{
            "source": "greenhouse", "company": "Example Telecom",
            "title": "<Job Title>",
            "url": "https://example.test/jobs/template-2",
            "location": "Remote (US)",
            "description": (
                "<Job Title> at Example Telecom. Insert the job title here. "
                "Insert the job title here. Insert the job title here."
            ),
        }]
        report = first_reject_census(postings, PROFILE, sample_size=5)
        self.assertEqual(report["total_rejected"], 1)
        self.assertEqual(len(report["families"]), 1)
        self.assertEqual(report["families"][0]["family"],
                         "quality:quality.placeholder_title")


if __name__ == "__main__":
    unittest.main()
