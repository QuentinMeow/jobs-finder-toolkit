"""Capture-at-the-fetch-boundary tests (store stage 1).

NO network: the HTTP layer is stubbed so each fetcher runs against fixed bytes.
Every test isolates the raw store to a throwaway data root via JOBHUNT_DATA_ROOT
(env beats the machine config's real store) — no test ever writes into private/data.

Covered: induced parse failure leaves readable raw; capture-disabled fetch is
byte-identical with no store writes; greenhouse board group (attested complete);
workday search group (multi-request, honest counts, not complete); failed fetch
captured; JobSpy deterministic scrape serialization + capture; two-process
concurrent capture at the fetcher level; and the write-containment guarantee.
"""
from __future__ import annotations

import multiprocessing
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
import fetch_jd  # noqa: E402
import sources  # noqa: E402
from common import HttpResult  # noqa: E402
from _vendor.store.blobs import BlobStore  # noqa: E402
from _vendor.store.manifest import iter_manifests  # noqa: E402
from _vendor.store.paths import domain_layout  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PRIVATE_DATA = _REPO_ROOT / "private" / "data"


def _result(body: bytes, *, status=200, ok=True, content_type="application/json",
            error=None, headers=None) -> HttpResult:
    return HttpResult(url="https://example.test/x", status=status, body=body,
                      headers=(headers if headers is not None
                               else {"content-type": content_type or ""}),
                      duration_ms=3, ok=ok, error=error, method="GET",
                      content_type=content_type)


def _private_data_files() -> set[str]:
    if not _PRIVATE_DATA.is_dir():
        return set()
    return {str(p) for p in _PRIVATE_DATA.rglob("*") if p.is_file()}


class _CaptureCase(unittest.TestCase):
    """Base: isolate the store to a fresh temp data root per test."""

    def setUp(self):
        self._prior = os.environ.get("JOBHUNT_DATA_ROOT")
        self.data_root = Path(tempfile.mkdtemp(prefix="capture-test-"))
        os.environ["JOBHUNT_DATA_ROOT"] = str(self.data_root)
        capture_hooks._reset_for_tests()
        self.layout = domain_layout(self.data_root, "jobs")
        # Save the real HTTP layer so a test's stub never leaks into another module.
        self._http = (sources.http_get_full, sources.http_post_json_full,
                      sources.http_get_json)

    def tearDown(self):
        (sources.http_get_full, sources.http_post_json_full,
         sources.http_get_json) = self._http
        if self._prior is None:
            os.environ.pop("JOBHUNT_DATA_ROOT", None)
        else:
            os.environ["JOBHUNT_DATA_ROOT"] = self._prior
        capture_hooks._reset_for_tests()
        shutil.rmtree(self.data_root, ignore_errors=True)

    def manifests(self):
        return [env for _p, env in iter_manifests(self.layout)]


class InducedParseFailureTests(_CaptureCase):
    """The design's core promise: a parse failure leaves readable raw on disk."""

    def test_broken_json_raises_but_raw_is_captured(self):
        broken = b'{"jobs": [ this is not valid json'
        sources.http_get_full = lambda *a, **k: _result(broken)  # stub HTTP
        with self.assertRaises(Exception):
            sources.fetch_greenhouse("Testco", "testco")

        # Despite the fetcher error, the raw blob + manifest exist and the blob
        # decompresses to the EXACT upstream bytes.
        manifests = self.manifests()
        members = [m for m in manifests if m.get("operation") == "board"]
        self.assertEqual(len(members), 1)
        payload = members[0]["payload"]
        self.assertIsNotNone(payload)
        blobs = BlobStore(self.layout.blobs)
        self.assertEqual(blobs.read(payload["blob"]), broken)


class ResponseHeaderRedactionTests(_CaptureCase):
    HEADERS = {
        "Set-Cookie": "sid=abc123", "x-apple-csrf-token": "tok",
        "X-RapidAPI-Key": "secretkey", "WWW-Authenticate": "Bearer realm=x",
        "ETag": "W/\"abc\"", "Content-Type": "application/json",
    }

    def test_redact_headers_unit(self):
        out = capture_hooks._redact_headers(self.HEADERS)
        self.assertEqual(out["Set-Cookie"], "[redacted]")
        self.assertEqual(out["x-apple-csrf-token"], "[redacted]")
        self.assertEqual(out["X-RapidAPI-Key"], "[redacted]")
        self.assertEqual(out["WWW-Authenticate"], "[redacted]")
        self.assertEqual(out["ETag"], "W/\"abc\"")            # intact
        self.assertEqual(out["Content-Type"], "application/json")  # intact

    def test_stored_manifest_headers_are_redacted(self):
        sources.http_get_full = lambda *a, **k: _result(b'{"jobs": []}',
                                                        headers=self.HEADERS)
        sources.fetch_greenhouse("Testco", "testco")
        board = [m for m in self.manifests() if m.get("operation") == "board"][0]
        rh = board["response_headers"]
        self.assertEqual(rh["Set-Cookie"], "[redacted]")
        self.assertEqual(rh["x-apple-csrf-token"], "[redacted]")
        self.assertEqual(rh["X-RapidAPI-Key"], "[redacted]")
        self.assertEqual(rh["WWW-Authenticate"], "[redacted]")
        self.assertEqual(rh["ETag"], "W/\"abc\"")
        self.assertEqual(rh["Content-Type"], "application/json")


class BadJsonAttestationTests(_CaptureCase):
    def test_truncated_board_attests_incomplete_and_raises(self):
        # A non-empty 200 that does not parse into a jobs list must attest
        # complete:false (not a false complete) and still raise.
        sources.http_get_full = lambda *a, **k: _result(b'{"jobs": [ {"title": "x"')
        with self.assertRaises(Exception):
            sources.fetch_greenhouse("Testco", "testco")
        boards = [m for m in self.manifests() if m.get("operation") == "board"]
        groups = [m for m in self.manifests() if m.get("operation") == "group"]
        self.assertEqual(len(boards), 1)
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0]["attested_complete"])


class WorkdayBadJsonRetryTests(_CaptureCase):
    def test_2xx_bad_json_is_retried_and_both_attempts_captured(self):
        responses = [_result(b'{ bad json'),
                     _result(b'{"jobPostings": []}')]  # good on retry
        sources.http_post_json_full = lambda *a, **k: responses.pop(0)
        sources.http_get_json = lambda *a, **k: {}
        sources.fetch_workday("Testco", "testco", "testco.wd5.myworkdayjobs.com",
                              "External", search_terms=["kubernetes"])
        searches = [m for m in self.manifests() if m.get("operation") == "search"]
        self.assertEqual(len(searches), 2)   # each attempt captured (failure = data)
        self.assertEqual(responses, [])       # retry consumed the good response


class FileSchemeJdTests(_CaptureCase):
    def test_file_scheme_jd_is_not_captured(self):
        page = self.data_root / "page.html"
        page.write_text("<html><body><h1>X</h1><p>hi</p></body></html>")
        fetch_jd.fetch_page(f"file://{page}", 5)
        # Non-http(s) schemes are never captured (would persist a local path/user).
        self.assertEqual(self.manifests(), [])


class DisabledCaptureTests(_CaptureCase):
    """With the store disabled the fetch is byte-identical and writes nothing."""

    def test_disabled_fetch_is_identical_and_writes_nothing(self):
        board = b'{"jobs": [{"title": "Platform Engineer", "location": ' \
                b'{"name": "Remote"}, "absolute_url": "https://x/1"}]}'
        sources.http_get_full = lambda *a, **k: _result(board)

        # Force the shim disabled (as if data_root were unset).
        capture_hooks._SESSION = None
        capture_hooks._SESSION_BUILT = True

        out = sources.fetch_greenhouse("Testco", "testco")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Platform Engineer")
        # No manifests were written anywhere under the (enabled-looking) data root.
        self.assertEqual(self.manifests(), [])


class GreenhouseBoardGroupTests(_CaptureCase):
    def test_board_group_attested_complete(self):
        board = b'{"jobs": [{"title": "SRE", "location": {"name": "Austin, TX"}, ' \
                b'"absolute_url": "https://x/1", "content": "<p>Hi</p>"}, ' \
                b'{"title": "Infra", "location": {"name": "Remote"}, ' \
                b'"absolute_url": "https://x/2", "content": "x"}]}'
        sources.http_get_full = lambda *a, **k: _result(board)

        out = sources.fetch_greenhouse("Testco", "testco")
        self.assertEqual(len(out), 2)

        manifests = self.manifests()
        boards = [m for m in manifests if m.get("operation") == "board"]
        groups = [m for m in manifests if m.get("operation") == "group"]
        self.assertEqual(len(boards), 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(boards[0]["item_count"], 2)
        self.assertEqual(boards[0]["context"]["company"], "testco")
        self.assertTrue(groups[0]["attested_complete"])  # greenhouse attests complete
        self.assertEqual(groups[0]["achieved"], 1)


class WorkdaySearchGroupTests(_CaptureCase):
    def test_multi_request_group_honest_and_not_complete(self):
        page = (b'{"jobPostings": [{"externalPath": "/job/1", '
                b'"title": "Platform Engineer"}, {"externalPath": "/job/2", '
                b'"title": "Infra Engineer"}]}')
        # A short batch (<20) ends each term's paging after one POST.
        sources.http_post_json_full = lambda *a, **k: _result(page)
        sources.http_get_json = lambda *a, **k: {}  # detail fetch → no posting

        sources.fetch_workday("Testco", "testco", "testco.wd5.myworkdayjobs.com",
                              "External", search_terms=["kubernetes", "platform"])

        manifests = self.manifests()
        members = [m for m in manifests if m.get("operation") == "search"]
        groups = [m for m in manifests if m.get("operation") == "group"]
        self.assertEqual(len(members), 2)              # one POST per term
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0]["attested_complete"])   # never complete
        self.assertEqual(groups[0]["achieved"], 2)         # honest member count
        for m in members:
            self.assertEqual(m["context"]["company"], "testco")
            self.assertEqual(m["pagination"]["limit"], 20)


class SmartRecruitersTruncationTests(_CaptureCase):
    def test_truncation_observation_recorded(self):
        # totalFound (5) > returned (2) => the listing is truncated; recorded in
        # the search manifest params, group attested NOT complete.
        body = (b'{"content": [{"id": "1", "name": "SWE", "location": {}}, '
                b'{"id": "2", "name": "Infra", "location": {}}], "totalFound": 5}')
        sources.http_get_full = lambda *a, **k: _result(body)
        sources.http_get_json = lambda *a, **k: {}   # detail → no description
        sources.fetch_smartrecruiters("Testco", "testco")

        searches = [m for m in self.manifests() if m.get("operation") == "search"]
        groups = [m for m in self.manifests() if m.get("operation") == "group"]
        self.assertEqual(len(searches), 1)
        params = searches[0]["request"]["params"]
        self.assertTrue(params["truncated"])
        self.assertEqual(params["total_found"], 5)
        self.assertEqual(params["returned"], 2)
        self.assertFalse(groups[0]["attested_complete"])


class FailedFetchTests(_CaptureCase):
    def test_http_500_is_captured_and_fetcher_still_errors(self):
        sources.http_get_full = lambda *a, **k: _result(
            b"", status=500, ok=False, content_type=None, error="HTTP 500 Server Error")
        with self.assertRaises(Exception):
            sources.fetch_greenhouse("Testco", "testco")

        boards = [m for m in self.manifests() if m.get("operation") == "board"]
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0]["status"], 500)
        self.assertIsNone(boards[0]["payload"])           # empty body → no blob
        self.assertEqual(boards[0]["error"], "HTTP 500 Server Error")


class JobSpyScrapeTests(_CaptureCase):
    class _FakeDF:
        def __init__(self, rows):
            self._rows = rows

        def iterrows(self):
            for i, r in enumerate(self._rows):
                yield i, r

        def __len__(self):
            return len(self._rows)

    def test_serialization_is_deterministic_regardless_of_key_order(self):
        a = self._FakeDF([{"title": "A", "company": "X", "min_amount": 100.0}])
        b = self._FakeDF([{"min_amount": 100.0, "company": "X", "title": "A"}])
        self.assertEqual(aggregators._serialize_jobspy_rows(a),
                         aggregators._serialize_jobspy_rows(b))

    def test_nan_becomes_null(self):
        df = self._FakeDF([{"title": "A", "salary": float("nan")}])
        self.assertIn(b'"salary":null', aggregators._serialize_jobspy_rows(df))

    def test_scrape_capture_writes_manifest_and_exact_bytes(self):
        body = b'[{"company":"X","title":"A"}]'
        capture_hooks.capture_scrape_bytes("jobspy", "jobspy://indeed/US?q=swe",
                                           body, item_count=1)
        scrapes = [m for m in self.manifests() if m.get("operation") == "scrape"]
        self.assertEqual(len(scrapes), 1)
        self.assertEqual(scrapes[0]["source"], "jobspy")
        blobs = BlobStore(self.layout.blobs)
        self.assertEqual(blobs.read(scrapes[0]["payload"]["blob"]), body)


class WriteContainmentTests(_CaptureCase):
    def test_capture_writes_only_under_the_env_data_root(self):
        before = _private_data_files()
        board = b'{"jobs": [{"title": "SRE", "location": {"name": "Remote"}, ' \
                b'"absolute_url": "https://x/1"}]}'
        sources.http_get_full = lambda *a, **k: _result(board)
        sources.fetch_greenhouse("Testco", "testco")

        # Something was written to the isolated temp root ...
        self.assertTrue(list(self.data_root.rglob("manifest.json")))
        # ... and NOTHING new landed in the real private store.
        self.assertEqual(_private_data_files(), before)


# ── two-process concurrent capture (fork; module-level worker) ──
def _concurrent_worker(data_root: str, n: int) -> None:
    sys.path.insert(0, str(_SCRIPTS_DIR))
    os.environ["JOBHUNT_DATA_ROOT"] = data_root
    import capture_hooks as ch
    import sources as sx
    from common import HttpResult as HR
    ch._reset_for_tests()
    board = b'{"jobs": [{"title": "SRE", "location": {"name": "Remote"}, ' \
            b'"absolute_url": "https://x/1"}]}'
    sx.http_get_full = lambda *a, **k: HR(
        url="u", status=200, body=board, headers={}, duration_ms=1, ok=True,
        error=None, method="GET", content_type="application/json")
    for _ in range(n):
        sx.fetch_greenhouse("Testco", "testco")


class ConcurrentCaptureTests(_CaptureCase):
    def test_two_processes_capture_cleanly(self):
        try:
            ctx = multiprocessing.get_context("fork")
        except ValueError:  # pragma: no cover
            self.skipTest("fork start method unavailable")
        n = 8
        procs = [ctx.Process(target=_concurrent_worker, args=(str(self.data_root), n))
                 for _ in range(2)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(30)
            self.assertEqual(p.exitcode, 0)

        manifests = self.manifests()
        # Each fetch_greenhouse writes 1 board + 1 group manifest; unique fetch dirs.
        self.assertEqual(len(manifests), 2 * n * 2)
        fetch_ids = [m["fetch_id"] for m in manifests]
        self.assertEqual(len(set(fetch_ids)), len(fetch_ids))


if __name__ == "__main__":
    unittest.main()
