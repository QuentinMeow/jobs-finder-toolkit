"""Persisted per-entity fold state — what lets an incremental build be O(new).

``build_postings.py`` reduces the raw zone by folding each entity's observations
in ledger order. Folding is a **left fold with carried state** (the previous
observation's snapshot decides the next `changed` event), so continuing it needs
that carried state, not the whole history. This module owns the file that stores
it: ``state/postings-fold-cache.jsonl``.

Three properties make trusting it safe:

* **It is a cache, never truth.** ``raw/`` + the ledger stay authoritative. Every
  question this module answers is "may the fast path run?", and every uncertain
  answer is ``no`` — which falls back to the unchanged full fold. A missing,
  torn, stale, or merely suspicious cache costs one slow build, never a wrong one.
* **It is written last and atomically.** The builder writes derived + index
  first and replaces this file (temp-then-rename, whole file) only after they
  land. A crash therefore leaves the PREVIOUS complete cache next to a store that
  has already moved on — which :func:`read_incomplete`'s write-ahead marker
  detects unconditionally (and the ledger digest also detects whenever the build
  ingested a manifest), forcing a full fold. A half-written cache is impossible
  (rename is atomic); a truncated one fails :func:`load`'s count check and is
  discarded.
* **It invalidates on anything it does not model.** The fingerprint covers every
  module whose code decides an entity's bytes, and the store digests cover the
  raw manifest set, blob presence, and the frozen-facts snapshots. A change to
  any of them re-derives everything from raw, exactly as today.

The per-entity payload is deliberately tiny — the carried snapshot and a couple
of flags. Everything else the fold needs (source ids, profiles, fetch ids, the
event list, the JD text) is read back from the entity's OWN derived files, which
are already the store's serialized form of it. Keeping one copy instead of two
means the cache cannot silently disagree with derived.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Bumped whenever a header field's MEANING changes, not only its layout: a cache
# whose digests were computed by an older rule cannot be compared against the new
# one, and `load` returning None ("no usable fold cache") names the cause far
# better than a bare digest mismatch would. Cost is one full fold per store, once.
#   1 -> 2  `manifest_digest` covers (fetch_id, payload blob) pairs, not bare
#           fetch ids, so a manifest replaced in place is detected.
CACHE_SCHEMA = 2
CACHE_NAME = "postings-fold-cache.jsonl"
INCOMPLETE_NAME = "postings-build-incomplete.json"


def cache_path(layout) -> Path:
    """``state/postings-fold-cache.jsonl`` for a domain layout."""
    return layout.state / CACHE_NAME


def incomplete_path(layout) -> Path:
    """``state/postings-build-incomplete.json`` for a domain layout."""
    return layout.state / INCOMPLETE_NAME


# ── digests (every one of these is an invalidation signal) ───────────────────
def digest_strings(values) -> str:
    """Order-independent sha256 over a collection of strings (16 hex chars)."""
    h = hashlib.sha256()
    for v in sorted(values):
        h.update(str(v).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def digest_pairs(pairs) -> str:
    """Order-independent sha256 over ``(name, content)`` pairs (16 hex chars)."""
    h = hashlib.sha256()
    for name, content in sorted(pairs):
        h.update(str(name).encode("utf-8"))
        h.update(b"\x00")
        h.update(content if isinstance(content, bytes)
                 else str(content).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def digest_obj(obj) -> str:
    """sha256 over any JSON-able object, canonically encoded (16 hex chars)."""
    text = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── file I/O ─────────────────────────────────────────────────────────────────
def load(path: Path) -> tuple[dict, dict] | None:
    """Return ``(header, {key: entry})``, or ``None`` if the file is unusable.

    Unusable means absent, unparseable, a schema we do not write, or a line count
    that disagrees with the header — i.e. any state from which we cannot prove the
    cache describes a complete build. The caller's only correct response is a full
    fold, so this returns ``None`` rather than raising.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    if not lines:
        return None
    try:
        header = json.loads(lines[0])
        entries = [json.loads(ln) for ln in lines[1:] if ln.strip()]
    except (ValueError, TypeError):
        return None
    if not isinstance(header, dict) or header.get("_schema") != CACHE_SCHEMA:
        return None
    if header.get("count") != len(entries):
        return None
    by_key = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("k"):
            return None
        by_key[entry["k"]] = entry
    if len(by_key) != len(entries):
        return None  # duplicate keys — a malformed cache, never trusted
    return header, by_key


def save(path: Path, header: dict, entries: dict) -> None:
    """Atomically replace the cache with ``header`` + one line per entity.

    Whole-file replacement (not an append log) is the crash-safety choice: the
    reader either sees the complete previous generation or the complete new one.
    """
    from _vendor.store.atomic import atomic_write_text  # local: skill vendoring

    head = dict(header)
    head["_schema"] = CACHE_SCHEMA
    head["count"] = len(entries)
    out = [json.dumps(head, sort_keys=True, ensure_ascii=False)]
    out += [json.dumps(entries[k], sort_keys=True, ensure_ascii=False)
            for k in sorted(entries)]
    atomic_write_text(Path(path), "\n".join(out) + "\n")


def discard(path: Path) -> None:
    """Remove the cache (used when a build cannot leave a trustworthy one)."""
    try:
        Path(path).unlink()
    except OSError:
        pass


# ── the write-ahead marker (crash detection that does not need the ledger) ────
# Every OTHER invalidation signal in the header describes state the build did not
# write — code, the raw zone, blob presence, frozen facts — so comparing it next
# run is enough. Two do not: `ledger_digest` describes the ledger, and `ann_keys`
# describes the DERIVED zone, both of which this build writes itself.
#
# `ledger_digest` gets away with it because `_record_pending` advances the ledger
# BEFORE the first derived write, so a crash always leaves ledger > cache. But it
# only moves when there is something to record, and a build with zero pending
# manifests — exactly what applying a human annotation is — records nothing while
# still rewriting derived. `ann_keys` is then the only thing that moved, and it is
# written LAST, so the next run computes its annotation-undo reach from a record
# that predates the derived zone it is supposed to correct.
#
# The general rule the ledger digest satisfies by accident is: *the store's
# description of the derived zone must be written before the derived zone moves.*
# This marker states it directly. Every build that can mutate `derived/` writes it
# first and removes it only after the cache (the description) has landed, so any
# interruption in between is visible next run and answered with a full fold — one
# slow build, the design's own stated failure mode.
def mark_incomplete(path: Path, mode: str) -> None:
    """Record — BEFORE the first derived write — that derived is about to move."""
    from _vendor.store import serialization  # local: skill vendoring
    from _vendor.store.atomic import atomic_write_text  # local: skill vendoring

    atomic_write_text(Path(path), json.dumps(
        {"mode": mode, "started_at": serialization.now_z()},
        sort_keys=True, ensure_ascii=False) + "\n")


def read_incomplete(path: Path) -> dict | None:
    """The surviving marker of a build that never finished, or ``None``.

    Any unreadable/unparseable marker still counts as "a build did not finish" —
    the file's presence is the signal; its contents only name the culprit.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def clear_incomplete(path: Path) -> None:
    """Drop the marker — the cache now describes the derived zone again."""
    try:
        Path(path).unlink()
    except OSError:
        pass


# ── the reasons a fast path is refused (reported, never silent) ──────────────
def compare_header(cached: dict, current: dict) -> str | None:
    """Return the first mismatching header field name, or ``None`` if all agree.

    Every field here is something the cache does not model per-entity, so a
    difference means the store or the code moved under it.
    """
    for field in ("fingerprint", "ledger_digest", "manifest_digest",
                  "absent_digest", "frozen_digest"):
        if cached.get(field) != current.get(field):
            return field
    return None
