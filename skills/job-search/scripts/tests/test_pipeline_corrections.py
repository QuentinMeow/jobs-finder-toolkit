"""Focused production-shaped regressions for the 2026-07-22 pipeline-correction
design (private/message-queue/needs-agent/requests/2026-07-22-opus-job-pipeline-
design-review.md, Decisions 1/3/4 + checklist 3-7). All company/JD text below is
FICTIONAL (Jordan-Rivers-universe placeholders) — no real company or posting
content, per the public-tree leak rule.

Covers:
  - Decision 3a: MTS/generalist -> `title.occupation_ambiguous` review; a
    definite non-technical-occupation lexicon hit -> hard `no_match`; the
    role-noun co-occurrence guard keeps a genuinely ambiguous engineering-
    adjacent title (e.g. "Sales Engineer") OUT of the hard-reject lexicon.
  - Decision 3c: an explicit JD-body level phrase that materially exceeds the
    profile's target band flags `jd_level_conflicts_title` without changing
    the title-derived occupation/level.
  - Decision 4: Ashby's structured per-component compensation parses into
    `JobPosting.salary_range` only with an explicit currency AND period
    (annual-USD case), and a missing-period control leaves it `None`.
  - Decision (e): the posting-quality gate hard-rejects an unfilled ATS
    template (placeholder title + repeated instructional block) and sends a
    JD with only a bare compensation placeholder to review instead.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _path in (_SCRIPTS, _SCRIPTS / "_vendor"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from common import HttpResult, JobPosting  # noqa: E402
from registry import Registry  # noqa: E402
from scoring import (  # noqa: E402
    assess_posting_quality,
    assess_title,
    posting_quality_ok,
    score_posting,
    title_ok,
)
import search_jobs  # noqa: E402
import sources  # noqa: E402


TITLES_CFG = {
    "include": ["software engineer", "platform engineer"],
    "exclude": ["manager", "director"],
    "exclude_neutralize": ["member of technical staff"],
}


class TitleOccupationAmbiguousReviewTests(unittest.TestCase):
    """Decision 3a: a plausible/technical UNKNOWN occupation is a conservative
    review, never a silent hard drop."""

    def test_mts_generalist_title_is_review_not_hard_reject(self):
        assessment = assess_title(
            "Member of Technical Staff, Generalist", TITLES_CFG)
        self.assertEqual(assessment["decision"], "review")
        self.assertIn("title_occupation_ambiguous", assessment["review_reasons"])
        self.assertIn("title.occupation_ambiguous", assessment["rule_ids"])

    def test_title_ok_keeps_the_posting_for_review(self):
        posting = JobPosting(
            source="board", company="Example Corp",
            title="Member of Technical Staff, Generalist",
            url="https://example.test/jobs/mts-generalist")
        self.assertTrue(title_ok(posting, {"titles": TITLES_CFG}))
        self.assertIn("title_occupation_ambiguous", posting.review_reasons)
        self.assertEqual(
            posting.filter_assessments["title"]["decision"], "review")


class TitleNontechnicalRejectTests(unittest.TestCase):
    """Decision 3a: a definite non-technical-occupation lexicon hit (generic,
    evidence-based occupation FAMILY, never a per-title alias) with no
    co-occurring engineering role noun stays a hard no_match."""

    def test_definite_recruiter_title_is_hard_rejected(self):
        assessment = assess_title("Senior Technical Recruiter", TITLES_CFG)
        self.assertEqual(assessment["decision"], "no_match")
        self.assertTrue(any(
            r.startswith("title.nontechnical_occupation.")
            for r in assessment["rule_ids"]))

    def test_title_ok_drops_the_definite_nontechnical_posting(self):
        posting = JobPosting(
            source="board", company="Example Corp",
            title="Senior Technical Recruiter",
            url="https://example.test/jobs/recruiter")
        self.assertFalse(title_ok(posting, {"titles": TITLES_CFG}))

    def test_role_noun_co_occurrence_guard_avoids_a_false_hard_reject(self):
        # "Sales Engineer" hits the "sales" lexicon token AND carries an
        # engineering role noun, so the occupation is genuinely ambiguous, not
        # definite — it must fall through to the normal include/residual
        # logic instead of being hard-rejected by the lexicon alone.
        assessment = assess_title("Sales Engineer", TITLES_CFG)
        self.assertNotEqual(assessment["decision"], "no_match")

    def test_bare_lead_department_title_is_review_not_an_accepted_match(self):
        cfg = {
            **TITLES_CFG,
            "include": [*TITLES_CFG["include"], "infrastructure"],
        }
        assessment = assess_title(
            "Communications Lead, Infrastructure and Engineering", cfg)
        self.assertEqual(assessment["decision"], "review")
        self.assertIn("title_leadership_ambiguous",
                      assessment["review_reasons"])

    def test_new_grad_exclusion_covers_new_college_grad_and_graduate_titles(self):
        cfg = {**TITLES_CFG, "exclude": [*TITLES_CFG["exclude"], "new grad"]}
        for title in (
            "Systems Software Engineer - New College Grad 2026",
            "Graduate Software Engineer, Open Source",
        ):
            with self.subTest(title=title):
                assessment = assess_title(title, cfg)
                self.assertEqual(assessment["decision"], "no_match")
                self.assertIn("title.excluded.new grad", assessment["rule_ids"])


class JDLevelConflictTests(unittest.TestCase):
    """Decision 3c: an explicit JD-body level phrase that materially exceeds
    the target band is flagged for review WITHOUT changing occupation/level."""

    PROFILE = {
        "titles": TITLES_CFG,
        "seniority": {"target": ["mid"]},
    }

    def test_staff_level_jd_body_conflicts_with_mid_level_title_search(self):
        posting = JobPosting(
            source="board", company="Example Data Corp",
            title="Software Engineer",
            url="https://example.test/jobs/jd-staff-conflict",
            description=(
                "Join our data platform team. We are looking for a Staff "
                "Software Engineer to own our distributed query engine. "
                "This role partners closely with product and SRE."
            ))
        posting.job_level = {"normalized": "mid", "min": 4.0, "max": 4.8,
                             "confidence": "medium", "source": "title"}
        score_posting(posting, self.PROFILE)
        self.assertIn("jd_level_conflicts_title", posting.review_reasons)
        # Occupation/title-derived level is untouched by the conflict flag.
        self.assertEqual(posting.job_level["normalized"], "mid")

    def test_no_conflict_when_jd_body_has_no_explicit_level_phrase(self):
        posting = JobPosting(
            source="board", company="Example Data Corp", title="Software Engineer",
            url="https://example.test/jobs/jd-no-conflict",
            description="Join our data platform team building reliable services.")
        posting.job_level = {"normalized": "mid", "min": 4.0, "max": 4.8,
                             "confidence": "medium", "source": "title"}
        score_posting(posting, self.PROFILE)
        self.assertNotIn("jd_level_conflicts_title", posting.review_reasons)

    def test_no_conflict_when_jd_body_level_is_within_the_target_band(self):
        # A JD-body level phrase that is IN-band (mid-target, mid-level JD
        # phrase) must never spuriously flag a conflict.
        profile = {"titles": TITLES_CFG, "seniority": {"target": ["staff"]}}
        posting = JobPosting(
            source="board", company="Example Data Corp", title="Software Engineer",
            url="https://example.test/jobs/jd-staff-target",
            description=(
                "Join our data platform team. We are looking for a Staff "
                "Software Engineer to own our distributed query engine."
            ))
        posting.job_level = {"normalized": "unknown", "min": None, "max": None,
                             "confidence": "unknown", "source": "generic"}
        score_posting(posting, profile)
        self.assertNotIn("jd_level_conflicts_title", posting.review_reasons)


class AshbyCompensationParsingTests(unittest.TestCase):
    """Decision 4: parse Ashby's structured compensation into
    JobPosting.salary_range only with explicit currency AND period."""

    def setUp(self):
        self._orig_http = sources.http_get_full
        self._prior_data_root = os.environ.get("JOBHUNT_DATA_ROOT")
        self._data_root = Path(tempfile.mkdtemp(prefix="pipeline-correction-test-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self._data_root)
        sources.capture_hooks._reset_for_tests()

    def tearDown(self):
        sources.http_get_full = self._orig_http
        if self._prior_data_root is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior_data_root
        sources.capture_hooks._reset_for_tests()
        shutil.rmtree(self._data_root, ignore_errors=True)

    def _fetch_one(self, compensation):
        payload = {"apiVersion": "1", "jobs": [{
            "id": "ax-1", "title": "Platform Engineer",
            "location": "Remote (US)",
            "jobUrl": "https://jobs.ashbyhq.com/examplecorp/ax-1",
            "descriptionPlain": "Do platform work.",
            "publishedAt": "2026-07-11T00:00:00Z", "isListed": True,
            "workplaceType": "Remote", "secondaryLocations": [],
            "compensation": compensation,
        }]}
        body = json.dumps(payload).encode()
        sources.http_get_full = lambda *a, **k: HttpResult(
            url="https://example.test/x", status=200, body=body,
            headers={"content-type": "application/json"}, duration_ms=1,
            ok=True, error=None, method="GET", content_type="application/json")
        postings = sources.fetch_ashby("ExampleCorp", "examplecorp")
        self.assertEqual(len(postings), 1)
        return postings[0]

    def test_annual_usd_component_parses_into_salary_range(self):
        posting = self._fetch_one({"summaryComponents": [{
            "compensationType": "Salary",
            "minValue": 150000, "maxValue": 210000,
            "currencyCode": "USD", "interval": "1 YEAR",
        }]})
        self.assertEqual(posting.salary_range, {
            "min": 150000, "max": 210000, "currency": "USD", "period": "year",
            "source": "ashby_api",
            "provenance": {
                "tier": "market_benchmark", "provider": "ashby_api",
                "confidence": "medium", "method": "structured_source_field",
            },
        })

    def test_tier_component_fallback_parses_when_summary_is_absent(self):
        posting = self._fetch_one({"compensationTiers": [{"components": [{
            "compensationType": "Salary",
            "minValue": 160000, "maxValue": 220000,
            "currencyCode": "USD", "interval": "1 YEAR",
        }]}]})
        self.assertEqual(posting.salary_range["min"], 160000)
        self.assertEqual(posting.salary_range["max"], 220000)
        self.assertEqual(posting.salary_range["period"], "year")

    def test_missing_interval_is_a_negative_control_salary_range_stays_none(self):
        # No explicit period -> never invented; salary_range stays None even
        # though currency + bounds are present.
        posting = self._fetch_one({"summaryComponents": [{
            "compensationType": "Salary",
            "minValue": 150000, "maxValue": 210000,
            "currencyCode": "USD", "interval": None,
        }]})
        self.assertIsNone(posting.salary_range)

    def test_missing_currency_is_also_a_negative_control(self):
        posting = self._fetch_one({"summaryComponents": [{
            "compensationType": "Salary",
            "minValue": 150000, "maxValue": 210000,
            "currencyCode": None, "interval": "1 YEAR",
        }]})
        self.assertIsNone(posting.salary_range)

    def test_bonus_component_is_never_read_as_salary(self):
        posting = self._fetch_one({"summaryComponents": [{
            "compensationType": "Bonus",
            "minValue": 10000, "maxValue": 20000,
            "currencyCode": "USD", "interval": "1 YEAR",
        }]})
        self.assertIsNone(posting.salary_range)

    def test_no_compensation_block_leaves_salary_range_none(self):
        posting = self._fetch_one(None)
        self.assertIsNone(posting.salary_range)


class PostingQualityGateTests(unittest.TestCase):
    """Decision (e): an unfilled ATS template must never be accepted as a
    real match. Fictional "template" posting, standing in for the live
    unfilled-Ashby-template shape reported in the design review."""

    TEMPLATE_TITLE = "<Job Title>"
    TEMPLATE_DESCRIPTION = (
        "<Job Title> at Example Telecom. Insert the job title here. "
        "Insert the job title here. Insert the job title here."
    )

    def test_unfilled_template_is_hard_rejected(self):
        assessment = assess_posting_quality(
            self.TEMPLATE_TITLE, self.TEMPLATE_DESCRIPTION)
        self.assertEqual(assessment["decision"], "no_match")
        self.assertIn("quality.placeholder_title", assessment["rule_ids"])

    def test_posting_quality_ok_drops_the_template_posting(self):
        posting = JobPosting(
            source="board", company="Example Telecom", title=self.TEMPLATE_TITLE,
            url="https://example.test/jobs/template",
            description=self.TEMPLATE_DESCRIPTION)
        self.assertFalse(posting_quality_ok(posting))
        self.assertEqual(
            posting.filter_assessments["quality"]["decision"], "no_match")

    def test_bare_compensation_placeholder_alone_is_review_not_hard_reject(self):
        # A single "$XXX,XXX" placeholder in otherwise-real JD prose is weaker
        # evidence than a literal title placeholder or a repeated template
        # block, so it must go to review rather than a silent hard drop.
        posting = JobPosting(
            source="board", company="Example Telecom",
            title="Software Engineer",
            url="https://example.test/jobs/comp-placeholder",
            description=(
                "Join Example Telecom's platform team building reliable "
                "distributed systems. Compensation for this role is "
                "$XXX,XXX depending on experience and location."
            ))
        self.assertTrue(posting_quality_ok(posting))
        self.assertIn("posting_template_placeholder", posting.review_reasons)
        self.assertEqual(
            posting.filter_assessments["quality"]["decision"], "review")

    def test_repeated_boilerplate_alone_is_review_not_hard_reject(self):
        repeated = "Benefits vary by location and applicable local law."
        posting = JobPosting(
            source="board", company="Example Telecom",
            title="Software Engineer",
            url="https://example.test/jobs/repeated-boilerplate",
            description=(
                "Build reliable distributed systems. "
                f"{repeated} {repeated} {repeated}"
            ))
        self.assertTrue(posting_quality_ok(posting))
        self.assertIn("posting_template_placeholder", posting.review_reasons)
        self.assertEqual(
            posting.filter_assessments["quality"]["decision"], "review")

    def test_lorem_ipsum_is_definite_template_content(self):
        assessment = assess_posting_quality(
            "Software Engineer",
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit.")
        self.assertEqual(assessment["decision"], "no_match")
        self.assertIn("quality.placeholder_lorem_ipsum", assessment["rule_ids"])

    def test_a_real_posting_with_a_real_dollar_figure_is_unaffected(self):
        posting = JobPosting(
            source="board", company="Example Telecom",
            title="Software Engineer",
            url="https://example.test/jobs/real-comp",
            description=(
                "Join Example Telecom's platform team. The salary range for "
                "this role is $150,000-$210,000 depending on experience."
            ))
        self.assertTrue(posting_quality_ok(posting))
        self.assertEqual([], posting.review_reasons)
        self.assertEqual(
            posting.filter_assessments["quality"]["decision"], "match")


class OccupationAmbiguousBoundedRolloutTests(unittest.TestCase):
    """Checklist item 3: the `title.occupation_ambiguous` residual is preserved
    for review, but bounded after all other gates and score ordering; overflow is
    counted and surfaced."""

    def _ctx(self):
        return {
            "considered_urls": set(), "considered_pairs": set(),
            "skip_days": 0, "search_tokens": [],
            "ignore_search_log": True, "ai_native_keys": set(),
        }

    def _postings(self, n):
        return [
            JobPosting(
                source="board", company="Example Corp",
                title=f"Member of Technical Staff, Generalist Team {i}",
                url=f"https://example.test/jobs/mts-{i}",
                location="Springfield, US",
                description="Own broad platform generalist work.")
            for i in range(n)
        ]

    NOW = datetime(2026, 7, 22, tzinfo=timezone.utc)

    def test_default_cap_of_300_lets_a_small_batch_through_uncapped(self):
        profile = {"titles": TITLES_CFG}
        postings = self._postings(5)
        _kept, counts = search_jobs.filter_score_rank(
            postings, profile, self._ctx(), max_age=None, top_k=40,
            max_per_company=10, sponsor_index=None, company_levels={},
            registry=Registry([]), now=self.NOW)
        self.assertEqual(counts["n_occupation_ambiguous_overflow"], 0)
        self.assertEqual(counts["n_review"], 5)

    def test_overflow_beyond_a_configured_cap_is_counted_after_scoring(self):
        profile = {"titles": {**TITLES_CFG, "occupation_review_cap": 2}}
        postings = self._postings(5)
        _kept, counts = search_jobs.filter_score_rank(
            postings, profile, self._ctx(), max_age=None, top_k=40,
            max_per_company=10, sponsor_index=None, company_levels={},
            registry=Registry([]), now=self.NOW)
        self.assertEqual(counts["n_review"], 2)                 # capped
        self.assertEqual(counts["n_occupation_ambiguous_overflow"], 3)  # counted
        # The two highest-ranked postings that made it under the cap are enriched.
        self.assertTrue(all(p.job_level for p in counts["review_postings"]))

    def test_irrelevant_early_rows_do_not_consume_the_review_cap(self):
        profile = {
            "titles": {**TITLES_CFG, "occupation_review_cap": 1},
            "location": {
                "preferred": ["Seattle"],
                "allow_remote": True,
                "us_only": True,
                "require_match": True,
            },
        }
        postings = self._postings(3)
        postings[0].location = "London, United Kingdom"
        postings[0].remote = "onsite"
        for posting in postings[1:]:
            posting.location = "Remote, United States"
            posting.remote = "remote"
        _kept, counts = search_jobs.filter_score_rank(
            postings, profile, self._ctx(), max_age=None, top_k=40,
            max_per_company=10, sponsor_index=None, company_levels={},
            registry=Registry([]), now=self.NOW)
        self.assertEqual(counts["n_review"], 1)
        # Only the second matching row overflows; the foreign first row was
        # rejected before the cap was applied and consumed no budget.
        self.assertEqual(counts["n_occupation_ambiguous_overflow"], 1)

    def test_cap_can_be_disabled_via_null(self):
        profile = {"titles": {**TITLES_CFG, "occupation_review_cap": None}}
        postings = self._postings(5)
        _kept, counts = search_jobs.filter_score_rank(
            postings, profile, self._ctx(), max_age=None, top_k=40,
            max_per_company=10, sponsor_index=None, company_levels={},
            registry=Registry([]), now=self.NOW)
        self.assertEqual(counts["n_occupation_ambiguous_overflow"], 0)
        self.assertEqual(counts["n_review"], 5)


if __name__ == "__main__":
    unittest.main()
