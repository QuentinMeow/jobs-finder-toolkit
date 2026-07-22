"""``scripts/shared/store`` — the raw-data-layer store library (Stage 0).

A filesystem-as-database contract shared by every data domain (jobs, email, …):
five directory zones (``raw`` / ``derived`` / ``index`` / ``annotations`` / ``state``),
same-directory atomic writes with torn-tail-tolerant JSONL, a content-addressed
blob store (sha256 of uncompressed bytes, verify-on-read), the manifest envelope v1
(fetch groups + over-capture), a build ledger with a materialization sequence,
idempotent event appends, a builder-only lock, a pinned-key registry, a
library-only neutral-identifier registry, the canonical serializer, JSON Schemas
plus a zone-aware validator, and a migrations scaffold (annotations/state only).

The package is stdlib + PyYAML + ``zstandard`` only and uses relative imports
throughout, so it stays byte-identically vendorable into a self-contained skill.
Capture is the only surface a live fetcher touches; it never raises and never locks.

See ``docs/design/raw-data-layer/01-store-core.md`` for the full contract.
"""
from __future__ import annotations

from . import (  # noqa: F401  (re-exported submodules)
    annotations,
    atomic,
    blobs,
    builder,
    capture,
    constants,
    events,
    identifiers,
    keyregistry,
    ledger,
    locking,
    manifest,
    paths,
    resolver,
    retention,
    serialization,
    validation,
)
from .blobs import BlobCorrupt, BlobRef, BlobStore
from .capture import CaptureSession
from .constants import ENVELOPE_SCHEMA, FIXTURE_SIZE_SOFT_LIMIT_BYTES, ZSTD_LEVEL
from .identifiers import IdentifierRegistry
from .keyregistry import KeyRegistry
from .ledger import BuildLedger, pending_manifests
from .locking import DomainLock, LockContention
from .paths import DomainLayout, SlugError, domain_layout, validate_identifier, validate_slug

__all__ = [
    "CaptureSession",
    "BlobStore",
    "BlobRef",
    "BlobCorrupt",
    "BuildLedger",
    "pending_manifests",
    "DomainLayout",
    "domain_layout",
    "DomainLock",
    "LockContention",
    "IdentifierRegistry",
    "KeyRegistry",
    "SlugError",
    "validate_slug",
    "validate_identifier",
    "ENVELOPE_SCHEMA",
    "ZSTD_LEVEL",
    "FIXTURE_SIZE_SOFT_LIMIT_BYTES",
]
