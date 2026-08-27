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

import json
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
import title_filter  # noqa: E402
import yaml  # noqa: E402
from common import HttpResult  # noqa: E402
from scoring import title_ok  # noqa: E402

# The prefilter has NO list of its own any more: the words are the candidate's,
# read from the profile. These tests drive it with the PUBLIC example profile, so
# a change to that profile's word_filter shows up here instead of in a live search.
_EXAMPLE_PROFILE = yaml.safe_load(
    (_SCRIPTS.parent / "profiles" / "example.yaml").read_text())
EXAMPLE_FILTER = title_filter.load_word_lists(_EXAMPLE_PROFILE)


def _result(body: bytes, *, status=200, ok=True, error=None,
            headers=None) -> HttpResult:
    return HttpResult(url="https://example.test/x", status=status, body=body,
                      headers=headers or {"content-type": "application/json"},
                      duration_ms=1, ok=ok, error=error, method="GET",
                      content_type="application/json")


class TitlePrefilterTests(unittest.TestCase):
    """The prefilter's documented promise: never drop a title the gate would keep.

    Driven by the public example profile's ``titles.word_filter`` — the prefilter
    holds no words of its own (owner decision 2026-08-01), so what these assert is
    the MATCHING behaviour plus the example persona's own choices.
    """

    def _keeps(self, title):
        return sources._title_prefilter(title, EXAMPLE_FILTER)

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
    # head noun, and the two space-padded entries in the profile's word_filter
    # exist to keep these. Word-anchoring alone (no padding) drops all four, which
    # is a silent recall loss: a title dropped here is never fetched, so it leaves
    # no filtered row and no snapshot trace.
    QUALIFIER_POSITION = (
        "Software Engineer (Manager Tools)",     # a product, not a report line
        "Software Engineer (VP)",                # the investment-bank IC level
        "Lead Software Engineer/Manager",        # hybrid IC row
        "VP, Engineering",                       # "vp" is not whitespace-delimited
    )
    # Genuinely non-matching occupations must still be dropped before the fetch.
    # `hard_exclude` in the example profile. The manager-family rows moved to
    # `soft_exclude` there (they are kept and marked, not dropped) and are
    # asserted in test_title_word_filter.py instead.
    STILL_SKIPPED = (
        "Software Engineering Intern",
        "VP Engineering",
        "Director of Engineering",
        "Enterprise Sales Executive",
        "Technical Recruiter",
        "Recruiting Coordinator",
        "Product Designer",
        "Account Executive, Mid-Market",
        "New Grad Software Engineer",
        "VP of Engineering",
    )
    # The five words that USED to be hardcoded, and were the one deliberate
    # exception to "never drops a title the title gate would keep". They are now
    # profile-owned and the example persona files them as include (principal /
    # distinguished / fellow) or soft_exclude (the two scientist titles) — either
    # way, never dropped before the fetch.
    FORMERLY_HARDCODED_SENIORITY = (
        "Principal Infrastructure Engineer",
        "Distinguished Engineer, Distributed Systems",
        "Research Scientist, Machine Learning",
        "Data Scientist, Platform",
    )

    def test_substring_of_a_longer_word_is_not_a_skip(self):
        for title in self.GLUED:
            with self.subTest(title=title):
                self.assertTrue(self._keeps(title))

    def test_a_seniority_word_inside_a_qualifier_is_not_a_skip(self):
        for title in self.QUALIFIER_POSITION:
            with self.subTest(title=title):
                self.assertTrue(
                    self._keeps(title),
                    f"prefilter drops {title!r}; 'manager'/'vp' need a WHITESPACE "
                    f"boundary, not just a word boundary")

    def test_the_padded_entries_keep_their_padding(self):
        """Pin the encoding itself — the spaces are the rule, not formatting.

        The words moved out of code into the profile, so this now pins the
        PROFILE's spelling: strip the padding there and the two qualifier-position
        titles above start being dropped before they are ever fetched.
        """
        self.assertIn(" manager", EXAMPLE_FILTER.soft_exclude)
        self.assertIn(" vp ", EXAMPLE_FILTER.hard_exclude)

    def test_odd_board_whitespace_does_not_smuggle_a_title_past_the_skip(self):
        # "Engineering Manager" is soft in the example profile, so it is KEPT for
        # review rather than dropped; " vp " is hard, so it is dropped.
        for title in ("VP\tEngineering", "VP Engineering"):
            with self.subTest(title=title):
                self.assertFalse(self._keeps(title))
        for title in ("Engineering  Manager", " Engineering Manager "):
            with self.subTest(title=title):
                verdict = EXAMPLE_FILTER.classify(title)
                self.assertEqual(verdict.action, title_filter.ACTION_REVIEW)
                self.assertEqual(verdict.soft_hits, (" manager",))

    def test_real_non_matching_occupations_are_still_skipped(self):
        for title in self.STILL_SKIPPED:
            with self.subTest(title=title):
                self.assertFalse(self._keeps(title))

    def test_formerly_hardcoded_seniority_words_now_reach_the_fetch(self):
        """The decision's whole point: these five stop being a silent loss."""
        for title in self.FORMERLY_HARDCODED_SENIORITY:
            with self.subTest(title=title):
                self.assertTrue(
                    self._keeps(title),
                    f"prefilter still drops {title!r}; the profile files it as "
                    f"include/soft_exclude, neither of which may drop")
                self.assertEqual(EXAMPLE_FILTER.classify(title).action,
                                 title_filter.ACTION_REVIEW)

    def test_an_unconfigured_profile_drops_nothing(self):
        """No word lists = no coarse filter, never a built-in fallback list."""
        inert = title_filter.load_word_lists({})
        self.assertFalse(inert.configured)
        for title in self.STILL_SKIPPED + self.FORMERLY_HARDCODED_SENIORITY:
            with self.subTest(title=title):
                self.assertTrue(sources._title_prefilter(title, inert))
                self.assertTrue(sources._title_prefilter(title))   # default = inert

    def test_prefilter_agrees_with_the_pipeline_title_gate(self):
        """The promise above _BIGTECH_TITLE_SKIP, asserted rather than asserted-in-prose.

        Scope: no title may be dropped merely because a skip token is glued
        inside a longer, unrelated word. The former exception — five hardcoded
        seniority/discipline words — is gone: those words are the profile's now,
        and the test above asserts they reach the fetch.
        """
        profile = {"titles": {"include": ["software engineer",
                                          "infrastructure engineer"]}}
        for title in self.GLUED:
            with self.subTest(title=title):
                posting = common.JobPosting(source="workday", company="Example Corp",
                                            title=title, url="https://example.test/1")
                if title_ok(posting, profile):
                    self.assertTrue(
                        self._keeps(title),
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
        self._workday_timing = (
            sources._WORKDAY_DETAIL_PACE_SECONDS,
            sources._WORKDAY_FALLBACK_BACKOFF_SECONDS,
            sources._WORKDAY_RETRY_AFTER_CEILING_SECONDS,
        )
        sources._WORKDAY_DETAIL_PACE_SECONDS = 0
        sources._WORKDAY_FALLBACK_BACKOFF_SECONDS = 0
        sources._WORKDAY_RETRY_AFTER_CEILING_SECONDS = 0
        common.drain_source_warnings()

    def tearDown(self):
        (sources.http_get_full, sources.http_post_json_full,
         sources.http_get_json) = self._http
        (sources._WORKDAY_DETAIL_PACE_SECONDS,
         sources._WORKDAY_FALLBACK_BACKOFF_SECONDS,
         sources._WORKDAY_RETRY_AFTER_CEILING_SECONDS) = self._workday_timing
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
            return _result(b"", status=503, ok=False,
                           error="HTTP 503 Service Unavailable")

        sources.http_get_full = _boom
        with self.assertRaises(RuntimeError) as ctx:
            self._fetch()
        self.assertIn("all 2 detail fetches failed", str(ctx.exception))

    def test_partial_detail_outage_keeps_rows_and_reports_what_it_missed(self):
        sources.http_post_json_full = lambda *a, **k: _result(_WORKDAY_PAGE)

        def _flaky(url, *a, **k):
            if url.endswith("/job/2"):
                return _result(b"", status=429, ok=False,
                               error="HTTP 429 Too Many Requests")
            return _result(json.dumps(_workday_detail("1")).encode())

        sources.http_get_full = _flaky
        out = self._fetch()
        self.assertEqual(len(out), 1)
        warnings = common.drain_source_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 of 2 detail fetches failed", warnings[0])
        self.assertIn("Testco", warnings[0])
        self.assertIn("coverage=incomplete", warnings[0])
        self.assertIn("4 total attempts", warnings[0])

    def test_healthy_fetch_reports_nothing(self):
        sources.http_post_json_full = lambda *a, **k: _result(_WORKDAY_PAGE)
        sources.http_get_full = lambda url, *a, **k: _result(
            json.dumps(_workday_detail(url[-1])).encode())
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


def _sr_page(offset: int, total: int, *, limit=None) -> bytes:
    """One SmartRecruiters listing page: rows [offset, offset+limit) of `total`."""
    limit = sources._SR_PAGE_LIMIT if limit is None else limit
    rows = [{"id": str(i), "name": f"Engineer {i}", "location": {}}
            for i in range(offset, min(offset + limit, total))]
    return json.dumps({"content": rows, "totalFound": total,
                       "offset": offset, "limit": limit}).encode()


class SmartRecruitersPaginationTests(_FetchCase):
    """A board is not its first 100 rows (#236).

    Reading one page inspected the first `limit` postings and ignored the rest —
    deterministic recall loss on any employer with a big board, before a single
    gate ran, with WHICH rows survive decided by the provider's page ordering.
    """

    def _serve(self, total, *, fail_at=None, replay=False, limit=None):
        """Serve a `total`-row board a page at a time; record every offset asked."""
        self.offsets = []

        def _get(url, *a, **k):
            offset = int(url.split("offset=")[1].split("&")[0])
            self.offsets.append(offset)
            if fail_at is not None and offset == fail_at:
                return HttpResult(url=url, status=503, body=b"", headers={},
                                  duration_ms=1, ok=False,
                                  error="HTTP 503 Service Unavailable", method="GET",
                                  content_type=None)
            served = 0 if replay else offset
            return _result(_sr_page(served, total, limit=limit))

        sources.http_get_full = _get
        sources.http_get_json = lambda *a, **k: _SR_DETAIL

    def test_a_233_row_board_is_inspected_whole(self):
        self._serve(233)
        out = sources.fetch_smartrecruiters("Testco", "testco")
        self.assertEqual(len(out), 233)
        self.assertEqual(self.offsets, [0, 100, 200])          # 100 + 100 + 33
        self.assertEqual(common.drain_source_warnings(), [])   # nothing was missed

    def test_paging_stops_on_a_short_page_without_asking_for_more(self):
        self._serve(150)
        self.assertEqual(len(sources.fetch_smartrecruiters("Testco", "testco")), 150)
        self.assertEqual(self.offsets, [0, 100])

    def test_an_exact_multiple_of_the_page_size_stops_at_total_found(self):
        self._serve(200)
        self.assertEqual(len(sources.fetch_smartrecruiters("Testco", "testco")), 200)
        self.assertEqual(self.offsets, [0, 100])

    def test_overlapping_pages_deduplicate_by_posting_id(self):
        # Page 2 re-serves rows 50-149 (the board shifted under us mid-crawl).
        pages = [_sr_page(0, 233), _sr_page(50, 233), _sr_page(200, 233)]
        calls = {"n": 0}

        def _get(*a, **k):
            body = pages[min(calls["n"], len(pages) - 1)]
            calls["n"] += 1
            return _result(body)

        sources.http_get_full = _get
        sources.http_get_json = lambda *a, **k: _SR_DETAIL
        out = sources.fetch_smartrecruiters("Testco", "testco")
        self.assertEqual(len(out), len({p.url for p in out}))   # no double-count

    def test_a_board_that_ignores_offset_cannot_spin_forever(self):
        self._serve(500, replay=True)          # every page is page 1
        out = sources.fetch_smartrecruiters("Testco", "testco")
        self.assertEqual(len(out), 100)
        self.assertLessEqual(len(self.offsets), 3)
        self.assertTrue(any("not paging" in w for w in common.drain_source_warnings()))

    def test_a_malformed_total_cannot_loop_or_stop_the_crawl_early(self):
        body = json.dumps({"content": [{"id": str(i), "name": "E", "location": {}}
                                       for i in range(100)],
                           "totalFound": "lots"}).encode()
        tail = json.dumps({"content": [], "totalFound": None}).encode()
        bodies = [body, tail]
        calls = {"n": 0}

        def _get(*a, **k):
            out = bodies[min(calls["n"], len(bodies) - 1)]
            calls["n"] += 1
            return _result(out)

        sources.http_get_full = _get
        sources.http_get_json = lambda *a, **k: _SR_DETAIL
        self.assertEqual(len(sources.fetch_smartrecruiters("Testco", "testco")), 100)
        self.assertEqual(calls["n"], 2)

    # -- a cap is not a failure --------------------------------------------- #
    def test_the_per_board_cap_is_reported_as_a_cap_naming_its_knob(self):
        self._serve(1000)
        out = sources.fetch_smartrecruiters("Testco", "testco", max_postings=150)
        self.assertEqual(len(out), 150)
        warnings = common.drain_source_warnings()
        said = " ".join(warnings)
        self.assertIn("configured per-board cap", said)
        self.assertIn("max_postings", said)
        self.assertNotIn("failed", said)

    def test_a_registry_row_can_raise_the_cap(self):
        self._serve(1000)
        out = sources.fetch_company({"name": "Testco", "ats": "smartrecruiters",
                                     "token": "testco", "max_postings": 250})
        self.assertEqual(len(out), 250)
        common.drain_source_warnings()

    # -- failure semantics --------------------------------------------------- #
    def test_a_first_page_failure_still_raises(self):
        self._serve(233, fail_at=0)
        with self.assertRaises(RuntimeError):
            sources.fetch_smartrecruiters("Testco", "testco")

    def test_a_later_page_failure_keeps_the_rows_already_in_hand(self):
        self._serve(233, fail_at=100)
        out = sources.fetch_smartrecruiters("Testco", "testco")
        self.assertEqual(len(out), 100)          # dropping these would be worse
        warnings = common.drain_source_warnings()
        self.assertTrue(any("listing incomplete" in w for w in warnings), warnings)

    def test_a_small_board_reports_nothing_at_all(self):
        self._serve(12)
        self.assertEqual(len(sources.fetch_smartrecruiters("Testco", "testco")), 12)
        self.assertEqual(common.drain_source_warnings(), [])

    def test_ending_short_of_total_found_is_still_reported(self):
        # The board says 5 and hands back 2 with no further page: paging ended,
        # but coverage did not. Silence here would read as a fully inspected board.
        body = json.dumps({"content": [{"id": "1", "name": "SWE", "location": {}},
                                       {"id": "2", "name": "Infra", "location": {}}],
                           "totalFound": 5}).encode()
        sources.http_get_full = lambda *a, **k: _result(body)
        sources.http_get_json = lambda *a, **k: _SR_DETAIL
        self.assertEqual(len(sources.fetch_smartrecruiters("Testco", "testco")), 2)
        warnings = common.drain_source_warnings()
        self.assertTrue(any("totalFound said 5" in w for w in warnings), warnings)


class SourceWarningSinkTests(unittest.TestCase):
    def test_draining_clears_the_sink(self):
        common.drain_source_warnings()
        common.record_source_warning("workday:Testco: 1 of 2 detail fetches failed")
        self.assertEqual(len(common.drain_source_warnings()), 1)
        self.assertEqual(common.drain_source_warnings(), [])


if __name__ == "__main__":
    unittest.main()
