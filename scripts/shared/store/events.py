"""Idempotent append-only event log for a derived entity.

An entity's ``events.jsonl`` is its biography. Event identity is
``(entity, fetch, type)`` — re-appending the same identity is a no-op — so a
builder crash and re-run cannot append the same history twice. Readers tolerate a
torn final line (via :mod:`.atomic`).
"""
from __future__ import annotations

from pathlib import Path

from . import serialization
from .atomic import append_line, read_jsonl

# The three fields that together identify an event.
IDENTITY_FIELDS = ("entity", "fetch", "type")


def event_identity(event: dict) -> tuple:
    return tuple(event.get(f) for f in IDENTITY_FIELDS)


def existing_identities(path: Path) -> set[tuple]:
    return {event_identity(ev) for ev in read_jsonl(path)}


def append_event(path: Path, event: dict) -> bool:
    """Append ``event`` unless its identity is already present.

    Returns ``True`` if written, ``False`` if it was a duplicate no-op. The event
    must carry ``entity``, ``fetch`` and ``type`` (its identity); other fields
    (old/new values, timestamps derived from manifests) are free-form payload.
    """
    for field in IDENTITY_FIELDS:
        if field not in event:
            raise ValueError(f"event missing required identity field {field!r}")
    if event_identity(event) in existing_identities(path):
        return False
    append_line(path, serialization.dumps_jsonl_line(event))
    return True
