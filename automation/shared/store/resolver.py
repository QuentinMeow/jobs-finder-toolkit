"""Entity-key → derived entity → manifest → blob resolution (for ``store_show``).

A human chasing "why was this classified wrong?" must not dead-end at a hash-named
compressed blob four hops away. These helpers walk that path in one place so the
``store_show`` CLI (and any future investigation tool) shares the logic.
"""
from __future__ import annotations

from pathlib import Path

from . import serialization
from .manifest import iter_manifests
from .paths import DomainLayout


def find_entity_dir(layout: DomainLayout, entity_key: str) -> Path | None:
    """Locate ``derived/<entity-type>/<partition>/<entity_key>/`` for a key."""
    derived = layout.derived
    if not derived.is_dir():
        return None
    for candidate in sorted(derived.rglob(entity_key)):
        if candidate.is_dir() and candidate.name == entity_key:
            return candidate
    return None


def load_entity(layout: DomainLayout, entity_key: str) -> tuple[Path, dict] | None:
    """Return ``(yaml_path, entity_data)`` for an entity, or ``None`` if absent."""
    entity_dir = find_entity_dir(layout, entity_key)
    if entity_dir is None:
        return None
    yamls = sorted(entity_dir.glob("*.yaml"))
    if not yamls:
        return None
    path = yamls[0]
    data = serialization.loads_yaml(path.read_text(encoding="utf-8"))
    return path, (data if isinstance(data, dict) else {})


def find_manifest_by_fetch_id(layout: DomainLayout,
                              fetch_id: str) -> tuple[Path, dict] | None:
    """Return ``(manifest_path, envelope)`` for a fetch id, or ``None``."""
    for path, env in iter_manifests(layout):
        if env.get("fetch_id") == fetch_id:
            return path, env
    return None


def resolve_blob(layout: DomainLayout, entity_data: dict) -> dict | None:
    """Return the payload dict (``{blob, bytes_raw, content_type}``) for an entity.

    Follows ``provenance.fetch_ids`` to the first manifest that carries a payload.
    Returns ``None`` when the entity records no payload-bearing fetch.
    """
    provenance = entity_data.get("provenance") or {}
    fetch_ids = provenance.get("fetch_ids") or []
    for fetch_id in fetch_ids:
        found = find_manifest_by_fetch_id(layout, fetch_id)
        if found is None:
            continue
        _path, env = found
        payload = env.get("payload")
        if isinstance(payload, dict) and payload.get("blob"):
            return payload
    return None
