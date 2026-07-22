"""Generate the tracked fictional fixture store under ``examples/data/``.

**Single source of truth:** the raw/annotations/state-identity zones are written
here by hand, but the ``derived/`` and ``index/`` zones are produced by RUNNING THE
REAL BUILDER (``build_postings.py``) over the fixture raw — so the fixture can never
drift from builder output. Regenerating is deterministic per-machine / per-zstandard
version: text artifacts (manifests, derived/index/state) are byte-stable; only the
compressed ``.zst`` blob bytes depend on the installed zstd (their NAMES, the sha256
of the uncompressed bytes, stay identical). Wholly the fictional Jordan-Rivers
universe (``examplecorp`` / ``profile-01`` / ``example.com``) — no real employer,
name, URL, or dated personal data.

The one ``jobs`` domain exercises every zone and the Stage-2 builder features the
task requires:
- a greenhouse posting (``gh-1234567``) with a human annotation and a PINNED key;
- a CHANGED-field event history (its location changes across two board fetches);
- a WEAK-identity row (a content-keyed ``ck-…`` aggregator row with no stable URL);
- a SUPPRESSED row (a structurally-foreign scrape row in the review queue);
- a NOT-SYNCED-HERE manifest (payload recorded, blob deliberately absent).

Usage:
    .venv/bin/python scripts/store/generate_fixture_store.py
    .venv/bin/python scripts/store/generate_fixture_store.py --root examples/data
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from store import manifest as _manifest  # noqa: E402
from store import serialization  # noqa: E402
from store.atomic import atomic_write_text, read_jsonl  # noqa: E402
from store.blobs import BlobStore, sha256_hex  # noqa: E402
from store.paths import domain_layout  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "examples" / "data"
BUILDER = (REPO_ROOT / ".agents" / "skills" / "job-search" / "scripts"
           / "build_postings.py")

DOMAIN = "jobs"
COMPANY = "examplecorp"
TOOL_VERSION = "capture-lib 1 / fixture-generator"
# Deterministic build-time value stamped into the ledger (the builder uses wall
# clock; we normalize it so the tracked fixture is byte-stable across regens).
FIXED_BUILT_AT = "2026-07-16T10:00:00Z"

# Fixed fetch ids + capture times (match the FETCH_ID pattern).
F_BOARD1 = "20260714T093000Z-000001-a1b2c3"
F_BOARD2 = "20260715T093000Z-000002-b2c3d4"
F_SCRAPE = "20260714T094000Z-000003-c3d4e5"
F_NOTSYNC = "20260716T093000Z-000004-d4e5f6"
T_BOARD1 = "2026-07-14T09:30:00Z"
T_BOARD2 = "2026-07-15T09:30:00Z"
T_SCRAPE = "2026-07-14T09:40:00Z"
T_NOTSYNC = "2026-07-16T09:30:00Z"


def _gh_job(jid, title, loc, content):
    return {"id": jid, "title": title, "location": {"name": loc},
            "absolute_url": f"https://boards.greenhouse.io/{COMPANY}/jobs/{jid}",
            "content": content, "first_published": "2026-07-12T00:00:00Z",
            "company_name": "ExampleCorp", "metadata": []}


GH_DAY1 = {"jobs": [
    _gh_job("1234567", "Software Engineer, Control Plane", "Austin, TX (Hybrid)",
            "<p>Build the scheduling and reconciliation control plane. "
            "Hybrid in Austin.</p>"),
    _gh_job("7654321", "Backend Engineer", "Remote, US",
            "<p>Backend role, remote in the United States.</p>"),
]}
# Day 2: gh-1234567's location changes Austin -> Seattle (a changed event).
GH_DAY2 = {"jobs": [
    _gh_job("1234567", "Software Engineer, Control Plane", "Seattle, WA (Hybrid)",
            "<p>Build the scheduling and reconciliation control plane. "
            "Hybrid in Seattle.</p>"),
    _gh_job("7654321", "Backend Engineer", "Remote, US",
            "<p>Backend role, remote in the United States.</p>"),
]}

SCRAPE = {"jobs": [
    {"id": 501, "url": "https://jobicy.com/jobs/501-platform", "jobTitle": "Platform Engineer",
     "companyName": "RemoteWorks", "jobGeo": "USA",
     "jobDescription": "<p>Platform engineering, US remote.</p>",
     "pubDate": "2026-07-14 00:00:00"},
    # No stable URL -> WEAK content key.
    {"id": 502, "url": "", "jobTitle": "Data Engineer", "companyName": "GhostWorks",
     "jobGeo": "United States", "jobDescription": "<p>Data role.</p>",
     "pubDate": "2026-07-14 00:00:00"},
    # Structurally foreign -> SUPPRESSED (not materialized).
    {"id": 503, "url": "https://jobicy.com/jobs/503-uk", "jobTitle": "UK Engineer",
     "companyName": "LondonCo", "jobGeo": "London, United Kingdom",
     "jobDescription": "<p>UK role.</p>", "pubDate": "2026-07-14 00:00:00"},
]}

# The deliberately-absent (not-synced-here) blob's content.
NOT_SYNCED_MARKDOWN = "# JD not synced to this machine\n"


def _write_manifest(layout, source, dt_str, fetch_id, envelope):
    dt = serialization.parse_z(dt_str)
    _manifest.write_manifest(layout.manifest_path(source, dt, fetch_id), envelope)


def _generate_raw(layout, blobstore):
    # Greenhouse board — day 1 and day 2 (attested-complete source).
    for fid, ts, payload in ((F_BOARD1, T_BOARD1, GH_DAY1),
                             (F_BOARD2, T_BOARD2, GH_DAY2)):
        body = serialization.dumps_json(payload).encode("utf-8")
        ref = blobstore.write(body, "application/json")
        env = _manifest.build_envelope(
            fetch_id=fid, source="greenhouse", operation="board",
            request={"url": f"https://boards-api.greenhouse.io/v1/boards/{COMPANY}/jobs",
                     "params": {"content": "true"}},
            status=200, fetched_at=ts, tool_version=TOOL_VERSION, item_count=2,
            response_headers={"content-type": "application/json"},
            payload=ref.as_payload("application/json"),
            context={"company": COMPANY, "profile": "profile-01"})
        _write_manifest(layout, "greenhouse", ts, fid, env)

    # Jobicy aggregator scrape (US url-keyed + weak content-keyed + foreign suppressed).
    body = serialization.dumps_json(SCRAPE).encode("utf-8")
    ref = blobstore.write(body, "application/json")
    env = _manifest.build_envelope(
        fetch_id=F_SCRAPE, source="jobicy", operation="scrape",
        request={"url": "https://jobicy.com/api/v2/remote-jobs", "params": {"geo": "usa"}},
        status=200, fetched_at=T_SCRAPE, tool_version=TOOL_VERSION, item_count=3,
        response_headers={"content-type": "application/json"},
        payload=ref.as_payload("application/json"),
        context={"profile": "profile-01"})
    _write_manifest(layout, "jobicy", T_SCRAPE, F_SCRAPE, env)

    # NOT-SYNCED-HERE: payload recorded, blob deliberately NOT written.
    ns_bytes = NOT_SYNCED_MARKDOWN.encode("utf-8")
    ns_payload = {"blob": sha256_hex(ns_bytes), "bytes_raw": len(ns_bytes),
                  "content_type": "text/markdown"}
    ns_env = _manifest.build_envelope(
        fetch_id=F_NOTSYNC, source="greenhouse", operation="jd",
        request={"url": f"https://boards.greenhouse.io/{COMPANY}/jobs/9999999"},
        status=200, fetched_at=T_NOTSYNC, tool_version=TOOL_VERSION,
        response_headers={"content-type": "text/html"}, payload=ns_payload,
        context={"company": COMPANY, "profile": "profile-01"})
    _write_manifest(layout, "greenhouse", T_NOTSYNC, F_NOTSYNC, ns_env)


def _generate_annotations_and_identity(layout):
    # A human annotation for gh-1234567 -> the builder pins its key.
    ann = {"schema_version": 1, "key": "gh-1234567", "verified_by": "human",
           "verified_at": "2026-07-14", "facts": {"workplace": "hybrid"},
           "note": "JD text confirms hybrid in Austin."}
    atomic_write_text(layout.annotations / "gh-1234567.yaml",
                      serialization.dumps_yaml(ann))
    identifiers = {"schema_version": 1,
                   "profile": {"profile-01": "Jordan Rivers (example profile)"},
                   "account": {"acct-01": "jordan.rivers@example.com"}}
    atomic_write_text(layout.identifiers, serialization.dumps_yaml(identifiers))


def _run_builder(root: Path):
    """Run the REAL builder over the fixture raw (subprocess = clean import env)."""
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--data-root", str(root)],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(f"builder failed on the fixture (rc={result.returncode})")


def _finalize(layout, root: Path):
    """Normalize wall-clock ledger built_at, drop the machine-specific README,
    and write the consumer cursor — so the tracked fixture is byte-stable."""
    ledger = layout.build_ledger
    if ledger.exists():
        lines = read_jsonl(ledger)
        for ln in lines:
            ln["built_at"] = FIXED_BUILT_AT
        atomic_write_text(ledger, "".join(
            serialization.dumps_jsonl_line(ln) for ln in lines))
    # The generated README embeds the absolute data root (machine-specific); it is a
    # real-store ergonomics artifact, not part of the tracked fixture.
    readme = root / "README.md"
    if readme.exists():
        readme.unlink()
    # A consumer cursor demonstrating the sequence-cursor contract.
    cursors = {"schema_version": 1,
               "cursors": {"shortlist-review": {"seq": 1,
                                                "updated_at": "2026-07-14T10:05:00Z"}}}
    atomic_write_text(layout.cursors, serialization.dumps_yaml(cursors))
    # The retention GC config at the DOMAIN root — the design's conservative defaults
    # (boards/JDs kept forever; aggregator sweeps prune only when BOTH the posting is
    # >90d old AND we last observed it >30d ago). On this fixture nothing is old
    # enough, so GC is a documented no-op here — it just demonstrates the schema.
    atomic_write_text(layout.root / "retention.yaml",
                      "tiers:\n"
                      "  aggregator_sweeps:\n"
                      "    prune_blobs_when:\n"
                      "      all_of:\n"
                      "        - posting_date_older_than_days: 90\n"
                      "        - last_observed_older_than_days: 30\n"
                      "  boards_and_jds:\n"
                      "    prune_blobs_when: never\n")


def generate(root: Path) -> None:
    """Generate the whole fixture store under ``root`` (wipes it first)."""
    import shutil
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    layout = domain_layout(root, DOMAIN)
    blobstore = BlobStore(layout.blobs)
    _generate_raw(layout, blobstore)
    _generate_annotations_and_identity(layout)
    _run_builder(root)
    _finalize(layout, root)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help=f"target data root (default: {DEFAULT_ROOT})")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    generate(root)
    print(f"fixture store generated at {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
