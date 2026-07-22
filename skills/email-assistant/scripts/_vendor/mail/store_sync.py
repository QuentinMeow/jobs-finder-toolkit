"""Privacy-bounded local synchronization for the email store.

This is deliberately below the email-assistant CLI and above providers: it has
no application-tracker imports and no drafting operations.  It records Inbox,
Sent Items, and Drafts as private local raw evidence, with a normal full
inventory path before delta is treated as an optimisation.  The only provider
identity used as a key is its immutable item ID; RFC Message-ID remains an alias.

The store lives under ``<data_root>/email``.  ``data_root`` is deliberately
configured outside tracked source trees (``config.data_root()``); the private
overlay's .gitignore adds a second defence for an in-overlay data root.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ..store.atomic import append_line, atomic_write_text, read_jsonl
from ..store.blobs import BlobStore
from ..store.identifiers import IdentifierRegistry
from ..store.manifest import build_envelope, new_fetch_id, write_manifest
from ..store.serialization import dumps_json, dumps_jsonl_line, dumps_yaml, now_z, parse_z, to_z
from .contract.interface import (
    CapabilityNotSupported,
    MailProvider,
    MessageNotFound,
    SyncTokenExpired,
)

STORE_SCHEMA_VERSION = 1
MESSAGE_SCHEMA_VERSION = 1
FIELD_SET_VERSION = 1
FOLDERS = ("inbox", "sentitems", "drafts")
PROVIDER_SOURCE = {"outlook_graph": "outlook"}
STALE_BANNER = "STORE STALE — sync broken"


class EmailStoreError(RuntimeError):
    """Email-store state is unsafe to use or cannot be completed."""


@dataclass(frozen=True)
class SyncResult:
    account: str
    mode: str
    folders: dict[str, dict[str, int]]
    token_expired: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "mode": self.mode,
            "token_expired": self.token_expired,
            "folders": self.folders,
        }


@dataclass
class _FolderWork:
    folder: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    sync_token: str | None = None
    watermark: str | None = None


def message_key(account_slug: str, provider_message_id: str) -> str:
    """Stable identity: sha256(account neutral slug + immutable provider ID)."""
    if not account_slug or not provider_message_id:
        raise EmailStoreError("account slug and provider immutable message ID are required")
    return hashlib.sha256(
        f"{account_slug}\0{provider_message_id}".encode("utf-8")
    ).hexdigest()


def _provider_source(provider: MailProvider) -> str:
    source = PROVIDER_SOURCE.get(provider.name, provider.name.replace("_", "-"))
    if not source or not all(ch.islower() or ch.isdigit() or ch == "-" for ch in source):
        raise EmailStoreError(f"provider {provider.name!r} has no safe store source slug")
    return source


def _parse_provider_time(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _message_time(message: dict[str, Any]) -> str | None:
    for key in ("receivedDateTime", "sentDateTime", "lastModifiedDateTime"):
        value = message.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_within_window(message: dict[str, Any], cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    timestamp = _parse_provider_time(_message_time(message))
    # Keep malformed/undated messages rather than silently discarding evidence.
    return timestamp is None or timestamp >= cutoff


def _clean_raw_message(value: Any) -> Any:
    """Copy provider JSON while structurally refusing attachment bytes.

    Attachment payloads use ``contentBytes`` in Graph.  A provider response that
    accidentally grows an attachments property is excluded wholesale; only the
    separately fetched, allowlisted metadata reaches the raw envelope.
    """
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in {"contentbytes", "attachments"}:
                continue
            cleaned[str(key)] = _clean_raw_message(child)
        return cleaned
    if isinstance(value, list):
        return [_clean_raw_message(item) for item in value]
    return value


def _attachment_metadata(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize to the five explicitly approved attachment fields."""
    normalized: list[dict[str, Any]] = []
    for item in items:
        attachment_id = str(item.get("attachment_id") or item.get("id") or "")
        if not attachment_id:
            # A retrieval pointer is required; ignore unusable provider debris.
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        normalized.append(
            {
                "attachment_id": attachment_id,
                "content_type": str(item.get("content_type") or item.get("contentType") or ""),
                "is_inline": bool(item.get("is_inline", item.get("isInline", False))),
                "name": str(item.get("name") or ""),
                "size": max(size, 0),
            }
        )
    return normalized


def normalized_message(
    *,
    account: str,
    provider: str,
    folder: str,
    message: dict[str, Any],
    attachments: Iterable[dict[str, Any]],
    raw_fetch_id: str,
    observed_at: str,
) -> dict[str, Any]:
    """The Stage-3 derived-message shape (no body; raw is authoritative).

    ``provider_message_id`` is the Graph immutable ID, ``message_key`` is the
    account-partitioned hash, and ``rfc_message_id`` is correlation-only.  These
    field names are intentionally stable for the later reconciliation stage.
    """
    provider_message_id = str(message.get("id") or "")
    if not provider_message_id:
        raise EmailStoreError("provider message omitted its immutable id")
    return {
        "schema_version": MESSAGE_SCHEMA_VERSION,
        "message_key": message_key(account, provider_message_id),
        "account": account,
        "provider": provider,
        "provider_message_id": provider_message_id,
        "provider_thread_id": str(message.get("conversationId") or "") or None,
        "rfc_message_id": str(message.get("internetMessageId") or "") or None,
        "folder": folder,
        "in_scope": True,
        "tombstoned": False,
        "received_at": message.get("receivedDateTime") or None,
        "sent_at": message.get("sentDateTime") or None,
        "modified_at": message.get("lastModifiedDateTime") or None,
        "is_draft": bool(message.get("isDraft", False)),
        "is_read": message.get("isRead") if isinstance(message.get("isRead"), bool) else None,
        "attachments": _attachment_metadata(attachments),
        "raw_fetch_id": raw_fetch_id,
        "observed_at": observed_at,
    }


class EmailStoreSync:
    """Synchronize one provider account into ``<data_root>/email``.

    Construction allocates the neutral account slug from the private identifier
    registry.  No mailbox address is used in a path, raw manifest context, CLI
    result, or message key.
    """

    def __init__(
        self,
        *,
        data_root: Path,
        provider: MailProvider,
        account_label: str,
        tool_version: str = "email-store-sync/1",
        read_only: bool = False,
    ) -> None:
        if not account_label.strip():
            raise EmailStoreError("configured mailbox label is required")
        self.provider = provider
        self.source = _provider_source(provider)
        self.root = Path(data_root).expanduser().resolve() / "email"
        self.tool_version = tool_version
        self.read_only = read_only
        registry = IdentifierRegistry(self.root / "state" / "identifiers.yaml")
        if read_only:
            # A freshness/review operation must not acquire the allocator lock
            # or create a new private account partition.  It is valid only after
            # an explicit sync has already established this mailbox locally.
            self.account = registry.resolve_label("account", account_label)
            if not self.account:
                raise EmailStoreError(
                    "configured mailbox has no local email-store partition; run sync-store first"
                )
        else:
            self.account = registry.allocate("account", account_label)
        self._blobs = BlobStore(self.root / "raw" / "_blobs")
        self._sequence = 0

    # ── layout / state ─────────────────────────────────────────────────
    @property
    def state_path(self) -> Path:
        return self.root / "state" / self.account / "sync.json"

    @property
    def runs_path(self) -> Path:
        return self.root / "state" / self.account / "runs.jsonl"

    def _derived_path(self, record: dict[str, Any]) -> Path:
        timestamp = (
            record.get("received_at")
            or record.get("sent_at")
            or record.get("modified_at")
            or record.get("observed_at")
        )
        parsed = _parse_provider_time(str(timestamp) if timestamp else None) or datetime.now(timezone.utc)
        return (
            self.root
            / "derived"
            / self.account
            / "messages"
            / f"{parsed:%Y-%m}"
            / str(record["message_key"])
            / "message.yaml"
        )

    def _index_header_path(self) -> Path:
        return self.root / "index" / self.account / "header.json"

    def _message_index_path(self) -> Path:
        return self.root / "index" / self.account / "messages.jsonl"

    def _default_state(self) -> dict[str, Any]:
        return {
            "schema_version": STORE_SCHEMA_VERSION,
            "field_set_version": FIELD_SET_VERSION,
            "account": self.account,
            "provider": self.source,
            "folders": {
                folder: {
                    "delta_token": None,
                    "inventory": [],
                    "watermark": None,
                    "last_successful_sync": None,
                }
                for folder in FOLDERS
            },
            "messages": {},
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EmailStoreError(f"email sync state is unreadable: {self.state_path}") from exc
        if not isinstance(state, dict) or state.get("schema_version") != STORE_SCHEMA_VERSION:
            raise EmailStoreError("email sync state schema is unsupported; do not overwrite it")
        if state.get("account") != self.account or state.get("provider") != self.source:
            raise EmailStoreError("email sync state belongs to a different account or provider")
        state.setdefault("messages", {})
        state.setdefault("folders", {})
        for folder in FOLDERS:
            state["folders"].setdefault(folder, self._default_state()["folders"][folder])
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        atomic_write_text(self.state_path, dumps_json(state))

    # ── raw + derived recording ─────────────────────────────────────────
    def _capture_raw(
        self,
        *,
        folder: str,
        message: dict[str, Any],
        attachments: list[dict[str, Any]],
        observed_at: str,
    ) -> str:
        self._sequence += 1
        captured = datetime.now(timezone.utc)
        fetch_id = new_fetch_id(captured, self._sequence, secrets.token_hex(3))
        raw_payload = {
            "payload_schema": 1,
            "message": _clean_raw_message(message),
            "attachment_metadata": attachments,
        }
        payload_bytes = dumps_json(raw_payload).encode("utf-8")
        ref = self._blobs.write(payload_bytes, "application/json")
        manifest = build_envelope(
            fetch_id=fetch_id,
            source=self.source,
            operation="scrape",
            request={"folder": folder, "resource": "message"},
            status=200,
            fetched_at=observed_at,
            tool_version=self.tool_version,
            item_count=1,
            payload=ref.as_payload("application/json"),
            context={"account": self.account},
        )
        path = (
            self.root
            / "raw"
            / self.source
            / self.account
            / f"{captured:%Y}"
            / f"{captured:%m}"
            / f"{captured:%d}"
            / fetch_id
            / "manifest.json"
        )
        write_manifest(path, manifest)
        return fetch_id

    def _write_derived(self, record: dict[str, Any]) -> None:
        atomic_write_text(self._derived_path(record), dumps_yaml(record))

    def _write_index(self, state: dict[str, Any]) -> None:
        # This is the sole content-free artifact the email index intentionally
        # permits Git to track.  Message rows are ignored even though this stage
        # avoids subjects and bodies in them: future projections will be richer.
        header = {
            "schema_version": 1,
            "kind": "email-index-header",
            "account": self.account,
            "provider": self.source,
            "content_free": True,
            "message_row_fields": [
                "message_key", "folder", "in_scope", "tombstoned",
                "received_at", "sent_at", "modified_at", "has_attachments",
            ],
        }
        atomic_write_text(self._index_header_path(), dumps_json(header))
        rows = []
        for key, record in sorted(state["messages"].items()):
            rows.append(
                {
                    "message_key": key,
                    "folder": record.get("folder"),
                    "in_scope": bool(record.get("in_scope")),
                    "tombstoned": bool(record.get("tombstoned")),
                    "received_at": record.get("received_at"),
                    "sent_at": record.get("sent_at"),
                    "modified_at": record.get("modified_at"),
                    "has_attachments": bool(record.get("attachments")),
                }
            )
        atomic_write_text(self._message_index_path(), "".join(dumps_jsonl_line(row) for row in rows))

    def _upsert_message(
        self,
        *,
        state: dict[str, Any],
        folder: str,
        envelope: dict[str, Any],
        observed_at: str,
    ) -> str:
        immutable_id = str(envelope.get("id") or "")
        if not immutable_id:
            raise EmailStoreError("delta/list response omitted immutable message id")
        # A list/delta envelope is intentionally not enough: capture the full
        # body locally for the requested window, then a separate metadata-only
        # attachment request.  Never request attachment content as a shortcut.
        full = self.provider.read_message(immutable_id)
        try:
            attachments = _attachment_metadata(self.provider.attachment_metadata(immutable_id))
        except CapabilityNotSupported as exc:
            raise EmailStoreError(
                f"{self.provider.name} cannot safely supply attachment metadata"
            ) from exc
        raw_fetch_id = self._capture_raw(
            folder=folder, message=full, attachments=attachments, observed_at=observed_at
        )
        record = normalized_message(
            account=self.account,
            provider=self.source,
            folder=folder,
            message=full,
            attachments=attachments,
            raw_fetch_id=raw_fetch_id,
            observed_at=observed_at,
        )
        key = str(record["message_key"])
        previous = state["messages"].get(key)
        if previous:
            # Preserve the original raw provenance chain.  The current fetch is
            # authoritative for fields that can change (folder, draft/read state).
            fetches = list(previous.get("raw_fetch_ids") or [previous.get("raw_fetch_id")])
            if raw_fetch_id not in fetches:
                fetches.append(raw_fetch_id)
            record["raw_fetch_ids"] = fetches
        else:
            record["raw_fetch_ids"] = [raw_fetch_id]
        state["messages"][key] = record
        self._write_derived(record)
        return key

    # ── provider collection ────────────────────────────────────────────
    def _full_snapshot(self, folder: str, cutoff: datetime | None) -> _FolderWork:
        """Build one complete inventory, using delta's initial enumeration when safe.

        The resulting work is still processed as a *full* snapshot and always
        runs the inventory diff.  Providers without delta support use their
        unbounded ``list_folder(..., limit=None)`` implementation.
        """
        if cutoff is not None:
            # The 30-day CLI path must not be a superficial count limit.  Outlook
            # applies this timestamp filter on the server and paginates every
            # matching item; only then are full bodies fetched locally.
            messages = self.provider.list_folder(
                folder, limit=None, since=to_z(cutoff)
            )
            # Do not initialize Graph delta here: an initial delta enumeration
            # walks the entire mailbox even though the user asked for a bounded
            # window. Rolling-window syncs therefore remain server-filtered full
            # snapshots; opaque delta optimization is reserved for ``--all``.
            return _FolderWork(folder=folder, messages=messages, sync_token=None,
                               watermark=_latest_time(messages))
        if self.provider.capabilities().delta_sync:
            response = self.provider.delta_sync(folder, None)
            return _FolderWork(
                folder=folder,
                messages=list(response.get("messages") or []),
                sync_token=str(response.get("sync_token") or "") or None,
                watermark=_latest_time(response.get("messages") or []),
            )
        messages = self.provider.list_folder(folder, limit=None)
        return _FolderWork(folder=folder, messages=messages, watermark=_latest_time(messages))

    def _delta(self, folder: str, token: str) -> _FolderWork:
        response = self.provider.delta_sync(folder, token)
        messages = list(response.get("messages") or [])
        removed = [
            str(item.get("id"))
            for item in messages
            if isinstance(item, dict) and item.get("@removed") and item.get("id")
        ]
        return _FolderWork(
            folder=folder,
            messages=[item for item in messages if isinstance(item, dict) and not item.get("@removed")],
            removed_ids=removed,
            sync_token=str(response.get("sync_token") or "") or None,
            watermark=_latest_time(messages),
        )

    # ── synchronization ────────────────────────────────────────────────
    def sync(self, *, days: int | None = 30, force_full: bool = False) -> SyncResult:
        """Synchronize the requested rolling window; ``days=None`` means all mail.

        Full snapshots perform the documented inventory diff.  With a rolling
        window, only a previously indexed message still inside *today's* window
        may be inferred deleted; an item that merely aged out is retained rather
        than falsely tombstoned.
        """
        if self.read_only:
            raise EmailStoreError("a read-only email-store handle cannot synchronize")
        if days is not None and days <= 0:
            raise EmailStoreError("--days must be a positive number or all")
        state = self._load_state()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
        token_invalid = False
        token_compatible = state.get("field_set_version") == FIELD_SET_VERSION
        tokens = [state["folders"][folder].get("delta_token") for folder in FOLDERS]
        use_full = force_full or not token_compatible or not all(tokens)

        if use_full:
            work = {folder: self._full_snapshot(folder, cutoff) for folder in FOLDERS}
            mode = "full"
        else:
            try:
                work = {
                    folder: self._delta(folder, str(state["folders"][folder]["delta_token"]))
                    for folder in FOLDERS
                }
                mode = "delta"
            except SyncTokenExpired:
                # An expired opaque token is an expected operational path, never
                # a data-loss event.  Restart all folders so cross-folder moves
                # remain coherent before running inventory-diff tombstoning.
                token_invalid = True
                work = {folder: self._full_snapshot(folder, cutoff) for folder in FOLDERS}
                mode = "full"

        observed_at = now_z()
        seen: set[str] = set()
        by_folder: dict[str, set[str]] = {folder: set() for folder in FOLDERS}
        removed_provider_ids: set[str] = set()
        counts = {
            folder: {"upserted": 0, "removed": 0, "tombstoned": 0, "out_of_scope": 0}
            for folder in FOLDERS
        }
        for folder in FOLDERS:
            folder_work = work[folder]
            for envelope in folder_work.messages:
                if not _is_within_window(envelope, cutoff):
                    continue
                key = self._upsert_message(
                    state=state, folder=folder, envelope=envelope, observed_at=observed_at
                )
                seen.add(key)
                by_folder[folder].add(key)
                counts[folder]["upserted"] += 1
            removed_provider_ids.update(folder_work.removed_ids)

        # A full snapshot's absence is meaningful only for records that remain
        # within this exact rolling window.  For each absence read its immutable
        # ID: 404 = hard deletion/tombstone; present outside the three folders =
        # out of scope.  Any other error aborts rather than manufacturing loss.
        pending_absences: set[str] = set()
        if mode == "full":
            for folder in FOLDERS:
                previous = set(state["folders"][folder].get("inventory") or [])
                for key in previous - by_folder[folder]:
                    record = state["messages"].get(key)
                    if record is None or key in seen:
                        continue
                    if cutoff is not None:
                        stamp = _parse_provider_time(_record_time(record))
                        if stamp is not None and stamp < cutoff:
                            continue  # aged out; not provider deletion evidence
                    pending_absences.add(key)
        for provider_id in removed_provider_ids:
            key = _key_for_provider_id(state, provider_id)
            if key and key not in seen:
                pending_absences.add(key)

        for key in sorted(pending_absences):
            record = state["messages"].get(key)
            if not record:
                continue
            prior_folder = _record_folder(record) or "inbox"
            try:
                self.provider.read_message(str(record["provider_message_id"]))
            except MessageNotFound:
                record["tombstoned"] = True
                record["in_scope"] = False
                record["folder"] = None
                record["tombstoned_at"] = observed_at
                counts[prior_folder]["tombstoned"] += 1
            else:
                record["tombstoned"] = False
                record["in_scope"] = False
                record["folder"] = None
                record["out_of_scope_at"] = observed_at
                counts[prior_folder]["out_of_scope"] += 1
            self._write_derived(record)

        state["field_set_version"] = FIELD_SET_VERSION
        for folder in FOLDERS:
            folder_state = state["folders"][folder]
            folder_state["inventory"] = sorted(by_folder[folder])
            if work[folder].sync_token:
                folder_state["delta_token"] = work[folder].sync_token
            # Use a post-sync cheap live probe as the actual watermark.  It is
            # intentionally one GET per folder and detects parser/delta wedges.
            probe = self.provider.probe_folder(folder)
            folder_state["watermark"] = probe.get("latest_at") or work[folder].watermark
            folder_state["last_successful_sync"] = observed_at

        self._write_index(state)
        self._save_state(state)
        append_line(
            self.runs_path,
            dumps_jsonl_line(
                {
                    "schema_version": 1,
                    "account": self.account,
                    "mode": mode,
                    "token_expired": token_invalid,
                    "days": days,
                    "at": observed_at,
                    "folders": counts,
                }
            ),
        )
        return SyncResult(
            account=self.account, mode=mode, folders=counts, token_expired=token_invalid
        )

    def staleness_probe(self, *, threshold_seconds: int = 60) -> dict[str, Any]:
        """Live-check each folder before a store-first review.

        The hard banner and ``review_complete=False`` are deliberately machine
        readable so future local-review commands cannot accidentally present a
        stale store as a completed mailbox review.
        """
        if threshold_seconds < 0:
            raise EmailStoreError("staleness threshold cannot be negative")
        state = self._load_state()
        details: dict[str, dict[str, Any]] = {}
        stale = False
        for folder in FOLDERS:
            live = self.provider.probe_folder(folder)
            stored = state["folders"][folder].get("watermark")
            live_at = live.get("latest_at")
            reason = None
            if live_at and not stored:
                reason = "store has no watermark"
            else:
                live_dt = _parse_provider_time(str(live_at) if live_at else None)
                stored_dt = _parse_provider_time(str(stored) if stored else None)
                if live_dt and stored_dt and live_dt > stored_dt + timedelta(seconds=threshold_seconds):
                    reason = "provider watermark is newer than the local store"
            if reason:
                stale = True
            details[folder] = {
                "live_latest_at": live_at,
                "stored_watermark": stored,
                "stale": bool(reason),
                "reason": reason,
            }
        return {
            "account": self.account,
            "store_stale": stale,
            "banner": STALE_BANNER if stale else None,
            "review_complete": not stale,
            "folders": details,
        }


def _latest_time(messages: Iterable[dict[str, Any]]) -> str | None:
    values = [value for item in messages if isinstance(item, dict)
              if (value := _message_time(item))]
    return max(values) if values else None


def _key_for_provider_id(state: dict[str, Any], provider_message_id: str) -> str | None:
    for key, record in state.get("messages", {}).items():
        if record.get("provider_message_id") == provider_message_id:
            return str(key)
    return None


def _record_time(record: dict[str, Any]) -> str | None:
    return (
        record.get("received_at")
        or record.get("sent_at")
        or record.get("modified_at")
        or record.get("observed_at")
    )


def _record_folder(record: dict[str, Any]) -> str | None:
    folder = record.get("folder")
    return str(folder) if folder in FOLDERS else None
