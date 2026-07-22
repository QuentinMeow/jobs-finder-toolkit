"""Capture API — the small surface Stage-1 fetchers call at the fetch boundary.

Hard requirements from the store-core capture contract, enforced here:

- **never raises into the caller.** Any internal error becomes one stderr warning
  and the fetch continues — a store bug must never break a live search.
- **never takes a lock.** Each capture writes into a *unique* fetch directory
  (timestamp + per-run seq + random suffix) with content-addressed blobs, so two
  processes capturing at once are safe by construction; a same-blob write is a
  benign no-op.
- **capture-before-parse.** The payload blob is written *before* the manifest, and
  the manifest is the commit marker.

When the store is not configured (``data_root is None``) capture no-ops after one
stderr info line per process — a disabled store is not an error.
"""
from __future__ import annotations

import itertools
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import manifest as _manifest
from . import serialization
from .blobs import BlobStore
from .manifest import new_fetch_id, write_manifest
from .paths import domain_layout

# One "store disabled" info line per process, shared across sessions.
_DISABLED_NOTICE_EMITTED = False
_NOTICE_LOCK = threading.Lock()


def _emit_disabled_notice_once() -> None:
    global _DISABLED_NOTICE_EMITTED
    with _NOTICE_LOCK:
        if _DISABLED_NOTICE_EMITTED:
            return
        _DISABLED_NOTICE_EMITTED = True
    print("store: not configured (paths.data_root unset) — capture disabled",
          file=sys.stderr)


def _random_suffix() -> str:
    return os.urandom(3).hex()


class GroupHandle:
    """A multi-request fetch group: members share a ``group_id``; a group manifest
    attesting completeness is written on exit."""

    def __init__(self, session: "CaptureSession", group_id: str,
                 expected: int | None) -> None:
        self._session = session
        self.group_id = group_id
        self.expected = expected
        self._members: list[str] = []
        self._attested: bool | None = None
        self._source: str | None = None
        self._context: dict | None = None

    def capture_fetch(self, **kwargs) -> str | None:
        """Capture one member of the group (stamps ``group_id`` and counts it)."""
        kwargs["group_id"] = self.group_id
        member_index = len(self._members) + 1
        kwargs.setdefault("group", {})
        kwargs["group"] = {
            "group_id": self.group_id,
            "expected": self.expected,
            "member": member_index,
            "attested_complete": None,
        }
        fetch_id = self._session.capture_fetch(**kwargs)
        if fetch_id is not None:
            self._members.append(fetch_id)
            self._source = kwargs.get("source", self._source)
            self._context = kwargs.get("context", self._context)
        return fetch_id

    def attest(self, complete: bool) -> None:
        """Record the fetcher's completeness attestation for this group."""
        self._attested = bool(complete)

    def __enter__(self) -> "GroupHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Best-effort: writing the group manifest must never raise into the caller.
        try:
            self._session._write_group_manifest(self)
        except Exception as e:  # noqa: BLE001  (capture never raises)
            self._session._warn(f"group manifest write failed (continuing): {e}")
        return False


class CaptureSession:
    """Capture handle for one domain. Construct once per run; call ``capture_fetch``.

    ``data_root`` of ``None`` disables the session (no-op capture). Callers resolve
    it via ``config.data_root()``; the library never imports config, so it stays
    relocatable when vendored into a skill.
    """

    def __init__(self, domain: str, data_root: Path | None, *,
                 tool_version: str = "") -> None:
        self.domain = domain
        self.tool_version = tool_version
        self.data_root = Path(data_root) if data_root else None
        self.layout = None
        self._blobs = None
        self._seq = itertools.count(1)
        if self.data_root is not None:
            # Construction must honor the never-raise guarantee: an invalid domain
            # slug disables the session with one warning instead of raising.
            try:
                self.layout = domain_layout(self.data_root, domain)
                self._blobs = BlobStore(self.layout.blobs)
            except Exception as e:  # noqa: BLE001  (never raises into the caller)
                self.layout = None
                self._blobs = None
                self._warn(f"invalid domain {domain!r}; capture disabled: {e}")

    @property
    def enabled(self) -> bool:
        return self.layout is not None

    def _warn(self, msg: str) -> None:
        print(f"store: WARNING {self.domain}: {msg}", file=sys.stderr)

    def group(self, group_id: str, *, expected: int | None = None) -> GroupHandle:
        return GroupHandle(self, group_id, expected)

    def capture_fetch(
        self,
        *,
        source: str,
        operation: str,
        request: dict,
        status: int,
        payload_bytes: bytes | None = None,
        content_type: str | None = None,
        fetched_at: datetime | None = None,
        response_headers: dict | None = None,
        item_count: int | None = None,
        query: dict | None = None,
        pagination: dict | None = None,
        duration_ms: int | None = None,
        context: dict | None = None,
        group_id: str | None = None,
        group: dict | None = None,
        error: str | None = None,
    ) -> str | None:
        """Capture one fetch. Returns the fetch id, or ``None`` if disabled/failed.

        This method never raises: any failure warns to stderr and returns ``None``.
        """
        if self.layout is None:
            _emit_disabled_notice_once()
            return None
        try:
            return self._capture(
                source=source, operation=operation, request=request, status=status,
                payload_bytes=payload_bytes, content_type=content_type,
                fetched_at=fetched_at, response_headers=response_headers,
                item_count=item_count, query=query, pagination=pagination,
                duration_ms=duration_ms, context=context, group_id=group_id,
                group=group, error=error,
            )
        except Exception as e:  # noqa: BLE001  (hard requirement: never raises)
            self._warn(f"capture failed (search continues): {e}")
            return None

    def _capture(self, *, source, operation, request, status, payload_bytes,
                 content_type, fetched_at, response_headers, item_count, query,
                 pagination, duration_ms, context, group_id, group, error) -> str:
        dt = fetched_at or datetime.now(timezone.utc)
        fetch_id = new_fetch_id(dt, next(self._seq), _random_suffix())

        payload = None
        if payload_bytes is not None:
            # Capture-before-parse: the blob lands before the manifest commit.
            ref = self._blobs.write(payload_bytes, content_type)
            payload = ref.as_payload(content_type)

        envelope = _manifest.build_envelope(
            fetch_id=fetch_id, source=source, operation=operation, request=request,
            status=status, fetched_at=serialization.to_z(dt),
            tool_version=self.tool_version, duration_ms=duration_ms,
            response_headers=response_headers, item_count=item_count, query=query,
            pagination=pagination, payload=payload, context=context,
            group_id=group_id, group=group, error=error,
        )
        write_manifest(self.layout.manifest_path(source, dt, fetch_id), envelope)
        return fetch_id

    def _write_group_manifest(self, handle: GroupHandle) -> None:
        if self.layout is None:
            return
        dt = datetime.now(timezone.utc)
        fetch_id = new_fetch_id(dt, next(self._seq), _random_suffix())
        source = handle._source or "group"
        env = _manifest.build_group_manifest(
            fetch_id=fetch_id, group_id=handle.group_id, source=source,
            fetched_at=serialization.to_z(dt), expected=handle.expected,
            achieved=len(handle._members), attested_complete=handle._attested,
            members=handle._members, tool_version=self.tool_version,
            context=handle._context,
        )
        write_manifest(self.layout.manifest_path(source, dt, fetch_id), env)
