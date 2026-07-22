"""Capture API: never-raises, disabled no-op, over-capture, groups, concurrency."""
from __future__ import annotations

import multiprocessing
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store import serialization  # noqa: E402
from store.capture import CaptureSession  # noqa: E402
from store.manifest import iter_manifests  # noqa: E402
from store.paths import domain_layout  # noqa: E402


def _capture_many(data_root: str, n: int) -> None:
    """Worker: capture ``n`` fetches into the store (used by the concurrency test)."""
    sys.path.insert(0, str(SHARED))
    from store.capture import CaptureSession as CS

    session = CS("jobs", Path(data_root))
    for i in range(n):
        session.capture_fetch(
            source="greenhouse", operation="search", request={"url": f"u{i}"},
            status=200, payload_bytes=f"payload-{i}".encode(),
            content_type="text/plain", context={"company": "examplecorp"},
        )


class CaptureBasicsTests(unittest.TestCase):
    def test_capture_writes_manifest_and_blob(self):
        with tempfile.TemporaryDirectory() as td:
            session = CaptureSession("jobs", Path(td), tool_version="t")
            fid = session.capture_fetch(
                source="greenhouse", operation="board", request={"url": "u"},
                status=200, payload_bytes=b'{"x": 1}', content_type="application/json",
                item_count=1, response_headers={"content-type": "application/json"},
                query={"terms": ["swe"], "caps": {"max": 100}},
                pagination={"page": 1}, context={"company": "examplecorp",
                                                 "profile": "profile-01"},
            )
            self.assertIsNotNone(fid)
            layout = domain_layout(Path(td), "jobs")
            manifests = list(iter_manifests(layout))
            self.assertEqual(len(manifests), 1)
            env = manifests[0][1]
            # Over-capture fields are present from day one.
            self.assertEqual(env["item_count"], 1)
            self.assertEqual(env["query"]["caps"]["max"], 100)
            self.assertEqual(env["pagination"]["page"], 1)
            self.assertEqual(env["context"]["profile"], "profile-01")
            self.assertEqual(env["payload"]["bytes_raw"], len(b'{"x": 1}'))

    def test_failed_fetch_is_captured_without_payload(self):
        with tempfile.TemporaryDirectory() as td:
            session = CaptureSession("jobs", Path(td))
            session.capture_fetch(
                source="greenhouse", operation="board", request={"url": "u"},
                status=500, error="boom", context={"company": "examplecorp"},
            )
            env = list(iter_manifests(domain_layout(Path(td), "jobs")))[0][1]
            self.assertEqual(env["status"], 500)
            self.assertIsNone(env["payload"])
            self.assertEqual(env["error"], "boom")


class CaptureNeverRaisesTests(unittest.TestCase):
    def test_internal_failure_warns_and_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            session = CaptureSession("jobs", Path(td))

            class Boom:
                def write(self, *a, **k):
                    raise RuntimeError("disk on fire")

            session._blobs = Boom()  # inject a failure inside capture
            # The caller must survive with only a warning (no exception).
            fid = session.capture_fetch(
                source="greenhouse", operation="board", request={"url": "u"},
                status=200, payload_bytes=b"data", content_type="text/plain",
                context={"company": "examplecorp"},
            )
            self.assertIsNone(fid)

    def test_disabled_session_noops(self):
        session = CaptureSession("jobs", None)
        self.assertFalse(session.enabled)
        self.assertIsNone(session.capture_fetch(
            source="greenhouse", operation="board", request={}, status=200))

    def test_invalid_domain_disables_never_raises(self):
        # Construction with an invalid domain slug disables the session with a
        # warning instead of raising SlugError (the never-raise guarantee).
        with tempfile.TemporaryDirectory() as td:
            session = CaptureSession("Bad Domain!", Path(td))
            self.assertFalse(session.enabled)
            self.assertIsNone(session.capture_fetch(
                source="greenhouse", operation="board", request={}, status=200))


class GroupTests(unittest.TestCase):
    def test_group_writes_members_and_attestation(self):
        with tempfile.TemporaryDirectory() as td:
            session = CaptureSession("jobs", Path(td))
            with session.group("20260721T093000Z-board-examplecorp",
                               expected=2) as group:
                group.capture_fetch(source="greenhouse", operation="board",
                                    request={"url": "board"}, status=200,
                                    payload_bytes=b"[]", content_type="application/json",
                                    context={"company": "examplecorp"})
                group.capture_fetch(source="greenhouse", operation="jd",
                                    request={"url": "jd"}, status=200,
                                    payload_bytes=b"# jd", content_type="text/markdown",
                                    context={"company": "examplecorp"})
                group.attest(complete=True)

            layout = domain_layout(Path(td), "jobs")
            envs = [e for _p, e in iter_manifests(layout)]
            members = [e for e in envs if e.get("operation") != "group"]
            groups = [e for e in envs if e.get("operation") == "group"]
            self.assertEqual(len(members), 2)
            self.assertEqual(len(groups), 1)
            g = groups[0]
            self.assertEqual(g["achieved"], 2)
            self.assertTrue(g["attested_complete"])
            self.assertEqual(len(g["members"]), 2)
            for m in members:
                self.assertEqual(m["group_id"],
                                 "20260721T093000Z-board-examplecorp")


class ConcurrentCaptureTests(unittest.TestCase):
    def test_two_processes_capture_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            # Fork avoids re-importing this test module in the child.
            try:
                ctx = multiprocessing.get_context("fork")
            except ValueError:  # pragma: no cover (non-fork platforms)
                self.skipTest("fork start method unavailable")
            n = 15
            procs = [ctx.Process(target=_capture_many, args=(td, n))
                     for _ in range(2)]
            for p in procs:
                p.start()
            for p in procs:
                p.join(30)
                self.assertEqual(p.exitcode, 0)

            layout = domain_layout(Path(td), "jobs")
            fetch_ids = [e["fetch_id"] for _p, e in iter_manifests(layout)]
            # Every capture committed a unique fetch directory — no lock, no clash.
            self.assertEqual(len(fetch_ids), 2 * n)
            self.assertEqual(len(set(fetch_ids)), 2 * n)


if __name__ == "__main__":
    unittest.main()
