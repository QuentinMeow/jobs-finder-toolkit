"""Manifest envelope v1 — construction, raw-zone traversal, reference audit.

The manifest is *our* envelope around an upstream response: fully under our
control, additive-only, forever (it is the observation log). This module builds
envelopes (member fetches and group attestations), walks the raw zone skipping
crash debris, and audits blob reference counts.

The blob is written before the manifest and **manifest presence is the commit
marker** — a fetch directory without a ``manifest.json`` is debris from a crash
and is skipped here (swept later by the Stage-4 retention job, not now).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import blobs as _blobs
from . import serialization
from .constants import (
    ENVELOPE_SCHEMA,
    IDENTIFIER_CONTEXT_KEYS,
    SLUG_CONTEXT_KEYS,
)
from .paths import DomainLayout, SlugError, validate_identifier, validate_slug

# The only context keys a manifest may carry. Unknown keys are rejected at write
# time so a future key must be added here deliberately (never bypasses validation).
ALLOWED_CONTEXT_KEYS = frozenset(IDENTIFIER_CONTEXT_KEYS) | frozenset(SLUG_CONTEXT_KEYS)


def new_fetch_id(dt: datetime, seq: int, suffix: str) -> str:
    """Compose a fetch id ``<compact-ts>-<6-digit seq>-<hex suffix>``."""
    return f"{serialization.to_compact(dt)}-{seq:06d}-{suffix}"


def _validate_context(context: dict | None) -> dict:
    """Enforce neutral-slug discipline on every owner-identifying context field.

    Unknown keys are a hard error (naming the allowed set) so nothing bypasses
    write-time validation; inside capture this surfaces as a warning and the fetch
    continues.
    """
    if not context:
        return {}
    ctx = dict(context)
    unknown = sorted(set(ctx) - ALLOWED_CONTEXT_KEYS)
    if unknown:
        raise SlugError(
            f"unknown context key(s) {unknown}; allowed keys are "
            f"{sorted(ALLOWED_CONTEXT_KEYS)} (add new keys deliberately)")
    for key in IDENTIFIER_CONTEXT_KEYS:
        if key in ctx and ctx[key] is not None:
            validate_identifier(str(ctx[key]), field=f"context.{key}")
    for key in SLUG_CONTEXT_KEYS:
        if key in ctx and ctx[key] is not None:
            validate_slug(str(ctx[key]), field=f"context.{key}")
    return ctx


def build_envelope(
    *,
    fetch_id: str,
    source: str,
    operation: str,
    request: dict,
    status: int,
    fetched_at: str,
    tool_version: str = "",
    duration_ms: int | None = None,
    response_headers: dict | None = None,
    item_count: int | None = None,
    query: dict | None = None,
    pagination: dict | None = None,
    payload: dict | None = None,
    context: dict | None = None,
    group_id: str | None = None,
    group: dict | None = None,
    error: str | None = None,
) -> dict:
    """Construct a manifest-envelope-v1 dict (over-capture fields included).

    ``payload`` is ``{"blob", "bytes_raw", "content_type"}`` for a captured body,
    or ``None`` for a failed/empty fetch. Owner-identifier context values are
    validated here so a bad slug can never be written to disk.
    """
    validate_slug(source, field="source")
    env: dict = {
        "envelope_schema": ENVELOPE_SCHEMA,
        "fetch_id": fetch_id,
        "source": source,
        "operation": operation,
        "request": dict(request or {}),
        "status": int(status),
        "response_headers": dict(response_headers or {}),
        "fetched_at": fetched_at,
        "tool_version": tool_version,
        "payload": payload,
        "context": _validate_context(context),
    }
    if group_id is not None:
        env["group_id"] = group_id
    if group is not None:
        env["group"] = dict(group)
    if duration_ms is not None:
        env["duration_ms"] = int(duration_ms)
    if item_count is not None:
        env["item_count"] = int(item_count)
    if query is not None:
        env["query"] = dict(query)
    if pagination is not None:
        env["pagination"] = dict(pagination)
    if error is not None:
        env["error"] = str(error)
    return env


def build_group_manifest(
    *,
    fetch_id: str,
    group_id: str,
    source: str,
    fetched_at: str,
    expected: int | None,
    achieved: int,
    attested_complete: bool | None,
    members: list[str],
    tool_version: str = "",
    context: dict | None = None,
) -> dict:
    """Construct a group attestation manifest (``operation: group``).

    Completeness is *attested by the fetcher*, never inferred from HTTP 200:
    ``attested_complete`` is ``True`` only for sources that return whole boards.
    Anything that reasons from absence may consume only attested-complete groups.
    """
    validate_slug(source, field="source")
    return {
        "envelope_schema": ENVELOPE_SCHEMA,
        "kind": "group",
        "fetch_id": fetch_id,
        "group_id": group_id,
        "source": source,
        "operation": "group",
        "fetched_at": fetched_at,
        "expected": expected,
        "achieved": int(achieved),
        "attested_complete": attested_complete,
        "members": list(members),
        "tool_version": tool_version,
        "context": _validate_context(context),
    }


def write_manifest(path: Path, envelope: dict) -> None:
    """Atomically write a manifest as canonical JSON (the commit marker)."""
    from .atomic import atomic_write_text

    atomic_write_text(path, serialization.dumps_json(envelope))


def is_group_manifest(envelope: dict) -> bool:
    return envelope.get("kind") == "group" or envelope.get("operation") == "group"


# ── raw-zone traversal + reference audit ─────────────────────
def iter_manifests(layout: DomainLayout) -> Iterator[tuple[Path, dict]]:
    """Yield ``(path, envelope)`` for every committed manifest under ``raw/``.

    Debris (a fetch dir with no ``manifest.json``) is skipped by construction —
    we only look for the commit marker. The ``_blobs`` tree is not a source.
    """
    raw = layout.raw
    if not raw.is_dir():
        return
    for path in sorted(raw.glob("*/**/manifest.json")):
        # Never treat anything under _blobs as a manifest source.
        if "_blobs" in path.parts:
            continue
        try:
            envelope = serialization.loads_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(envelope, dict):
            yield path, envelope


def audit_refcounts(layout: DomainLayout, blobstore: _blobs.BlobStore) -> dict:
    """Compute blob reference counts and availability across the raw zone.

    Returns a report with per-sha reference counts, the set of present blobs,
    orphans (present but referenced by no live manifest), and referenced blobs
    that are absent (each classified ``pruned`` vs. informational
    ``not-synced-here``). Reference counts are computed here, never cached.
    """
    refs: dict[str, int] = {}
    ref_ext: dict[str, str] = {}
    for _path, env in iter_manifests(layout):
        payload = env.get("payload")
        if isinstance(payload, dict) and payload.get("blob"):
            sha = payload["blob"]
            refs[sha] = refs.get(sha, 0) + 1
            ref_ext.setdefault(sha, _blobs.ext_for_content_type(
                payload.get("content_type")))

    present = blobstore.present_shas()
    referenced = set(refs)
    orphans = sorted(present - referenced)
    absent = {}
    for sha in sorted(referenced - present):
        absent[sha] = blobstore.state(sha, ref_ext.get(sha))
    return {
        "refcounts": refs,
        "present": sorted(present),
        "orphans": orphans,
        "absent": absent,  # sha -> "pruned" | "not-synced-here" | "corrupt"
    }
