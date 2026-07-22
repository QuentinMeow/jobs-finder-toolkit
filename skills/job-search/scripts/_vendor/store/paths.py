"""Zone path layout for a domain root, plus lowercase-slug enforcement.

A *domain* (``jobs``, ``email``, …) is one subtree of the data root with the five
zones. This module is the single place that knows where each zone and each fetch
directory lives, and the single gate that enforces lowercase-slug path components
with case-collision detection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import serialization
from .constants import IDENTIFIER_RE, IDENTIFIER_RULE, SLUG_RE, SLUG_RULE


class SlugError(ValueError):
    """A path component or identifier failed its write-time validation."""


def validate_slug(value: str, *, field: str = "path component") -> str:
    """Return ``value`` if it is a valid lowercase slug, else raise naming the rule."""
    if not isinstance(value, str) or not SLUG_RE.match(value):
        raise SlugError(f"{field} {value!r} is invalid: {SLUG_RULE}")
    return value


def validate_identifier(value: str, *, field: str = "identifier") -> str:
    """Return ``value`` if it matches ``(profile|acct)-NN``, else raise naming the rule.

    Agents never construct these by hand — they come only from the identifier
    registry. This is the mechanical backstop the store-core privacy decision
    requires: a real label physically cannot pass this gate into a manifest.
    """
    if not isinstance(value, str) or not IDENTIFIER_RE.match(value):
        raise SlugError(f"{field} {value!r} is invalid: {IDENTIFIER_RULE}")
    return value


def detect_case_collision(existing: list[str], candidate: str) -> str | None:
    """Return an existing sibling that differs from ``candidate`` only by case.

    A case-only collision is a build error (it would merge on Mac, fork on Linux),
    never a silent merge. Returns the colliding name, or ``None`` if clear.

    Stage 2 wires this into the derived-zone writer (checking each new
    ``derived/.../<entity-key>`` against its existing siblings before write); it is
    intentionally provided now, not dead forever.
    """
    low = candidate.lower()
    for name in existing:
        if name != candidate and name.lower() == low:
            return name
    return None


@dataclass(frozen=True)
class DomainLayout:
    """Resolved paths for one domain's five zones under a data root."""

    root: Path  # <data_root>/<domain>
    domain: str

    # ── zone roots ──
    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def blobs(self) -> Path:
        return self.root / "raw" / "_blobs"

    @property
    def derived(self) -> Path:
        return self.root / "derived"

    @property
    def index(self) -> Path:
        return self.root / "index"

    @property
    def annotations(self) -> Path:
        return self.root / "annotations"

    @property
    def state(self) -> Path:
        return self.root / "state"

    # ── raw fetch layout ──
    def source_day_dir(self, source: str, dt: datetime) -> Path:
        validate_slug(source, field="source")
        d = serialization._as_utc(dt)
        return self.raw / source / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}"

    def fetch_dir(self, source: str, dt: datetime, fetch_id: str) -> Path:
        return self.source_day_dir(source, dt) / fetch_id

    def manifest_path(self, source: str, dt: datetime, fetch_id: str) -> Path:
        return self.fetch_dir(source, dt, fetch_id) / "manifest.json"

    # ── state files ──
    @property
    def build_ledger(self) -> Path:
        return self.state / "build-ledger.jsonl"

    @property
    def key_registry(self) -> Path:
        return self.state / "key-registry.yaml"

    @property
    def identifiers(self) -> Path:
        return self.state / "identifiers.yaml"

    @property
    def cursors(self) -> Path:
        return self.state / "cursors.yaml"

    def lock_path(self) -> Path:
        return self.state / f"{self.domain}.build.lock"


def domain_layout(data_root: Path, domain: str) -> DomainLayout:
    """Build a :class:`DomainLayout` for ``domain`` under ``data_root``."""
    validate_slug(domain, field="domain")
    return DomainLayout(root=Path(data_root) / domain, domain=domain)
