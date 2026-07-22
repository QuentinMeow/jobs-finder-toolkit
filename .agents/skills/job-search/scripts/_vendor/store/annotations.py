"""Annotations zone — human-verified facts, and the orphan hard-fail.

Only *human* judgments live in ``annotations/``; they are merged into ``derived/``
at build time (the human fact wins) and survive rebuilds. A rebuild **fails its
verification step if any annotation no longer matches an entity** — an orphaned
human judgment is a loud error, never a silent drop. This module loads annotation
files (keyed by source-native id / entity key) and provides that hard-fail check;
the real builder (Stage 2) calls it before an atomic swap.
"""
from __future__ import annotations

from pathlib import Path

from . import serialization


class AnnotationOrphanError(Exception):
    """One or more annotations reference no built entity — a build-fatal condition."""

    def __init__(self, orphans: list[str]) -> None:
        self.orphans = sorted(orphans)
        super().__init__(
            "annotation(s) match no built entity (human judgment would be lost): "
            + ", ".join(self.orphans)
        )


def annotation_key(path: Path) -> str:
    """The entity key an annotation file targets (its stem, e.g. ``gh-1234567``)."""
    return Path(path).stem


def load_annotations(annotations_dir: Path) -> dict[str, dict]:
    """Return ``{entity_key: annotation_data}`` for every ``*.yaml`` annotation."""
    annotations_dir = Path(annotations_dir)
    out: dict[str, dict] = {}
    if not annotations_dir.is_dir():
        return out
    for path in sorted(annotations_dir.glob("*.yaml")):
        data = serialization.loads_yaml(path.read_text(encoding="utf-8"))
        out[annotation_key(path)] = data if isinstance(data, dict) else {}
    return out


def find_orphans(annotation_keys, entity_keys) -> list[str]:
    """Annotation keys that match no built entity key."""
    entities = set(entity_keys)
    return sorted(k for k in annotation_keys if k not in entities)


def assert_no_orphans(annotation_keys, entity_keys) -> None:
    """Raise :class:`AnnotationOrphanError` if any annotation is orphaned."""
    orphans = find_orphans(annotation_keys, entity_keys)
    if orphans:
        raise AnnotationOrphanError(orphans)
