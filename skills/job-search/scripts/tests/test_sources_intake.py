"""What ``sources.py`` decides BEFORE any gate in ``scoring.py`` can see a posting.

Two failure modes live here and both are invisible in the run summary unless the
fetcher says something:

* the coarse title prefilter drops a posting before its detail fetch, so a title
  the pipeline's title gate would have KEPT never enters the pipeline and appears
  in no count; and
* a per-posting detail fetch that fails is swallowed, so a total detail outage
  returns zero postings with zero errors ("this company has no matching jobs")
  and a partial one returns rows with empty descriptions that rank below top_k.

NO network: the HTTP layer is stubbed and the raw store is isolated to a throwaway
JOBHUNT_DATA_ROOT, so no test writes into a real store.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (_SCRIPTS, _SCRIPTS / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import capture_hooks  # noqa: E402
import common  # noqa: E402
import sources  # noqa: E402
from common import HttpResult  # noqa: E402
from scoring import title_ok  # noqa: E402


def _result(body: bytes) -> HttpResult:
    return HttpResult(url="https://example.test/x", status=200, body=body,
                      headers={"content-type": "application/json"}, duration_ms=1,
                      ok=True, error=None, method="GET",
                      content_type="application/json")


class TitlePrefilterTests(unittest.TestCase):
    """The prefilter's documented promise: never drop a title the gate would keep."""

    # Each of these carries a skip token as a SUBSTRING of a longer, unrelated
    # word: intern/Internal, intern/Internationalization, director/Directory,
    # sales/Salesforce, co-op/Co-operative.
    GLUED = (
        "Software Engineer, Internal Developer Platform",
        "Software Engineer - Internationalization",
        "Infrastructure Engineer, Internal Tools",
        "Systems Engineer, Active Directory",
        "Software Engineer, Salesforce Platform",
        "Software Engineer, Co-operative Caching",
    )
    # A seniority word sitting inside a QUALIFIER — a parenthetical, a hybrid
    # "engineer/manager" row, an appositive after a comma — is not the title's
    # head noun, and the two space-padded entries in _BIGTECH_TITLE_SKIP exist to
    # keep these. Word-anchoring alone (no padding) drops all four, which is a
    # silent recall loss: a title dropped here is never fetched, so it leaves no
    # filtered row and no snapshot trace.
    QUALIFIER_POSITION = (
        "Software Engineer (Manager Tools)",     # a product, not a report line
        "Software Engineer (VP)",                # the investment-bank IC level
        "Lead Software Engineer/Manager",        # hybrid IC row
        "VP, Engineering",                       # "vp" is not whitespace-delimited
    )
    # Genuinely non-matching occupations must still be dropped before the fetch.
    STILL_SKIPPED = (
        "Software Engineering Intern",
        "Engineering Manager",
        "Manager, Software Engineering",
        "Senior Manager, Software Engineering",
        "VP Engineering",
        "Engineering Manager, Platform",
        "Director of Engineering",
        "Enterprise Sales Executive",
        "Technical Recruiter",
        "Recruiting Coordinator",
        "Product Designer",
        "Account Executive, Mid-Market",
        "New Grad Software Engineer",
        "VP of Engineering",
    )
    # The one deliberate exception to "never drops a title the title gate would
    # keep": hardcoded seniority/discipline words. Pinned so the exception stays
    # visible and cannot drift silently while the owner decision is pending —
    # message-queue/needs-human/decisions/title-prefilter-hardcoded-seniority-words.md
    HARDCODED_SENIORITY = (
        "Principal Infrastructure Engineer",
        "Distinguished Engineer, Distributed Systems",
        "Research Scientist, Machine Learning",
        "Data Scientist, Platform",
    )

    def test_substring_of_a_longer_word_is_not_a_skip(self):
        for title in self.GLUED:
            with self.subTest(title=title):
                self.assertTrue(sources._title_prefilter(title))

    def test_a_seniority_word_inside_a_qualifier_is_not_a_skip(self):
        for title in self.QUALIFIER_POSITION:
            with self.subTest(title=title):
                self.assertTrue(
                    sources._title_prefilter(title),
                    f"prefilter drops {title!r}; 'manager'/'vp' need a WHITESPACE "
                    f"boundary, not just a word boundary")

    def test_the_padded_entries_keep_their_padding(self):
        """Pin the encoding itself — the spaces are the rule, not formatting."""
        self.assertIn(" manager", sources._BIGTECH_TITLE_SKIP)
        self.assertIn(" vp ", sources._BIGTECH_TITLE_SKIP)

    def test_odd_board_whitespace_does_not_smuggle_a_title_past_the_skip(self):
        for title in ("VP\tEngineering", "Engineering  Manager",
                      "VP Engineering", " Engineering Manager "):
            with self.subTest(title=title):
                self.assertFalse(sources._title_prefilter(title))

    def test_real_non_matching_occupations_are_still_skipped(self):
        for title in self.STILL_SKIPPED:
            with self.subTest(title=title):
                self.assertFalse(sources._title_prefilter(title))

    def test_hardcoded_seniority_words_are_still_skipped_pending_the_decision(self):
        for title in self.HARDCODED_SENIORITY:
            with self.subTest(title=title):
                self.assertFalse(sources._title_prefilter(title))

    def test_prefilter_agrees_with_the_pipeline_title_gate(self):
        """The promise above _BIGTECH_TITLE_SKIP, asserted rather than asserted-in-prose.

        Scope: no title may be dropped merely because a skip token is glued
        inside a longer, unrelated word. The hardcoded seniority/discipline
        words are the one KNOWN exception to the wider promise and are excluded
        here on purpose — they are pinned by the test above and carry an open
        owner decision, so they are a documented gap, not an undetected one.
        """
        profile = {"titles": {"include": ["software engineer",
                                          "infrastructure engineer"]}}
        for title in self.GLUED:
            with self.subTest(title=title):
                posting = common.JobPosting(source="workday", company="Example Corp",
                                            title=title, url="https://example.test/1")
                if title_ok(posting, profile):
                    self.assertTrue(
                        sources._title_prefilter(title),
                        f"prefilter drops {title!r} that the title gate keeps")


class _FetchCase(unittest.TestCase):
    """Isolate the raw store and the partial-fetch warning sink per test."""

    def setUp(self):
        self._prior = os.environ.get("JOBHUNT_DATA_ROOT")
        self.data_root = Path(tempfile.mkdtemp(prefix="intake-test-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.data_root)
        capture_hooks._reset_for_tests()
        self._http = (sources.http_get_full, sources.http_post_json_full,
                      sources.http_get_json)
        common.drain_source_warnings()

    def tearDown(self):
        (sources.http_get_full, sources.http_post_json_full,
         sources.http_get_json) = self._http
        if self._prior is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior
        capture_hooks._reset_for_tests()
        common.drain_source_warnings()
        shutil.rmtree(self.data_root, ignore_errors=True)


_WORKDAY_PAGE = (b'{"jobPostings": [{"externalPath": "/job/1", '
                 b'"title": "Platform Engineer"}, {"externalPath": "/job/2", '
                 b'"title": "Infrastructure Engineer"}]}')


def _workday_detail(path_suffix: str) -> dict:
    return {"jobPostingInfo": {"title": f"Engineer {path_suffix}",
                               "location": "Seattle, WA",
                               "jobDescription": "<p>Build things.</p>",
                               "startDate": "2026-07-01"}}


class WorkdayDetailOutageTests(_FetchCase):
    def _fetch(self):
        return sources.fetch_workday("Testco", "testco",
                                     "testco.wd5.myworkdayjobs.com", "External",
                                     search_terms=["kubernetes"])

    def test_total_detail_outage_raises_instead_of_reporting_zero_jobs(self):
        sources.http_post_json_full = lambda *a, **k: _result(_WORKDAY_PAGE)

        def _boom(url, *a, **k):
            raise RuntimeError("GET failed for %s: HTTP 503 Service Unavailable" % url)

        sources.http_get_json = _boom
        with self.assertRaises(RuntimeError) as ctx:
            self._fetch()
        self.assertIn("all 2 detail fetches failed", str(ctx.exception))

    def test_partial_detail_outage_keeps_rows_and_reports_what_it_missed(self):
        sources.http_post_json_full = lambda *a, **k: _result(_WORKDAY_PAGE)

        def _flaky(url, *a, **k):
            if url.endswith("/job/2"):
                raise RuntimeError("HTTP 429 Too Many Requests")
            return _workday_detail("1")

        sources.http_get_json = _flaky
        out = self._fetch()
        self.assertEqual(len(out), 1)
        warnings = common.drain_source_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 of 2 detail fetches failed", warnings[0])
        self.assertIn("Testco", warnings[0])

    def test_healthy_fetch_reports_nothing(self):
        sources.http_post_json_full = lambda *a, **k: _result(_WORKDAY_PAGE)
        sources.http_get_json = lambda url, *a, **k: _workday_detail(url[-1])
        self.assertEqual(len(self._fetch()), 2)
        self.assertEqual(common.drain_source_warnings(), [])


_SR_LISTING = (b'{"content": [{"id": "1", "name": "Platform Engineer", '
               b'"location": {"city": "Seattle", "region": "WA"}}, '
               b'{"id": "2", "name": "Infrastructure Engineer", '
               b'"location": {"city": "Austin", "region": "TX"}}], "totalFound": 2}')
_SR_DETAIL = {"jobAd": {"sections": {"jobDescription": {"text": "<p>Build things.</p>"}}}}


class SmartRecruitersDetailOutageTests(_FetchCase):
    def test_total_jd_outage_raises_instead_of_emitting_empty_descriptions(self):
        sources.http_get_full = lambda *a, **k: _result(_SR_LISTING)

        def _boom(*a, **k):
            raise RuntimeError("HTTP 429 Too Many Requests")

        sources.http_get_json = _boom
        with self.assertRaises(RuntimeError) as ctx:
            sources.fetch_smartrecruiters("Testco", "testco")
        self.assertIn("all 2 JD detail fetches failed", str(ctx.exception))

    def test_partial_jd_outage_reports_the_empty_descriptions(self):
        sources.http_get_full = lambda *a, **k: _result(_SR_LISTING)
        calls = {"n": 0}

        def _flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("HTTP 503 Service Unavailable")
            return _SR_DETAIL

        sources.http_get_json = _flaky
        out = sources.fetch_smartrecruiters("Testco", "testco")
        self.assertEqual(len(out), 2)
        self.assertEqual([bool(p.description) for p in out], [True, False])
        warnings = common.drain_source_warnings()
        self.assertTrue(any("1 of 2 JD detail fetches failed" in w for w in warnings))

    def test_healthy_fetch_reports_nothing(self):
        sources.http_get_full = lambda *a, **k: _result(_SR_LISTING)
        sources.http_get_json = lambda *a, **k: _SR_DETAIL
        self.assertEqual(len(sources.fetch_smartrecruiters("Testco", "testco")), 2)
        self.assertEqual(common.drain_source_warnings(), [])


class SmartRecruitersTruncationReportTests(_FetchCase):
    def test_truncated_listing_is_reported_to_the_run_not_only_to_the_store(self):
        # The listing caps at `limit`; totalFound says how much was NOT returned.
        body = (b'{"content": [{"id": "1", "name": "Platform Engineer", '
                b'"location": {}}], "totalFound": 280}')
        sources.http_get_full = lambda *a, **k: _result(body)
        sources.http_get_json = lambda *a, **k: _SR_DETAIL
        sources.fetch_smartrecruiters("Testco", "testco")
        warnings = common.drain_source_warnings()
        self.assertTrue(any("truncated at 1 of 280" in w for w in warnings),
                        f"no truncation report in {warnings!r}")


class SourceWarningSinkTests(unittest.TestCase):
    def test_draining_clears_the_sink(self):
        common.drain_source_warnings()
        common.record_source_warning("workday:Testco: 1 of 2 detail fetches failed")
        self.assertEqual(len(common.drain_source_warnings()), 1)
        self.assertEqual(common.drain_source_warnings(), [])


if __name__ == "__main__":
    unittest.main()
