"""Offline regressions for bounded, tenant-local Workday detail recovery."""
from __future__ import annotations

import json
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import common  # noqa: E402
import snapshot  # noqa: E402
import sources  # noqa: E402
from common import HttpResult  # noqa: E402


def _response(body: dict | None = None, *, status=200, headers=None,
              error=None) -> HttpResult:
    payload = json.dumps(body or {}).encode() if status == 200 else b""
    return HttpResult(
        url="https://example.test/detail",
        status=status,
        body=payload,
        headers=headers or {"content-type": "application/json"},
        duration_ms=1,
        ok=200 <= status < 300,
        error=error,
        method="GET",
        content_type="application/json",
    )


def _detail(title: str) -> dict:
    return {"jobPostingInfo": {
        "title": title,
        "location": "Seattle, WA",
        "jobDescription": "<p>Build reliable systems.</p>",
        "startDate": "2026-08-01",
    }}


class RetryAfterParsingTests(unittest.TestCase):
    def test_delta_seconds_and_case_insensitive_header(self):
        self.assertEqual(
            common.retry_after_seconds({"rEtRy-AfTeR": "2"}, ceiling=10), 2.0)

    def test_http_date_uses_caller_clock(self):
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        header = format_datetime(now + timedelta(seconds=7), usegmt=True)
        self.assertEqual(
            common.retry_after_seconds({"Retry-After": header}, now=now,
                                       ceiling=10),
            7.0,
        )

    def test_hostile_values_are_bounded_and_invalid_values_fall_back(self):
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        far_future = format_datetime(now + timedelta(days=365), usegmt=True)
        self.assertEqual(
            common.retry_after_seconds({"Retry-After": "999999"}, ceiling=10),
            10.0,
        )
        self.assertEqual(
            common.retry_after_seconds({"Retry-After": far_future}, now=now,
                                       ceiling=10),
            10.0,
        )
        self.assertIsNone(
            common.retry_after_seconds({"Retry-After": "not-a-delay"}, now=now))


class TenantPacerTests(unittest.TestCase):
    def test_request_starts_are_spaced(self):
        clock = {"now": 0.0}
        sleeps: list[float] = []

        def sleep(delay):
            sleeps.append(delay)
            clock["now"] += delay

        pacer = sources._WorkdayTenantPacer(
            0.25, sleep=sleep, monotonic=lambda: clock["now"])
        pacer.wait()
        pacer.wait()
        self.assertEqual(sleeps, [0.25])

    def test_one_tenants_deferral_does_not_delay_another(self):
        clock = {"now": 0.0}
        sleeps: list[float] = []

        def monotonic():
            return clock["now"]

        def sleep(delay):
            sleeps.append(delay)
            clock["now"] += delay

        tenant_a = sources._WorkdayTenantPacer(
            0, sleep=sleep, monotonic=monotonic)
        tenant_b = sources._WorkdayTenantPacer(
            0, sleep=sleep, monotonic=monotonic)

        tenant_a.defer(3)
        tenant_b.wait()
        self.assertEqual(sleeps, [])
        tenant_a.wait()
        self.assertEqual(sleeps, [3.0])


class WorkdayRecoveryTests(unittest.TestCase):
    def _run(self, paths):
        return sources._fetch_workday_details(
            "Testco", "testco.example", "External",
            "https://testco.example/wday/cxs/testco/External", paths)

    def test_recovery_requests_only_missed_paths_and_emits_each_once(self):
        calls: list[str] = []
        retry_args: list[int | None] = []

        def get(url, **_kwargs):
            path = url.rsplit("/job/", 1)[-1]
            calls.append(path)
            retry_args.append(_kwargs.get("retries"))
            if path == "2" and calls.count("2") == 1:
                return _response(status=429, headers={"Retry-After": "0"},
                                 error="HTTP 429 Too Many Requests")
            return _response(_detail(f"Engineer {path}"))

        with mock.patch.object(sources, "http_get_full", side_effect=get), \
                mock.patch.object(sources, "_WORKDAY_DETAIL_PACE_SECONDS", 0):
            postings, failures, attempts = self._run(
                ["/job/1", "/job/2", "/job/2"])

        self.assertEqual(calls, ["1", "2", "2"])
        self.assertEqual(retry_args, [0, 0, 0])
        self.assertEqual([p.title for p in postings], ["Engineer 1", "Engineer 2"])
        self.assertEqual(failures, [])
        self.assertEqual(attempts, 3)

    def test_incomplete_warning_remains_durable_in_snapshot_errors(self):
        warning = (
            "workday:Testco: coverage=incomplete; 1 of 2 detail fetches failed "
            "after bounded recovery; those postings were not inspected"
        )
        with TemporaryDirectory() as tmp:
            path, _latest = snapshot.write_snapshot(
                Path(tmp),
                profile="example",
                stage=1,
                fetched_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
                source_selection={"n_companies": 1, "aggregators": []},
                postings=[],
                errors=[warning],
            )
            persisted = snapshot.load_snapshot(path)
        self.assertEqual(persisted["errors"], [warning])
        self.assertIn("coverage=incomplete", persisted["errors"][0])

    def test_persistent_failures_stop_after_finite_rounds(self):
        calls = 0

        def get(_url, **_kwargs):
            nonlocal calls
            calls += 1
            return _response(status=503, error="HTTP 503 Service Unavailable")

        with mock.patch.object(sources, "http_get_full", side_effect=get), \
                mock.patch.object(sources, "_WORKDAY_DETAIL_PACE_SECONDS", 0):
            postings, failures, attempts = self._run(["/job/1"])

        self.assertEqual(postings, [])
        self.assertEqual(calls, sources._WORKDAY_DETAIL_RECOVERY_ROUNDS + 1)
        self.assertEqual(attempts, calls)
        self.assertEqual(len(failures), 1)
        self.assertIn("HTTP 503", failures[0])

    def test_retry_after_seconds_is_applied_and_capped_before_recovery(self):
        responses = [
            _response(status=429, headers={"Retry-After": "999"},
                      error="HTTP 429 Too Many Requests"),
            _response(_detail("Recovered Engineer")),
        ]
        clock = {"now": 0.0}
        sleeps: list[float] = []

        def sleep(delay):
            sleeps.append(delay)
            clock["now"] += delay

        with mock.patch.object(sources, "http_get_full",
                               side_effect=lambda *_a, **_k: responses.pop(0)), \
                mock.patch.object(sources, "_WORKDAY_DETAIL_PACE_SECONDS", 0), \
                mock.patch.object(sources,
                                  "_WORKDAY_RETRY_AFTER_CEILING_SECONDS", 3), \
                mock.patch.object(sources.time, "monotonic",
                                  side_effect=lambda: clock["now"]), \
                mock.patch.object(sources.time, "sleep", side_effect=sleep):
            postings, failures, attempts = self._run(["/job/1"])

        self.assertEqual(sleeps, [3.0])
        self.assertEqual(attempts, 2)
        self.assertEqual(failures, [])
        self.assertEqual([p.title for p in postings], ["Recovered Engineer"])

    def test_local_fixture_429_then_200_emits_one_posting(self):
        class Handler(BaseHTTPRequestHandler):
            calls = 0

            def do_GET(self):  # noqa: N802 — stdlib handler API
                type(self).calls += 1
                if type(self).calls == 1:
                    self.send_response(429)
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    return
                body = json.dumps(_detail("Recovered Engineer")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with mock.patch.object(sources, "_WORKDAY_DETAIL_PACE_SECONDS", 0):
                postings, failures, attempts = sources._fetch_workday_details(
                    "Testco", "testco.example", "External", base, ["/job/1"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(Handler.calls, 2)
        self.assertEqual(attempts, 2)
        self.assertEqual(failures, [])
        self.assertEqual([p.title for p in postings], ["Recovered Engineer"])


if __name__ == "__main__":
    unittest.main()
