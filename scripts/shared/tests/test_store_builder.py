"""Materialization machinery: incremental==rebuild, determinism, missing-raw.

Uses a *toy builder* (a reducer over synthetic manifests) to exercise the
library-level fold the real posting builder (Stage 2) will supply. Two contract
properties are asserted: incremental builds equal a full rebuild (even when a
manifest commits late / out of order), and a rebuild is byte-identical run to run.
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

from store import serialization  # noqa: E402
from store.blobs import BlobStore  # noqa: E402
from store.builder import materialize_full, materialize_incremental  # noqa: E402
from store.manifest import build_envelope, write_manifest  # noqa: E402
from store.paths import domain_layout  # noqa: E402


# ── the toy builder ──
def _key(env: dict) -> str | None:
    return env.get("posting_id")


def _reduce(key: str, manifests: list[dict]) -> dict:
    # Deterministic per-entity fold over the entity's full, canonically-sorted
    # manifest history.
    return {
        "key": key,
        "observations": len(manifests),
        "first_seen": manifests[0]["fetched_at"],
        "last_seen": manifests[-1]["fetched_at"],
        "titles": sorted({m["title"] for m in manifests}),
    }


def _m(fetch_id, fetched_at, posting_id, title):
    return {"fetch_id": fetch_id, "fetched_at": fetched_at,
            "posting_id": posting_id, "title": title}


class IncrementalEqualsRebuildTests(unittest.TestCase):
    def test_incremental_equals_full_even_with_late_commit(self):
        all_manifests = [
            _m("20260721T093000Z-000001-a", "2026-07-21T09:30:00Z", "gh-1", "Eng I"),
            _m("20260721T093100Z-000002-b", "2026-07-21T09:31:00Z", "gh-1", "Eng II"),
            _m("20260721T093200Z-000003-c", "2026-07-21T09:32:00Z", "gh-2", "SRE"),
        ]
        full = materialize_full(all_manifests, _key, _reduce)

        # Build #1 processed the later two; the FIRST manifest (older timestamp)
        # commits late and is the only pending item for build #2.
        prior = materialize_full(all_manifests[1:], _key, _reduce)
        late = [all_manifests[0]]
        incremental = materialize_incremental(all_manifests, prior, late,
                                               _key, _reduce)
        self.assertEqual(incremental, full)
        # And the late manifest reordered gh-1's first_seen to the earlier time.
        self.assertEqual(full["gh-1"]["first_seen"], "2026-07-21T09:30:00Z")
        self.assertEqual(full["gh-1"]["observations"], 2)

    def test_order_independent_set_function(self):
        manifests = [
            _m("20260721T093000Z-000001-a", "2026-07-21T09:30:00Z", "gh-1", "A"),
            _m("20260721T093100Z-000002-b", "2026-07-21T09:31:00Z", "gh-1", "B"),
        ]
        a = materialize_full(manifests, _key, _reduce)
        b = materialize_full(list(reversed(manifests)), _key, _reduce)
        self.assertEqual(a, b)


class DeterminismTests(unittest.TestCase):
    def test_rebuild_is_byte_identical(self):
        manifests = [
            _m("20260721T093000Z-000001-a", "2026-07-21T09:30:00Z", "gh-2", "SRE"),
            _m("20260721T093100Z-000002-b", "2026-07-21T09:31:00Z", "gh-1", "Eng"),
        ]
        s1 = serialization.dumps_yaml(materialize_full(manifests, _key, _reduce))
        s2 = serialization.dumps_yaml(materialize_full(manifests, _key, _reduce))
        self.assertEqual(s1, s2)
        # Sorted keys → gh-1 sorts before gh-2 regardless of input order.
        self.assertLess(s1.index("gh-1"), s1.index("gh-2"))


class MissingRawKeepExistingTests(unittest.TestCase):
    """A builder that hits a not-synced-here blob keeps the existing entity."""

    def test_keep_existing_when_blob_absent(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            blobs = BlobStore(layout.blobs)
            dt = datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc)

            # A committed manifest whose payload blob was never synced here.
            missing_sha = "ab" * 32
            env = build_envelope(
                fetch_id="20260721T093000Z-000001-aaaaaa", source="greenhouse",
                operation="jd", request={"url": "u"}, status=200,
                fetched_at=serialization.to_z(dt),
                payload={"blob": missing_sha, "bytes_raw": 10,
                         "content_type": "text/markdown"},
                context={"company": "examplecorp"},
            )
            write_manifest(layout.manifest_path("greenhouse", dt, env["fetch_id"]),
                           env)

            prior_entity = {"key": "gh-1", "jd": "carried-forward-text"}

            # The builder-side rule: byte-needing work degrades to keep-existing.
            def build_one(envelope, existing):
                payload = envelope.get("payload")
                sha = payload["blob"]
                ext = "md"
                if blobs.state(sha, ext) != "present":
                    return existing  # keep-existing, no error
                data = blobs.read(sha, ext)
                return {"key": "gh-1", "jd": data.decode()}

            result = build_one(env, prior_entity)
            self.assertEqual(result, prior_entity)  # unchanged, no exception


if __name__ == "__main__":
    unittest.main()
