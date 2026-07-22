"""Generate the tracked fictional fixture store under ``examples/data/``.

Deterministic by construction: fixed timestamps, fixed content, the canonical
serializer, and fixed fetch-id suffixes — so regenerating is byte-identical (run
twice, ``git status`` is unchanged after the second run). Byte-identical regen is
guaranteed **per-machine / per-zstandard-version only**: the compressed ``.zst``
blob bytes are a function of the installed zstd build, so a different zstandard
version may produce different compressed bytes — but the blob NAMES (sha256 of the
UNCOMPRESSED bytes) and every text artifact (manifests, derived/index/state YAML
and JSONL) stay identical across versions. Entirely the fictional Jordan-Rivers
universe (``examplecorp``, ``profile-01``, ``acct-01``, only ``example.com`` email
localparts) — no real employer, name, or dated personal data.

The one ``jobs`` domain exercises all five zones and every schema:
- raw: a two-member fetch group (board + JD) with an attested-complete group
  manifest, a captured **failed** fetch, and one **not-synced-here** manifest
  (blob deliberately absent — the normal multi-laptop state);
- derived: one posting entity (``gh-1234567``) with its JD;
- index: ``postings.jsonl`` and ``by-day/…`` with header lines;
- annotations: one human-verified annotation;
- state: build ledger, key registry, identifiers, cursors.

Usage:
    .venv/bin/python scripts/store/generate_fixture_store.py
    .venv/bin/python scripts/store/generate_fixture_store.py --root examples/data
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from store import manifest as _manifest  # noqa: E402
from store import serialization  # noqa: E402
from store.atomic import append_line, atomic_write_text  # noqa: E402
from store.blobs import BlobStore, ext_for_content_type, sha256_hex  # noqa: E402
from store.paths import domain_layout  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "examples" / "data"

DOMAIN = "jobs"
GROUP_ID = "20260714T093000Z-board-examplecorp"
COMPANY = "examplecorp"
ENTITY_KEY = "gh-1234567"

# Fixed fetch ids (match the FETCH_ID pattern) and their capture times.
FETCH_BOARD = "20260714T093000Z-000001-a1b2c3"
FETCH_JD = "20260714T093100Z-000002-b2c3d4"
FETCH_GROUP = "20260714T093200Z-000003-c3d4e5"
FETCH_FAILED = "20260715T093000Z-000004-d4e5f6"
FETCH_NOT_SYNCED = "20260716T093000Z-000005-e5f6a7"

TS_BOARD = "2026-07-14T09:30:00Z"
TS_JD = "2026-07-14T09:31:00Z"
TS_GROUP = "2026-07-14T09:32:00Z"
TS_FAILED = "2026-07-15T09:30:00Z"
TS_NOT_SYNCED = "2026-07-16T09:30:00Z"

TOOL_VERSION = "capture-lib 1 / fixture-generator"
INDEX_NOTE = ("machine-generated — do not cat into context; use query_postings.py")

BOARD_PAYLOAD = {
    "jobs": [
        {
            "id": "1234567",
            "title": "Software Engineer, Control Plane",
            "location": "Austin, TX (Hybrid)",
            "absolute_url": "https://boards.greenhouse.io/examplecorp/jobs/1234567",
            "updated_at": "2026-07-12T00:00:00Z",
        }
    ]
}

JD_MARKDOWN = (
    "# Software Engineer, Control Plane\n"
    "\n"
    "ExampleCorp is hiring a Software Engineer on the Control Plane team to build\n"
    "the scheduling and reconciliation layer of our platform.\n"
    "\n"
    "Location: Austin, TX (Hybrid).\n"
)

# Content for the deliberately-absent (not-synced-here) blob.
NOT_SYNCED_MARKDOWN = "# Placeholder JD not synced to this machine\n"


def _write_manifest(layout, source, dt_str, fetch_id, envelope) -> None:
    dt = serialization.parse_z(dt_str)
    _manifest.write_manifest(layout.manifest_path(source, dt, fetch_id), envelope)


def _generate_raw(layout, blobstore: BlobStore) -> None:
    # Group member 1: the board listing (attested-complete source: greenhouse).
    board_bytes = serialization.dumps_json(BOARD_PAYLOAD).encode("utf-8")
    board_ref = blobstore.write(board_bytes, "application/json")
    board_env = _manifest.build_envelope(
        fetch_id=FETCH_BOARD, source="greenhouse", operation="board",
        request={"url": "https://boards.greenhouse.io/v1/boards/examplecorp/jobs",
                 "params": {"content": "true"}},
        status=200, fetched_at=TS_BOARD, tool_version=TOOL_VERSION, duration_ms=412,
        response_headers={"content-type": "application/json"}, item_count=1,
        query={"terms": [], "caps": {}},
        pagination={"page": 1, "has_more": False},
        payload=board_ref.as_payload("application/json"),
        context={"company": COMPANY, "profile": "profile-01"},
        group_id=GROUP_ID,
        group={"group_id": GROUP_ID, "expected": 2, "member": 1,
               "attested_complete": None},
    )
    _write_manifest(layout, "greenhouse", TS_BOARD, FETCH_BOARD, board_env)

    # Group member 2: the JD page.
    jd_bytes = JD_MARKDOWN.encode("utf-8")
    jd_ref = blobstore.write(jd_bytes, "text/markdown")
    jd_env = _manifest.build_envelope(
        fetch_id=FETCH_JD, source="greenhouse", operation="jd",
        request={"url": "https://boards.greenhouse.io/examplecorp/jobs/1234567"},
        status=200, fetched_at=TS_JD, tool_version=TOOL_VERSION, duration_ms=180,
        response_headers={"content-type": "text/html"},
        payload=jd_ref.as_payload("text/markdown"),
        context={"company": COMPANY, "profile": "profile-01"},
        group_id=GROUP_ID,
        group={"group_id": GROUP_ID, "expected": 2, "member": 2,
               "attested_complete": None},
    )
    _write_manifest(layout, "greenhouse", TS_JD, FETCH_JD, jd_env)

    # Group attestation (greenhouse returns whole boards → attested complete).
    group_env = _manifest.build_group_manifest(
        fetch_id=FETCH_GROUP, group_id=GROUP_ID, source="greenhouse",
        fetched_at=TS_GROUP, expected=2, achieved=2, attested_complete=True,
        members=[FETCH_BOARD, FETCH_JD], tool_version=TOOL_VERSION,
        context={"company": COMPANY, "profile": "profile-01"},
    )
    _write_manifest(layout, "greenhouse", TS_GROUP, FETCH_GROUP, group_env)

    # A captured FAILED fetch (HTTP 500, empty body) — failure history is data.
    failed_env = _manifest.build_envelope(
        fetch_id=FETCH_FAILED, source="greenhouse", operation="board",
        request={"url": "https://boards.greenhouse.io/v1/boards/examplecorp/jobs"},
        status=500, fetched_at=TS_FAILED, tool_version=TOOL_VERSION, duration_ms=90,
        response_headers={}, payload=None,
        context={"company": COMPANY, "profile": "profile-01"},
        error="upstream 500 (empty body)",
    )
    _write_manifest(layout, "greenhouse", TS_FAILED, FETCH_FAILED, failed_env)

    # A NOT-SYNCED-HERE manifest: payload recorded, blob deliberately NOT written
    # (the normal multi-laptop state — informational, never an error).
    ns_bytes = NOT_SYNCED_MARKDOWN.encode("utf-8")
    ns_sha = sha256_hex(ns_bytes)
    ns_payload = {"blob": ns_sha, "bytes_raw": len(ns_bytes),
                  "content_type": "text/markdown"}
    ns_env = _manifest.build_envelope(
        fetch_id=FETCH_NOT_SYNCED, source="greenhouse", operation="jd",
        request={"url": "https://boards.greenhouse.io/examplecorp/jobs/7654321"},
        status=200, fetched_at=TS_NOT_SYNCED, tool_version=TOOL_VERSION,
        response_headers={"content-type": "text/html"}, payload=ns_payload,
        context={"company": COMPANY, "profile": "profile-01"},
    )
    _write_manifest(layout, "greenhouse", TS_NOT_SYNCED, FETCH_NOT_SYNCED, ns_env)


def _generate_derived(layout) -> None:
    entity_dir = layout.derived / "postings" / COMPANY / ENTITY_KEY
    jd_text = JD_MARKDOWN
    jd_hash = sha256_hex(jd_text.encode("utf-8"))
    posting = {
        "schema_version": 1,
        "key": ENTITY_KEY,
        "company": COMPANY,
        "source_ids": [
            {"source": "greenhouse", "board_token": "examplecorp",
             "id": "1234567",
             "url": "https://boards.greenhouse.io/examplecorp/jobs/1234567"},
        ],
        "title": "Software Engineer, Control Plane",
        "location": "Austin, TX (Hybrid)",
        "first_seen": TS_BOARD,
        "last_seen": TS_BOARD,
        "facts": {"posted_at": "2026-07-12", "workplace_raw": "hybrid"},
        "opinions": {
            "visa": {"label": "unclear", "hits": [],
                     "by": "visa.py@fixture", "from": FETCH_BOARD},
            "workplace": {"value": "hybrid", "by": "location.py@fixture",
                          "from": FETCH_BOARD},
        },
        "provenance": {
            "built_by": "fixture-generator",
            "fetch_ids": [FETCH_BOARD, FETCH_JD],
        },
        "jd": {"file": "jd.md", "content_hash": jd_hash, "fetched_verbatim": True},
    }
    atomic_write_text(entity_dir / "posting.yaml", serialization.dumps_yaml(posting))
    atomic_write_text(entity_dir / "jd.md", jd_text)

    # events.jsonl — the entity's biography (idempotent identities).
    events_path = entity_dir / "events.jsonl"
    for event in (
        {"entity": ENTITY_KEY, "fetch": FETCH_BOARD, "type": "first_seen",
         "at": TS_BOARD},
        {"entity": ENTITY_KEY, "fetch": FETCH_JD, "type": "jd_fetched",
         "at": TS_JD},
    ):
        append_line(events_path, serialization.dumps_jsonl_line(event))


def _generate_index(layout) -> None:
    postings = layout.index / "postings.jsonl"
    header = {"_schema": 1, "built_at": TS_GROUP, "note": INDEX_NOTE}
    row = {"key": ENTITY_KEY, "company": COMPANY,
           "title": "Software Engineer, Control Plane",
           "location": "Austin, TX (Hybrid)", "first_seen": TS_BOARD,
           "last_seen": TS_BOARD, "visa": "unclear", "workplace": "hybrid",
           "seq": 2}
    append_line(postings, serialization.dumps_jsonl_line(header))
    append_line(postings, serialization.dumps_jsonl_line(row))

    by_day = layout.index / "by-day" / "2026-07-14.jsonl"
    day_header = {"_schema": 1, "built_at": TS_GROUP, "note": INDEX_NOTE}
    day_row = {"key": ENTITY_KEY, "type": "first_seen", "at": TS_BOARD}
    append_line(by_day, serialization.dumps_jsonl_line(day_header))
    append_line(by_day, serialization.dumps_jsonl_line(day_row))


def _generate_annotations(layout) -> None:
    ann = {
        "schema_version": 1,
        "key": ENTITY_KEY,
        "verified_by": "human",
        "verified_at": "2026-07-14",
        "facts": {"workplace": "hybrid"},
        "note": "JD text confirms hybrid in Austin.",
    }
    atomic_write_text(layout.annotations / f"{ENTITY_KEY}.yaml",
                      serialization.dumps_yaml(ann))


def _generate_state(layout) -> None:
    # Build ledger: build 1 processed the group + failed fetch; build 2 the
    # not-synced manifest (the builder tolerates the absent blob).
    ledger_lines = [
        {"fetch_id": FETCH_BOARD, "seq": 1, "fetched_at": TS_BOARD,
         "built_at": "2026-07-14T10:00:00Z", "clock_ok": True},
        {"fetch_id": FETCH_JD, "seq": 2, "fetched_at": TS_JD,
         "built_at": "2026-07-14T10:00:00Z", "clock_ok": True},
        {"fetch_id": FETCH_GROUP, "seq": 3, "fetched_at": TS_GROUP,
         "built_at": "2026-07-14T10:00:00Z", "clock_ok": True},
        {"fetch_id": FETCH_FAILED, "seq": 4, "fetched_at": TS_FAILED,
         "built_at": "2026-07-15T10:00:00Z", "clock_ok": True},
        {"fetch_id": FETCH_NOT_SYNCED, "seq": 5, "fetched_at": TS_NOT_SYNCED,
         "built_at": "2026-07-16T10:00:00Z", "clock_ok": True},
    ]
    for line in ledger_lines:
        append_line(layout.build_ledger, serialization.dumps_jsonl_line(line))

    key_registry = {
        "schema_version": 1,
        "keys": {ENTITY_KEY: {"pinned": True, "reason": "annotation", "aliases": []}},
    }
    atomic_write_text(layout.key_registry, serialization.dumps_yaml(key_registry))

    identifiers = {
        "schema_version": 1,
        "profile": {"profile-01": "Jordan Rivers (example profile)"},
        "account": {"acct-01": "jordan.rivers@example.com"},
    }
    atomic_write_text(layout.identifiers, serialization.dumps_yaml(identifiers))

    cursors = {
        "schema_version": 1,
        "cursors": {"shortlist-review": {"seq": 2,
                                         "updated_at": "2026-07-14T10:05:00Z"}},
    }
    atomic_write_text(layout.cursors, serialization.dumps_yaml(cursors))


def generate(root: Path) -> None:
    """Generate the whole fixture store under ``root`` (wipes it first)."""
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    layout = domain_layout(root, DOMAIN)
    blobstore = BlobStore(layout.blobs)
    _generate_raw(layout, blobstore)
    _generate_derived(layout)
    _generate_index(layout)
    _generate_annotations(layout)
    _generate_state(layout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help=f"target data root (default: {DEFAULT_ROOT})")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    generate(root)
    print(f"fixture store generated at {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
