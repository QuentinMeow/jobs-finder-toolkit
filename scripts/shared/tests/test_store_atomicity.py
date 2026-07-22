"""Atomic write discipline, torn-tail JSONL tolerance, and crash-injection.

Proves the store-core write-discipline promises at the library level: a reader
never sees a half-written file; a JSONL reader tolerates a torn final line; and a
crash between the blob write and the manifest write leaves readable debris that
readers skip (the manifest is the commit marker).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store import atomic, serialization  # noqa: E402
from store.blobs import BlobStore  # noqa: E402
from store.manifest import build_envelope, iter_manifests, write_manifest  # noqa: E402
from store.paths import domain_layout  # noqa: E402


class AtomicWriteTests(unittest.TestCase):
    def test_write_bytes_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sub" / "file.json"
            atomic.atomic_write_text(p, "hello\n")
            self.assertEqual(p.read_text(), "hello\n")

    def test_no_temp_files_left_behind(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "file.txt"
            atomic.atomic_write_text(p, "x")
            leftovers = [q.name for q in Path(td).iterdir() if q.name != "file.txt"]
            self.assertEqual(leftovers, [])


class JsonlTornTailTests(unittest.TestCase):
    def test_clean_file_reads_all(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            atomic.append_line(p, serialization.dumps_jsonl_line({"n": 1}))
            atomic.append_line(p, serialization.dumps_jsonl_line({"n": 2}))
            self.assertEqual(atomic.read_jsonl(p), [{"n": 1}, {"n": 2}])

    def test_torn_final_line_without_newline_is_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            atomic.append_line(p, serialization.dumps_jsonl_line({"n": 1}))
            # Simulate a crash mid-append: a partial line with no terminator.
            with open(p, "a", encoding="utf-8") as fh:
                fh.write('{"n": 2, "part')
            self.assertEqual(atomic.read_jsonl(p), [{"n": 1}])

    def test_terminated_but_corrupt_final_line_is_tolerated(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            atomic.append_line(p, serialization.dumps_jsonl_line({"n": 1}))
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("{not json}\n")  # a fully-written but corrupt final line
            self.assertEqual(atomic.read_jsonl(p), [{"n": 1}])

    def test_interior_corruption_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('{"n": 1}\n')
                fh.write("GARBAGE\n")       # interior — real corruption
                fh.write('{"n": 3}\n')
            with self.assertRaises(ValueError):
                atomic.read_jsonl(p)


class TornTailRepairTests(unittest.TestCase):
    """The design's 'next build repairs it by truncation' promise, made real."""

    def test_repair_truncates_torn_tail(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            atomic.append_line(p, serialization.dumps_jsonl_line({"n": 1}))
            with open(p, "a", encoding="utf-8") as fh:
                fh.write('{"n": 2, "part')  # torn: no terminator
            self.assertTrue(atomic.repair_jsonl(p))
            self.assertEqual(atomic.read_jsonl(p), [{"n": 1}])
            self.assertFalse(atomic.repair_jsonl(p))  # idempotent on a clean file

    def test_append_after_torn_tail_does_not_merge(self):
        # Reviewer scenario: torn tail + append then read yields BOTH complete
        # records, minus only the genuinely-torn partial, and nothing raises.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            atomic.append_line(p, serialization.dumps_jsonl_line({"n": 1}))
            with open(p, "a", encoding="utf-8") as fh:
                fh.write('{"n": 2, "torn')  # partial, no newline
            atomic.append_line(p, serialization.dumps_jsonl_line({"n": 3}))
            self.assertEqual(atomic.read_jsonl(p), [{"n": 1}, {"n": 3}])

    def test_repair_whole_file_that_is_a_single_torn_line(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('{"n": 1, "torn')  # no newline at all
            self.assertTrue(atomic.repair_jsonl(p))
            self.assertEqual(atomic.read_jsonl(p), [])


class CrashInjectionTests(unittest.TestCase):
    """Dying between the blob write and the manifest write → skippable debris."""

    def test_debris_skipped_and_blob_survives(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            dt = datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc)

            # A committed fetch (blob + manifest).
            good_bytes = b'{"ok": true}'
            ref = blobs.write(good_bytes, "application/json")
            env = build_envelope(
                fetch_id="20260721T093000Z-000001-aaaaaa", source="greenhouse",
                operation="board", request={"url": "u"}, status=200,
                fetched_at=serialization.to_z(dt),
                payload=ref.as_payload("application/json"),
                context={"company": "examplecorp"},
            )
            write_manifest(layout.manifest_path("greenhouse", dt, env["fetch_id"]), env)

            # A CRASHED fetch: the blob landed, but the manifest never did.
            crash_bytes = b'{"partial": true}'
            crash_ref = blobs.write(crash_bytes, "application/json")
            crash_dir = layout.fetch_dir("greenhouse", dt,
                                         "20260721T093000Z-000002-bbbbbb")
            crash_dir.mkdir(parents=True, exist_ok=True)  # dir exists, no manifest.json

            manifests = list(iter_manifests(layout))
            self.assertEqual(len(manifests), 1)  # debris dir skipped
            self.assertEqual(manifests[0][1]["fetch_id"],
                             "20260721T093000Z-000001-aaaaaa")
            # The crashed blob is NOT lost — capture-before-parse means the bytes
            # are on disk and recoverable.
            self.assertEqual(blobs.read(crash_ref.sha256, "json"), crash_bytes)


if __name__ == "__main__":
    unittest.main()
