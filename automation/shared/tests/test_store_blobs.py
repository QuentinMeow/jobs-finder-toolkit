"""Content-addressed blob store: dedup, refcount audit, verify-on-read, 4 states."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store import blobs as _blobs  # noqa: E402
from store import serialization  # noqa: E402
from store.blobs import BlobCorrupt, BlobStore  # noqa: E402
from store.manifest import audit_refcounts, build_envelope, write_manifest  # noqa: E402
from store.paths import domain_layout  # noqa: E402


def _write_fetch(layout, blobs, fetch_id, dt, payload_bytes, ct="application/json"):
    ref = blobs.write(payload_bytes, ct) if payload_bytes is not None else None
    env = build_envelope(
        fetch_id=fetch_id, source="greenhouse", operation="board",
        request={"url": "u"}, status=200, fetched_at=serialization.to_z(dt),
        payload=ref.as_payload(ct) if ref else None,
        context={"company": "examplecorp"},
    )
    write_manifest(layout.manifest_path("greenhouse", dt, fetch_id), env)
    return ref


class DedupTests(unittest.TestCase):
    def test_write_is_content_addressed_and_dedupes(self):
        with tempfile.TemporaryDirectory() as td:
            blobs = BlobStore(Path(td))
            r1 = blobs.write(b"same bytes", "application/json")
            r2 = blobs.write(b"same bytes", "application/json")
            self.assertEqual(r1.sha256, r2.sha256)
            files = list(Path(td).rglob("*.zst"))
            self.assertEqual(len(files), 1)  # identical content → one blob

    def test_name_is_sha_of_uncompressed_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            blobs = BlobStore(Path(td))
            ref = blobs.write(b"payload", "text/plain")
            self.assertEqual(ref.sha256, _blobs.sha256_hex(b"payload"))
            self.assertTrue(blobs.path_for(ref.sha256, "txt").exists())


class VerifyOnReadTests(unittest.TestCase):
    def test_read_roundtrips(self):
        with tempfile.TemporaryDirectory() as td:
            blobs = BlobStore(Path(td))
            ref = blobs.write(b"hello world", "text/plain")
            self.assertEqual(blobs.read(ref.sha256, "txt"), b"hello world")

    def test_corrupt_blob_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            blobs = BlobStore(Path(td))
            ref = blobs.write(b"authentic", "text/plain")
            # Overwrite the compressed blob with different (still-valid zstd) bytes.
            import zstandard
            tampered = zstandard.ZstdCompressor().compress(b"tampered!")
            blobs.path_for(ref.sha256, "txt").write_bytes(tampered)
            with self.assertRaises(BlobCorrupt):
                blobs.read(ref.sha256, "txt")
            self.assertEqual(blobs.state(ref.sha256, "txt"), _blobs.CORRUPT)


class BlobStateTests(unittest.TestCase):
    def test_four_states(self):
        with tempfile.TemporaryDirectory() as td:
            blobs = BlobStore(Path(td))
            present = blobs.write(b"here", "text/plain")
            self.assertEqual(blobs.state(present.sha256, "txt"), _blobs.PRESENT)

            # not-synced-here: a referenced sha with neither file nor tombstone.
            missing_sha = _blobs.sha256_hex(b"elsewhere")
            self.assertEqual(blobs.state(missing_sha, "txt"),
                             _blobs.NOT_SYNCED_HERE)

            # pruned: a tombstone exists.
            tomb = blobs.tombstone_path(missing_sha)
            tomb.parent.mkdir(parents=True, exist_ok=True)
            tomb.write_text("pruned\n")
            self.assertEqual(blobs.state(missing_sha, "txt"), _blobs.PRUNED)

    def test_state_finds_sha_under_a_different_ext(self):
        # Identity is the uncompressed sha alone: querying state with a different
        # ext must still report present (not a false not-synced-here).
        with tempfile.TemporaryDirectory() as td:
            blobs = BlobStore(Path(td))
            ref = blobs.write(b'{"x": 1}', "application/json")  # stored .json.zst
            self.assertEqual(blobs.state(ref.sha256, "md"), _blobs.PRESENT)
            self.assertEqual(blobs.state(ref.sha256, "txt"), _blobs.PRESENT)
            self.assertEqual(blobs.state(ref.sha256), _blobs.PRESENT)


class RefcountAuditTests(unittest.TestCase):
    def test_refcounts_orphans_and_absent(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            dt = datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc)

            # Two fetches referencing the SAME payload (dedup → refcount 2).
            _write_fetch(layout, blobs, "20260721T093000Z-000001-aaaaaa", dt,
                         b'{"same": 1}')
            _write_fetch(layout, blobs, "20260721T093100Z-000002-bbbbbb",
                         datetime(2026, 7, 21, 9, 31, tzinfo=timezone.utc),
                         b'{"same": 1}')
            shared_sha = _blobs.sha256_hex(b'{"same": 1}')

            # An orphan blob referenced by nobody.
            orphan = blobs.write(b'{"orphan": true}', "application/json")

            report = audit_refcounts(layout, blobs)
            self.assertEqual(report["refcounts"][shared_sha], 2)
            self.assertIn(orphan.sha256, report["orphans"])
            self.assertNotIn(shared_sha, report["orphans"])


if __name__ == "__main__":
    unittest.main()
