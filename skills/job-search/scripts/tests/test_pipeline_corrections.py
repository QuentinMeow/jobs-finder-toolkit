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
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parents[1]
for _path in (_SCRIPTS, _SCRIPTS / "_vendor"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from common import HttpResult, JobPosting  # noqa: E402
from registry import Registry  # noqa: E402
import scoring  # noqa: E402
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


class LexiconVersusProfileIncludeTests(unittest.TestCase):
    """The generic occupation lexicon must not hard-drop a title the profile names.

    The lexicon fires on a title with no engineering role NOUN, and it cannot tell
    an occupation ("Clinical Nurse") from an application VERTICAL ("Clinical
    Imaging" — the product area at every health-AI employer). Decision 3a's rule is
    that only a DEFINITE non-match is a hard drop; a profile include term matching
    the same title makes it ambiguous, so it goes to review instead.
    """

    CFG = {
        "include": ["machine learning", "ml", "applied scientist",
                    "research scientist", "infrastructure"],
        "exclude": ["manager", "director"],
    }

    def test_a_research_title_in_a_lexicon_vertical_is_not_hard_dropped(self):
        for title in ("Machine Learning Scientist, Clinical Imaging",
                      "Applied Scientist, Marketing Science",
                      "Research Scientist, Legal Reasoning"):
            with self.subTest(title=title):
                assessment = assess_title(title, self.CFG)
                self.assertNotEqual(assessment["decision"], "no_match")
                self.assertFalse([r for r in assessment["rule_ids"]
                                  if r.startswith("title.nontechnical_occupation.")])
                posting = JobPosting(source="board", company="Example Corp",
                                     title=title, url="https://example.test/j")
                self.assertTrue(title_ok(posting, {"titles": self.CFG}))

    def test_the_lexicon_still_hard_drops_a_non_research_occupation(self):
        for title in ("Clinical Research Coordinator",
                      "Marketing Partnerships Lead",
                      "Senior Technical Recruiter",
                      "Capital Markets Infrastructure Financing Associate"):
            with self.subTest(title=title):
                self.assertEqual(assess_title(title, self.CFG)["decision"],
                                 "no_match")

    def test_an_unrelated_research_title_reaches_review_never_a_match(self):
        self.assertEqual(assess_title("Environmental Scientist", self.CFG)["decision"],
                         "review")


class ProfileIncludeOutranksTheOccupationLexiconTests(unittest.TestCase):
    """#232: the generic occupation lexicon ran BEFORE `titles.include`.

    The lexicon encodes what a default SOFTWARE search does not want. A profile's
    own `titles.include` encodes what THIS search does want, and it is the more
    specific statement — so a candidate whose profile says
    ``include: [account executive]`` was still losing every account-executive
    posting to ``title.nontechnical_occupation.sales``. Verified broken across
    sales, finance, customer success, clinical, design and recruiting profiles:
    not one explicit include phrase survived.

    The fix is deliberately NARROW: only a CLEAN include match skips the lexicon.
    A title matched solely by a BROAD DOMAIN token (``infrastructure``,
    ``platform``, ``compute``) still faces it, because such a token names a
    technical AREA, not an occupation — see
    `BroadDomainOnlyIncludeStillFacesTheLexiconTests` below, which pins the eight
    real finance/legal/comms shapes that the wide form of this rule wrongly
    rescued.
    """

    SALES = {"include": ["account executive", "sales executive",
                         "business development representative"],
             "exclude": ["manager", "director", "vp", "intern"]}
    CLINICAL = {"include": ["clinical research associate"],
                "exclude": ["director", "vp"]}
    RECRUITING = {"include": ["technical recruiter"], "exclude": ["director", "vp"]}

    def test_an_explicitly_included_sales_title_is_a_match(self):
        for title in ("Account Executive", "Enterprise Account Executive",
                      "Sales Executive", "Business Development Representative"):
            with self.subTest(title=title):
                assessment = assess_title(title, self.SALES)
                self.assertEqual(assessment["decision"], "match")
                self.assertFalse([r for r in assessment["rule_ids"]
                                  if r.startswith("title.nontechnical_occupation.")])

    def test_an_explicit_exclude_still_beats_the_include(self):
        """Precedence is unchanged above the lexicon: excludes still run first."""
        assessment = assess_title("Sales Manager", self.SALES)
        self.assertEqual(assessment["decision"], "no_match")
        self.assertEqual(assessment["rule_ids"], ["title.excluded.manager"])

    def test_the_lexicon_still_drops_a_title_the_profile_never_named(self):
        """The lexicon is skipped for INCLUDED titles only, not switched off."""
        assessment = assess_title("Registered Nurse", self.SALES)
        self.assertEqual(assessment["decision"], "no_match")
        self.assertIn("title.nontechnical_occupation.clinical",
                      assessment["rule_ids"])

    def test_a_clinical_profile_keeps_its_own_roles_and_drops_the_rest(self):
        self.assertEqual(
            assess_title("Clinical Research Associate", self.CLINICAL)["decision"],
            "match")
        self.assertEqual(
            assess_title("Registered Nurse", self.CLINICAL)["decision"], "no_match")

    def test_a_recruiting_profile_keeps_its_own_roles_and_drops_the_rest(self):
        self.assertEqual(
            assess_title("Technical Recruiter", self.RECRUITING)["decision"], "match")
        self.assertEqual(
            assess_title("Head of People Operations", self.RECRUITING)["decision"],
            "no_match")

    def test_title_ok_keeps_the_included_posting_in_the_pipeline(self):
        posting = JobPosting(
            source="board", company="Example Corp", title="Account Executive",
            url="https://example.test/jobs/ae")
        self.assertTrue(title_ok(posting, {"titles": self.SALES}))
        self.assertEqual(posting.filter_assessments["title"]["decision"], "match")


class BroadDomainOnlyIncludeStillFacesTheLexiconTests(unittest.TestCase):
    """The wide form of the #232 fix ("any include match skips the lexicon") was
    MEASURED wrong: on a real corpus it changed eight rows and all eight got
    worse, turning finance/legal/communications postings from `no_match` into
    review-queue noise. Every one of them matched only a broad-domain token
    (``infrastructure``, ``platform``, ``compute``), which is a technical AREA and
    not an occupation declaration. The FICTIONAL titles below reproduce those
    eight shapes so the wide form cannot be reintroduced silently.
    """

    CFG = {"include": ["software engineer", "infrastructure", "platform",
                       "compute", "distributed systems"],
           "exclude": ["manager", "director"]}

    def test_broad_domain_only_finance_and_legal_titles_stay_hard_dropped(self):
        for title in ("Strategic Finance Partner, Compute",
                      "Capital Markets Associate - Infrastructure Financing",
                      "Commercial Counsel, Platform Marketplace",
                      "Associate General Counsel, Infrastructure",
                      "Utilities and Infrastructure Counsel",
                      "Communications Specialist, Platform",
                      "Platform Partnerships Lead, Programs",
                      "Commercial Counsel-Infrastructure and Go To Market"):
            with self.subTest(title=title):
                assessment = assess_title(title, self.CFG)
                self.assertEqual(assessment["decision"], "no_match")
                self.assertTrue([r for r in assessment["rule_ids"]
                                 if r.startswith("title.nontechnical_occupation.")],
                                assessment["rule_ids"])

    def test_the_broad_domain_set_is_the_one_the_residual_guard_already_uses(self):
        """One definition, not two — a second copy would drift out of agreement."""
        self.assertFalse(scoring._is_clean_include_match(["infrastructure"]))
        self.assertFalse(scoring._is_clean_include_match(["platform", "compute"]))
        self.assertTrue(scoring._is_clean_include_match(["account executive"]))
        self.assertTrue(scoring._is_clean_include_match(
            ["infrastructure", "software engineer"]))
        self.assertFalse(scoring._is_clean_include_match([]))

    def test_skipping_the_lexicon_can_never_introduce_a_new_drop(self):
        """The fix only moves an existing hard drop later in the chain.

        Every path below the lexicon ends in `match` or `review`, so a title that
        skips it cannot be dropped by something further down — which is why the
        measured row-change count on a software profile is zero.
        """
        for title in ("Account Executive", "Registered Nurse",
                      "Software Engineer, Platform", "Marketing Partnerships Lead",
                      "Strategic Finance Partner, Compute"):
            with self.subTest(title=title):
                widened = assess_title(title, self.CFG)["decision"]
                self.assertIn(widened, {"match", "review", "no_match"})
                if widened == "no_match":
                    # Still dropped -> it was dropped by an exclude or by the
                    # lexicon it never skipped, never by a rule below them.
                    self.assertTrue(
                        [r for r in assess_title(title, self.CFG)["rule_ids"]
                         if r.startswith("title.excluded.")
                         or r.startswith("title.nontechnical_occupation.")])


class DedupeIdentityTests(unittest.TestCase):
    """One title published as several per-location requisitions is several jobs."""

    def _req(self, req_id, location):
        return JobPosting(
            source="board", company="Acme", title="Senior Software Engineer",
            url=f"https://acme.example/jobs/{req_id}", location=location)

    def test_distinct_requisitions_are_not_collapsed(self):
        rows = [self._req("JR100", "Seattle, WA"), self._req("JR200", "New York, NY"),
                self._req("JR300", "Remote, US")]
        kept = search_jobs.dedupe(rows)
        self.assertEqual(len(kept), 3)
        self.assertEqual([p.url for p in kept], [p.url for p in rows])

    def test_the_same_opening_from_two_sources_still_collapses(self):
        # Two sources give the SAME opening two different URLs; that is exactly
        # what dedupe exists for, so the key must not be the URL.
        a = self._req("JR100", "Seattle, WA")
        b = self._req("JR100-indeed", "Seattle, WA")
        b.source, b.score = "aggregator", 9.0
        a.score = 1.0
        kept = search_jobs.dedupe([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].source, "aggregator")   # highest score wins


class LowQualityVisibilityTests(unittest.TestCase):
    """Gate 0 is the first hard drop in the pipeline; its count must be visible."""

    NOW = datetime(2026, 7, 22, tzinfo=timezone.utc)

    def test_the_gate_0_drop_count_reaches_the_run_metadata(self):
        template = JobPosting(
            source="board", company="Example Corp", title="<Job Title>",
            url="https://example.test/jobs/template",
            description="Lorem ipsum dolor sit amet.")
        real = JobPosting(
            source="board", company="Example Corp", title="Software Engineer",
            url="https://example.test/jobs/real", location="Remote, United States",
            description="Python, Kubernetes, distributed systems.")
        ctx = {"considered_urls": set(), "considered_pairs": set(), "skip_days": 0,
               "search_tokens": [], "ignore_search_log": True, "ai_native_keys": set()}
        _kept, counts = search_jobs.filter_score_rank(
            [template, real], {"titles": TITLES_CFG}, ctx, max_age=None, top_k=40,
            max_per_company=10, sponsor_index=None, company_levels={},
            registry=Registry([]), now=self.NOW)
        self.assertEqual(counts["n_low_quality"], 1)
        meta = search_jobs.build_meta(
            {"titles": TITLES_CFG}, types.SimpleNamespace(profile="example"),
            stage=1, n_companies=0, aggregators=[], n_raw=2, counts=counts,
            max_age=None, max_per_company=10, errors=[], now=self.NOW)
        self.assertEqual(meta["n_low_quality"], 1)


class OverCapExperienceRoutingTests(unittest.TestCase):
    """An over-cap requirement the extractor cannot act on belongs in review.

    `experience_ok` returned a bare bool, so a `review` verdict was a silent
    KEEP: the row reached the MAIN shortlist with `review_reasons: []`, reading
    exactly like a posting that stated no requirement. Nothing about it invited
    the reader to check the years by hand. Naming the verdict routes it to the
    review lane, which is what "not confident enough to DROP it" always meant.
    """

    NOW = datetime(2026, 7, 22, tzinfo=timezone.utc)

    def _ctx(self):
        return {"considered_urls": set(), "considered_pairs": set(),
                "skip_days": 0, "search_tokens": [],
                "ignore_search_log": True, "ai_native_keys": set()}

    def _run(self, description):
        posting = JobPosting(
            source="board", company="Example Corp", title="Software Engineer",
            url="https://example.test/jobs/yoe", location="Remote, United States",
            description=description)
        profile = {"titles": TITLES_CFG, "max_years_experience": 6}
        return search_jobs.filter_score_rank(
            [posting], profile, self._ctx(), max_age=None, top_k=40,
            max_per_company=10, sponsor_index=None, company_levels={},
            registry=Registry([]), now=self.NOW)

    def test_a_non_decisive_over_cap_row_lands_in_the_review_lane(self):
        kept, counts = self._run(
            "Requires 12+ years of experience with Kubernetes. "
            "Python, distributed systems.")
        self.assertEqual(kept, [])
        self.assertEqual(counts["n_review"], 1)
        self.assertIn("experience_over_cap",
                      counts["review_postings"][0].review_reasons)

    def test_a_decisive_over_cap_row_is_still_dropped_outright(self):
        kept, counts = self._run(
            "Requires at least 12 years of professional experience. "
            "Python, distributed systems.")
        self.assertEqual(kept, [])
        self.assertEqual(counts["n_review"], 0)

    def test_a_row_inside_the_cap_still_reaches_the_main_shortlist(self):
        kept, counts = self._run(
            "Requires 3+ years of experience with Kubernetes. "
            "Python, distributed systems.")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].review_reasons, [])
        self.assertEqual(counts["n_review"], 0)


class CompensationColumnUnitTests(unittest.TestCase):
    """The discovery table's pay column must state the unit it is printing.

    An aggregator's structured pay field may be hourly. The column compacted
    every band to thousands and printed no unit, so $30-$35 PER HOUR rendered as
    `30-35` — the same string a $30k-$35k annual band produces.
    """

    def test_an_hourly_band_prints_its_unit(self):
        self.assertEqual(
            search_jobs._format_comp(
                {"min": 30, "max": 35, "period": "hour", "currency": "USD"}),
            "30-35/hr")

    def test_an_annual_band_is_unchanged(self):
        for value, expected in (
            ({"min": 150000, "max": 190000, "period": "year",
              "currency": "USD"}, "150k-190k"),
            ({"min": 150000, "max": 190000}, "150k-190k"),
            (None, "?"),
            ({"min": None, "max": None}, "?"),
        ):
            with self.subTest(value=value):
                self.assertEqual(search_jobs._format_comp(value), expected)

    def test_a_non_usd_currency_is_named(self):
        self.assertEqual(
            search_jobs._format_comp(
                {"min": 60000, "max": 80000, "period": "year",
                 "currency": "EUR"}),
            "60k-80k EUR")

    def test_monthly_and_daily_bands_carry_their_own_unit(self):
        self.assertEqual(
            search_jobs._format_comp(
                {"min": 3000, "max": 4000, "period": "month"}), "3000-4000/mo")
        self.assertEqual(
            search_jobs._format_comp(
                {"min": 400, "max": 600, "period": "day"}), "400-600/day")


class UnimplementedProfileKeyTests(unittest.TestCase):
    """A salary floor that filters nothing must not look like one that does.

    `comp.min_base` / `comp.min_total` are declared in both shipped profiles and
    read by nothing. The user sets a number, sees a shortlist, and concludes
    every row clears the floor. Nothing filtered anything, and no output said so.
    """

    def test_a_set_floor_is_reported(self):
        warnings = search_jobs.unimplemented_profile_warnings(
            {"comp": {"min_base": 180000, "min_total": None}})
        self.assertEqual(len(warnings), 1)
        self.assertIn("comp.min_base", warnings[0])
        self.assertIn("not implemented", warnings[0])

    def test_both_floors_are_reported_separately(self):
        warnings = search_jobs.unimplemented_profile_warnings(
            {"comp": {"min_base": 180000, "min_total": 300000}})
        self.assertEqual(len(warnings), 2)

    def test_the_shipped_profiles_stay_silent(self):
        for name in ("example.yaml", "_TEMPLATE.yaml"):
            path = _SCRIPTS.parent / "profiles" / name
            with self.subTest(profile=name):
                profile = yaml.safe_load(path.read_text())
                self.assertEqual(
                    search_jobs.unimplemented_profile_warnings(profile), [])

    def test_an_absent_block_is_silent(self):
        self.assertEqual(search_jobs.unimplemented_profile_warnings({}), [])
        self.assertEqual(
            search_jobs.unimplemented_profile_warnings({"comp": None}), [])


class SponsorIndexCompanyKeyTests(unittest.TestCase):
    """DOL filings use legal names; postings use short registry names."""

    def test_a_legal_suffix_is_stripped_as_a_token_not_a_substring(self):
        for raw, expected in (("Acme Corporation", "acme"),
                              ("Acme Corp", "acme"),
                              ("Databricks Incorporated", "databricks"),
                              ("Databricks Inc", "databricks"),
                              ("Bio IO Health", "bio io health"),
                              ("Northwind Technologies", "northwind")):
            with self.subTest(raw=raw):
                self.assertEqual(scoring._norm_company(raw), expected)

    def test_the_boost_fires_for_a_legal_name_in_the_index(self):
        index = {scoring._norm_company("Acme Corp"): {"h1b": 40, "perm": 10}}
        posting = JobPosting(
            source="board", company="Acme Corporation",
            title="Senior Software Engineer", url="https://acme.example/jobs/1",
            description="Python, distributed systems.")
        score_posting(posting, {"titles": TITLES_CFG}, sponsor_index=index)
        self.assertTrue(any(r.startswith("DOL:") for r in posting.reasons),
                        posting.reasons)


if __name__ == "__main__":
    unittest.main()
