"""Builder-side parser tests + the parser<->live-fetcher PARITY harness.

The parity harness feeds the SAME captured-payload bytes through (a) the builder's
``posting_parsers`` and (b) the live fetcher's parsing path (HTTP stubbed to return
those bytes), then asserts the payload-derived fields agree — catching silent drift
without refactoring the battle-tested fetch path. Company on board sources is an
external registry argument (not payload-derived) so it cannot drift and is excluded;
for aggregators the company IS payload-derived and is compared.

Every test isolates the raw store to a throwaway ``JOBHUNT_DATA_ROOT`` so the live
fetchers' capture side-effect never writes into the real ``private/data`` store.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import aggregators  # noqa: E402
import capture_hooks  # noqa: E402
import common  # noqa: E402
import posting_parsers as pp  # noqa: E402
import sources  # noqa: E402
from common import HttpResult, parse_dt  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PRIVATE_DATA = _REPO_ROOT / "private" / "data"


def _result(body: bytes) -> HttpResult:
    return HttpResult(url="https://example.test/x", status=200, body=body,
                      headers={"content-type": "application/json"}, duration_ms=1,
                      ok=True, error=None, method="GET",
                      content_type="application/json")


# ── fictional payloads (Jordan-Rivers universe) ──────────────
GH = {"jobs": [{
    "id": 111, "title": " Software Engineer ", "location": {"name": "Austin, TX"},
    "absolute_url": "https://boards.greenhouse.io/examplecorp/jobs/111",
    "content": "&lt;p&gt;Build &amp; ship things&lt;/p&gt;",
    "first_published": "2026-07-10T00:00:00Z", "updated_at": "2026-07-12T00:00:00Z",
    "company_name": "ExampleCorp", "metadata": []}]}

ASHBY = {"apiVersion": "1", "jobs": [{
    "id": "ax-1", "title": "Platform Engineer", "location": "Remote (US)",
    "jobUrl": "https://jobs.ashbyhq.com/examplecorp/ax-1",
    "descriptionPlain": "Do platform work", "publishedAt": "2026-07-11T00:00:00Z",
    "isListed": True, "workplaceType": "Remote", "secondaryLocations": [],
    "compensation": {"summaryComponents": [{
        "compensationType": "Salary", "minValue": 150000, "maxValue": 210000,
        "currencyCode": "USD", "interval": "1 YEAR",
    }]}}]}

LEVER = [{
    "id": "lv-1", "text": "Site Reliability Engineer",
    "categories": {"location": "San Francisco, CA"},
    "hostedUrl": "https://jobs.lever.co/examplecorp/lv-1",
    "createdAt": 1720000000000, "descriptionPlain": "Keep it up",
    "additionalPlain": "Salary\n$140,000 - $190,000/year.",
    "workplaceType": "on-site",
    "salaryRange": {
        "min": 140000, "max": 190000, "currency": "USD", "interval": "year",
    }}]

JOBICY = {"jobs": [{
    "id": 501, "url": "https://jobicy.com/jobs/501-backend", "jobTitle": "Backend Engineer",
    "companyName": "RemoteCo", "jobGeo": "USA", "jobDescription": "desc",
    "pubDate": "2026-07-09 00:00:00"}]}

REMOTEOK = [{"legal": "notice"}, {
    "id": "ro1", "position": "Full Stack Dev", "company": "OceanCo",
    "url": "https://remoteOK.com/remote-jobs/ro1", "location": "Worldwide",
    "date": "2026-07-08T00:00:00Z", "description": "desc"}]

THEMUSE = {"results": [{
    "id": 9001, "name": "Data Engineer", "company": {"name": "MuseCo"},
    "locations": [{"name": "New York, NY"}],
    "refs": {"landing_page": "https://themuse.com/jobs/museco/data-9001"},
    "publication_date": "2026-07-07T00:00:00Z", "contents": "desc"}]}


def _core(jp):
    return (jp.title, jp.url, jp.location,
            jp.posted_at.isoformat() if jp.posted_at else None)


def _core_row(r):
    return (r["title"], r["url"], r["location"], r["posted_at"])


class LocationFidelityTests(unittest.TestCase):
    def test_ashby_appends_foreign_country_to_bare_city(self):
        payload = {"jobs": [{
            "id": "ax-foreign", "title": "Backend Engineer", "location": "Belgrade",
            "address": {"postalAddress": {
                "addressLocality": "Belgrade", "addressCountry": "Serbia",
            }},
        }]}
        rows = pp.parse_ashby(json.dumps(payload).encode())
        self.assertEqual(rows[0]["location"], "Belgrade, Serbia")

    def test_ashby_keeps_us_secondary_locations_unchanged(self):
        payload = {"jobs": [{
            "id": "ax-us", "title": "Platform Engineer", "location": "San Francisco, CA",
            "address": {"postalAddress": {
                "addressLocality": "San Francisco", "addressRegion": "CA",
                "addressCountry": "United States",
            }},
            "secondaryLocations": [
                {"location": "New York, NY"}, {"location": "Austin, TX"},
            ],
        }]}
        rows = pp.parse_ashby(json.dumps(payload).encode())
        self.assertEqual(
            rows[0]["location"],
            "San Francisco, CA / New York, NY, Austin, TX",
        )

    def test_lever_prefers_multiple_all_locations(self):
        payload = [{
            "id": "lv-us", "text": "Site Reliability Engineer", "country": "US",
            "categories": {
                "location": "United States",
                "allLocations": [
                    "United States", "San Diego, California", "Dallas, Texas",
                ],
            },
        }]
        rows = pp.parse_lever(json.dumps(payload).encode())
        self.assertEqual(
            rows[0]["location"],
            "United States / San Diego, California / Dallas, Texas",
        )

    def test_lever_appends_iso_country_name(self):
        payload = [{
            "id": "lv-gr", "text": "Software Engineer", "country": "GR",
            "categories": {"location": "Athens"},
        }]
        rows = pp.parse_lever(json.dumps(payload).encode())
        self.assertEqual(rows[0]["location"], "Athens, Greece")

    def test_apple_pairs_each_location_with_its_country(self):
        payload = {"res": {"searchResults": [{
            "positionId": "200599999", "postingTitle": "Software Engineer",
            "locations": [
                {"name": "San Francisco", "countryName": "United States of America"},
                {"name": "New York", "countryName": "United States of America"},
            ],
        }]}}
        rows = pp.parse_apple(json.dumps(payload).encode())
        self.assertEqual(
            rows[0]["location"],
            "San Francisco, United States of America / "
            "New York, United States of America",
        )


class _IsolatedCapture(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.get("JOBHUNT_DATA_ROOT")
        self.data_root = Path(tempfile.mkdtemp(prefix="parser-test-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.data_root)
        capture_hooks._reset_for_tests()
        self._http = (sources.http_get_full, aggregators.http_get_full)

    def tearDown(self):
        sources.http_get_full = self._http[0]
        aggregators.http_get_full = self._http[1]
        if self._prior is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior
        capture_hooks._reset_for_tests()
        shutil.rmtree(self.data_root, ignore_errors=True)


class ParityTests(_IsolatedCapture):
    def test_greenhouse_parity(self):
        body = json.dumps(GH).encode()
        sources.http_get_full = lambda *a, **k: _result(body)
        live = sources.fetch_greenhouse("ExampleCorp", "examplecorp")
        rows = pp.parse_greenhouse(body)
        self.assertEqual(len(live), len(rows))
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual(rows[0]["native_id"], "111")

    def test_ashby_parity(self):
        body = json.dumps(ASHBY).encode()
        sources.http_get_full = lambda *a, **k: _result(body)
        live = sources.fetch_ashby("ExampleCorp", "examplecorp")
        rows = pp.parse_ashby(body)
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual(rows[0]["native_id"], "ax-1")
        self.assertEqual(rows[0]["salary_range"], live[0].salary_range)
        self.assertEqual(rows[0]["salary_range"]["period"], "year")

    def test_lever_parity(self):
        body = json.dumps(LEVER).encode()
        sources.http_get_full = lambda *a, **k: _result(body)
        live = sources.fetch_lever("ExampleCorp", "examplecorp")
        rows = pp.parse_lever(body)
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual(rows[0]["native_id"], "lv-1")
        self.assertEqual(rows[0]["description"], live[0].description)
        self.assertIn("$140,000 - $190,000/year", rows[0]["description"])
        self.assertEqual(rows[0]["salary_range"], live[0].salary_range)
        self.assertEqual(rows[0]["salary_range"]["source"], "lever_api")

    def test_jobicy_parity_including_company(self):
        body = json.dumps(JOBICY).encode()
        aggregators.http_get_full = lambda *a, **k: _result(body)
        live = aggregators.fetch_jobicy([], "", None)
        rows = pp.parse_jobicy(body)
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual(live[0].company, rows[0]["company_name"])

    def test_remoteok_parity_skips_legal_header(self):
        body = json.dumps(REMOTEOK).encode()
        aggregators.http_get_full = lambda *a, **k: _result(body)
        live = aggregators.fetch_remoteok([], "", None)
        rows = pp.parse_remoteok(body)
        self.assertEqual(len(rows), 1)  # legal notice row dropped
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual(live[0].company, rows[0]["company_name"])

    def test_themuse_parity_including_company(self):
        body = json.dumps(THEMUSE).encode()
        aggregators.http_get_full = lambda *a, **k: _result(body)
        live = aggregators.fetch_themuse([], "", None, pages=1)
        rows = pp.parse_themuse(body)
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual(live[0].company, rows[0]["company_name"])


SR = {"content": [{
    "id": "744000", "name": "Cloud Engineer",
    "ref": "https://jobs.smartrecruiters.com/co/744000",
    "releasedDate": "2026-07-10T00:00:00Z", "company": {"name": "WDC"},
    "location": {"city": "San Jose", "region": "CA", "country": "us",
                 "remote": False, "hybrid": True}}]}


class SmartRecruitersParityTests(_IsolatedCapture):
    def setUp(self):
        super().setUp()
        self._json = sources.http_get_json

    def tearDown(self):
        sources.http_get_json = self._json
        super().tearDown()

    def test_smartrecruiters_parity(self):
        body = json.dumps(SR).encode()
        sources.http_get_full = lambda *a, **k: _result(body)
        sources.http_get_json = lambda *a, **k: {}  # empty detail (description only)
        live = sources.fetch_smartrecruiters("WDC", "co")
        rows = pp.parse_smartrecruiters(body)
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual(rows[0]["native_id"], "744000")


class BigTechParserTests(unittest.TestCase):
    """Amazon/Apple/Meta: live parse routes through capped/filtered network flows, so
    payload shape is covered by direct unit tests from real-shape synthetic payloads."""

    def test_amazon(self):
        payload = {"jobs": [{
            "id": "2851234", "title": "Software Dev Engineer",
            "job_path": "/en/jobs/2851234/sde", "normalized_location": "Seattle, WA, USA",
            "posted_date": "March 10, 2026", "description": "Build systems.",
            "company_name": "Amazon", "basic_qualifications": "BS"}]}
        rows = pp.parse_amazon(json.dumps(payload).encode())
        self.assertEqual(rows[0]["native_id"], "2851234")
        self.assertEqual(rows[0]["url"], "https://www.amazon.jobs/en/jobs/2851234/sde")
        self.assertEqual(rows[0]["location"], "Seattle, WA, USA")
        self.assertTrue(rows[0]["posted_at"].startswith("2026-03-10"))

    def test_apple_json_and_html(self):
        payload = {"res": {"searchResults": [{
            "positionId": "200591234", "postingTitle": "ML Engineer",
            "transformedPostingTitle": "ml-engineer", "team": {"teamCode": "SFTWR"},
            "locations": [{"name": "Cupertino", "countryName": "United States"}],
            "postingDate": "Mar 5, 2026", "jobSummary": "<p>ML work</p>",
            "homeOffice": False}]}}
        rows = pp.parse_apple(json.dumps(payload).encode())
        self.assertEqual(rows[0]["native_id"], "200591234")
        self.assertTrue(rows[0]["url"].startswith(
            "https://jobs.apple.com/en-us/details/200591234/ml-engineer?team=SFTWR"))
        self.assertEqual(rows[0]["description"], "ML work")
        # HTML handshake/bootstrap members parse to nothing (not an error).
        self.assertEqual(pp.parse_apple(b"<!doctype html><html></html>"), [])

    def test_meta_json_and_html(self):
        payload = {"data": {"job_search_with_featured_jobs": {"all_jobs": [{
            "id": "a1b2c3", "title": "Infra Engineer",
            "locations": ["Menlo Park, CA", "Remote, US"]}]}}}
        rows = pp.parse_meta(json.dumps(payload).encode())
        self.assertEqual(rows[0]["native_id"], "a1b2c3")
        self.assertEqual(rows[0]["url"], "https://www.metacareers.com/jobs/a1b2c3/")
        self.assertEqual(rows[0]["location"], "Menlo Park, CA / Remote, US")
        self.assertIsNone(rows[0]["posted_at"])
        self.assertEqual(pp.parse_meta(b"<!DOCTYPE html><html></html>"), [])


class WorkdayParseTests(unittest.TestCase):
    """Workday's live search parse routes through a separate network detail call, so
    payload parity is covered by a direct unit test of the search-row extraction."""

    PAYLOAD = {"total": 2, "jobPostings": [
        {"title": "Platform Engineer", "externalPath": "/en-US/site/job/Loc/PE_JR100",
         "locationsText": "Santa Clara, CA", "bulletFields": ["JR100"]},
        {"title": "SRE", "externalPath": "/en-US/site/job/Loc/SRE_JR200-1",
         "locationsText": "Remote, USA", "bulletFields": ["JR200"]},
    ]}

    def test_req_and_url_extraction(self):
        env = {"source": "workday", "operation": "search",
               "request": {"url": "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers"}}
        rows = pp.parse_workday(json.dumps(self.PAYLOAD).encode(), env)
        self.assertEqual(rows[0]["native_id"], "JR100")
        self.assertEqual(rows[1]["native_id"], "JR200")
        self.assertTrue(rows[0]["url"].startswith(
            "https://acme.wd5.myworkdayjobs.com/Careers/"))
        self.assertEqual(rows[0]["location"], "Santa Clara, CA")


class NormalizerTests(unittest.TestCase):
    def test_double_escaped_greenhouse_content_flattens_like_single_encoded(self):
        # Greenhouse content=true arrives DOUBLE entity-encoded; every other source
        # is single-encoded. Decoding is per-source and happens at parse time, so
        # the two forms of the same body must flatten — and therefore hash — the
        # same, and the normalized text must be free of markup.
        gh = "&lt;p&gt;Hello &amp;amp; world&lt;/p&gt;"      # greenhouse content=true
        single = "<p>Hello &amp; world</p>"                  # every other source
        self.assertEqual(common.strip_html(gh, entity_encoded=True), "Hello & world")
        self.assertEqual(
            pp.content_hash(common.strip_html(gh, entity_encoded=True)),
            pp.content_hash(common.strip_html(single)))

    def test_normalizer_version_declared(self):
        self.assertIsInstance(pp.NORMALIZER_VERSION, int)

    def test_whitespace_reflow_not_a_change(self):
        self.assertEqual(pp.content_hash("A  B\n\nC"), pp.content_hash("A B C"))

    def test_bad_payload_yields_no_rows(self):
        self.assertEqual(pp.parse_manifest({"source": "greenhouse",
                                            "operation": "board"}, b"not json"), [])
        self.assertEqual(pp.parse_manifest({"source": "greenhouse",
                                            "operation": "group"}, b"{}"), [])


# --------------------------------------------------------------------------- #
# RemoteOK source quality (#252): mojibake text behind one shared, non-actionable
# listing URL. Fixtures are built by DAMAGING known-good UTF-8 the way the feed
# does (encode UTF-8, read the bytes back as Latin-1), so the repair is tested
# against the real failure mode rather than a hand-typed approximation.
# --------------------------------------------------------------------------- #
_GREEK = "Μηχανικός Λογισμικού"
_CHINESE = "软件工程师"


def _mangle(text: str) -> str:
    """UTF-8 bytes read back as Latin-1 — exactly how the feed's rows arrive."""
    return text.encode("utf-8").decode("latin-1")


REMOTEOK_DAMAGED = [
    {"legal": "notice"},
    # Two unrelated rows, garbled, both pointing at the bare listing root.
    {"id": "bad-1", "position": _mangle(_GREEK), "company": _mangle("Φανταστικά"),
     "url": "https://remoteOK.com/remote-jobs/", "location": "Worldwide",
     "date": "2026-07-08T00:00:00Z", "description": _mangle(_GREEK)},
    {"id": "bad-2", "position": _mangle(_CHINESE), "company": _mangle("软件公司"),
     "url": "https://remoteOK.com/remote-jobs/", "location": "Worldwide",
     "date": "2026-07-08T00:00:00Z", "description": _mangle(_CHINESE)},
    # Garbled text but a real employer apply link: recoverable, not quarantined.
    {"id": "ok-apply", "position": _mangle(_GREEK), "company": "OceanCo",
     "url": "https://remoteOK.com/remote-jobs/",
     "apply_url": "https://oceanco.example/careers/postings/8891",
     "location": "Worldwide", "date": "2026-07-08T00:00:00Z",
     "description": _mangle(_CHINESE)},
    # Ordinary healthy row.
    {"id": "ok-1", "position": "Full Stack Dev", "company": "OceanCo",
     "url": "https://remoteOK.com/remote-jobs/ok-1-full-stack-dev",
     "location": "Worldwide", "date": "2026-07-08T00:00:00Z",
     "description": "desc"},
]


class MojibakeRepairTests(unittest.TestCase):
    def test_damaged_text_is_restored(self):
        self.assertEqual(pp.repair_mojibake(_mangle(_GREEK)), _GREEK)
        self.assertEqual(pp.repair_mojibake(_mangle(_CHINESE)), _CHINESE)

    def test_double_damage_is_restored(self):
        self.assertEqual(pp.repair_mojibake(_mangle(_mangle(_GREEK))), _GREEK)

    def test_healthy_unicode_is_never_touched(self):
        for good in (_GREEK, _CHINESE, "Zürich, Schweiz", "Café Ops Engineer",
                     "Señor Backend Engineer", "naïve", "Ça marche", ""):
            self.assertEqual(pp.repair_mojibake(good), good)

    def test_plain_ascii_is_returned_unchanged(self):
        self.assertEqual(pp.repair_mojibake("Senior Platform Engineer"),
                         "Senior Platform Engineer")

    def test_unrepairable_text_is_left_alone_not_mangled(self):
        # Mojibake mixed with genuinely non-Latin-1 text cannot be re-encoded:
        # the rule is to leave it rather than guess.
        mixed = _CHINESE + _mangle(_GREEK)
        self.assertEqual(pp.repair_mojibake(mixed), mixed)

    def test_none_is_an_empty_string(self):
        self.assertEqual(pp.repair_mojibake(None), "")


class RemoteOkSourceQualityTests(_IsolatedCapture):
    def setUp(self):
        super().setUp()
        common.drain_source_warnings()
        self.addCleanup(common.drain_source_warnings)
        self.body = json.dumps(REMOTEOK_DAMAGED).encode()
        aggregators.http_get_full = lambda *a, **k: _result(self.body)

    def _live(self):
        return aggregators.fetch_remoteok([], "", None)

    def test_valid_unicode_reaches_the_pipeline(self):
        row = next(p for p in self._live() if p.url.endswith("/postings/8891"))
        self.assertEqual(row.title, _GREEK)
        self.assertEqual(row.description, _CHINESE)

    def test_every_emitted_row_has_a_posting_specific_link(self):
        urls = [p.url for p in self._live()]
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(pp.url_identifies_a_posting(url), url)
        self.assertEqual(len(urls), len(set(urls)))   # no two rows share one URL

    def test_unopenable_rows_are_quarantined_once_with_a_diagnostic(self):
        out = self._live()
        self.assertEqual({p.title for p in out},
                         {_GREEK, "Full Stack Dev"})     # bad-1 / bad-2 dropped
        warnings = common.drain_source_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("quarantined 2 posting(s)", warnings[0])
        self.assertIn("bad-1", warnings[0])
        self.assertIn("bad-2", warnings[0])

    def test_the_diagnostic_never_repeats_the_garbled_text(self):
        self._live()
        warning = common.drain_source_warnings()[0]
        self.assertNotIn(_mangle(_GREEK), warning)

    def test_a_clean_feed_says_nothing(self):
        aggregators.http_get_full = lambda *a, **k: _result(
            json.dumps(REMOTEOK).encode())
        self.assertEqual(len(self._live()), 1)
        self.assertEqual(common.drain_source_warnings(), [])

    def test_the_builder_parser_agrees_with_the_live_fetcher(self):
        live = self._live()
        rows = pp.parse_remoteok(self.body)
        self.assertEqual([_core(j) for j in live], [_core_row(r) for r in rows])
        self.assertEqual([j.company for j in live],
                         [r["company_name"] for r in rows])

    def test_the_store_keeps_a_stable_id_for_every_materialized_row(self):
        rows = pp.parse_remoteok(self.body)
        self.assertEqual([r["native_id"] for r in rows], ["ok-apply", "ok-1"])


class ContainmentTests(_IsolatedCapture):
    def test_no_writes_reach_private_data(self):
        def _files():
            if not _PRIVATE_DATA.is_dir():
                return set()
            return {str(p) for p in _PRIVATE_DATA.rglob("*") if p.is_file()}
        before = _files()
        sources.http_get_full = lambda *a, **k: _result(json.dumps(GH).encode())
        sources.fetch_greenhouse("ExampleCorp", "examplecorp")
        self.assertEqual(_files(), before)


if __name__ == "__main__":
    unittest.main()
