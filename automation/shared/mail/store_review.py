"""Read-only local email-store integrity and store-first review plumbing.

The sync engine owns all writes.  This module does the opposite: it resolves a
stored message key to its current raw blob *only in memory*, feeds the existing
deterministic reconciler, and returns content-free records/projections.  It never
contacts a provider, writes an application, changes local mailbox state, or
persists a body/subject/sender outside the ignored raw zone.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..store.blobs import BlobCorrupt, BlobStore
from ..store.identifiers import IdentifierRegistry
from ..store.serialization import loads_yaml
from . import reconciliation

ATTACHMENT_METADATA_FIELDS = frozenset(
    {"attachment_id", "name", "size", "content_type", "is_inline"}
)


class StoreReviewError(RuntimeError):
    """A local email-store reader cannot safely complete its requested view."""


def _contains_attachment_bytes(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() == "contentbytes" or _contains_attachment_bytes(child):
                return True
    elif isinstance(value, list):
        return any(_contains_attachment_bytes(item) for item in value)
    return False


def _content_free(value: Any) -> bool:
    """Assert the return value has no message content-bearing field names."""
    banned = {"subject", "sender", "from", "body", "body_text", "content", "bodypreview"}
    if isinstance(value, Mapping):
        return all(
            str(key).casefold() not in banned and _content_free(child)
            for key, child in value.items()
        )
    if isinstance(value, (tuple, list)):
        return all(_content_free(item) for item in value)
    return True


@dataclass(frozen=True)
class LocalStoreIntegrity:
    account: str
    messages: int
    manifests: int
    derived_messages: int
    index_rows: int
    raw_blobs_checked: int
    attachments_checked: int
    errors: tuple[dict[str, str], ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        # Errors only carry neutral message keys/fetch IDs/paths categories.
        return {
            "account": self.account,
            "ok": self.ok,
            "counts": {
                "messages": self.messages,
                "manifests": self.manifests,
                "derived_messages": self.derived_messages,
                "index_rows": self.index_rows,
                "raw_blobs_checked": self.raw_blobs_checked,
                "attachments_checked": self.attachments_checked,
            },
            "errors": [dict(error) for error in self.errors],
        }


class EmailStoreReader:
    """Read-only access to one neutral account partition of the email store."""

    def __init__(self, *, data_root: Path, account: str) -> None:
        self.root = Path(data_root).expanduser().resolve() / "email"
        self.account = account
        self._blobs = BlobStore(self.root / "raw" / "_blobs")
        self._state: dict[str, Any] | None = None
        self._manifests: dict[str, tuple[Path, dict[str, Any]]] | None = None
        self._manifest_errors: list[dict[str, str]] | None = None
        self._raw_payloads: dict[str, dict[str, Any]] = {}

    @classmethod
    def for_account_label(cls, *, data_root: Path, account_label: str) -> "EmailStoreReader":
        root = Path(data_root).expanduser().resolve() / "email"
        registry = IdentifierRegistry(root / "state" / "identifiers.yaml")
        account = registry.resolve_label("account", account_label)
        if not account:
            raise StoreReviewError("the configured mailbox has no local email-store partition")
        return cls(data_root=data_root, account=account)

    @property
    def state_path(self) -> Path:
        return self.root / "state" / self.account / "sync.json"

    @property
    def index_path(self) -> Path:
        return self.root / "index" / self.account / "messages.jsonl"

    def state(self) -> dict[str, Any]:
        if self._state is None:
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise StoreReviewError("local email sync state is unavailable or malformed") from exc
            if not isinstance(data, dict) or data.get("account") != self.account:
                raise StoreReviewError("local email sync state does not match its account partition")
            messages = data.get("messages")
            if not isinstance(messages, dict):
                raise StoreReviewError("local email sync state has no message map")
            self._state = data
        return self._state

    def envelopes(self) -> dict[str, dict[str, Any]]:
        messages = self.state().get("messages") or {}
        return {str(key): dict(record) for key, record in messages.items() if isinstance(record, dict)}

    def _manifest_map(self) -> dict[str, tuple[Path, dict[str, Any]]]:
        if self._manifests is not None:
            return self._manifests
        found: dict[str, tuple[Path, dict[str, Any]]] = {}
        errors: list[dict[str, str]] = []
        raw = self.root / "raw"
        for path in sorted(raw.glob("*/**/manifest.json")):
            if "_blobs" in path.parts:
                continue
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Account association is unavailable for a malformed manifest;
                # only flag it when its path already names this neutral account.
                if self.account in path.parts:
                    errors.append({"kind": "raw_manifest_unreadable", "ref": path.name})
                continue
            if not isinstance(manifest, dict):
                continue
            context = manifest.get("context")
            fetch_id = manifest.get("fetch_id")
            if (
                isinstance(context, dict)
                and context.get("account") == self.account
                and isinstance(fetch_id, str)
            ):
                if fetch_id in found:
                    errors.append({"kind": "raw_manifest_duplicate_fetch", "ref": fetch_id})
                found[fetch_id] = (path, manifest)
        self._manifests = found
        self._manifest_errors = errors
        return found

    def _raw_payload(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        fetch_id = envelope.get("raw_fetch_id")
        if not isinstance(fetch_id, str) or not fetch_id:
            raise StoreReviewError("stored message has no current raw fetch reference")
        cached = self._raw_payloads.get(fetch_id)
        if cached is not None:
            return cached
        found = self._manifest_map().get(fetch_id)
        if found is None:
            raise StoreReviewError("current raw fetch manifest is missing")
        _path, manifest = found
        payload = manifest.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("blob"), str):
            raise StoreReviewError("current raw manifest has no payload blob")
        try:
            decoded = json.loads(self._blobs.read(payload["blob"]).decode("utf-8"))
        except (BlobCorrupt, OSError, ValueError, UnicodeDecodeError) as exc:
            raise StoreReviewError("current raw message blob is missing or malformed") from exc
        if not isinstance(decoded, dict) or not isinstance(decoded.get("message"), dict):
            raise StoreReviewError("current raw payload does not contain a message envelope")
        self._raw_payloads[fetch_id] = decoded
        return decoded

    def _manifest_payload(self, fetch_id: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
        """Read one manifest payload only in memory, caching it by neutral fetch ID."""
        cached = self._raw_payloads.get(fetch_id)
        if cached is not None:
            return cached
        payload = manifest.get("payload")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("blob"), str):
            raise StoreReviewError("raw manifest has no payload blob")
        try:
            decoded = json.loads(self._blobs.read(payload["blob"]).decode("utf-8"))
        except (BlobCorrupt, OSError, ValueError, UnicodeDecodeError) as exc:
            raise StoreReviewError("raw message blob is missing or malformed") from exc
        if not isinstance(decoded, dict) or not isinstance(decoded.get("message"), dict):
            raise StoreReviewError("raw payload does not contain a message envelope")
        self._raw_payloads[fetch_id] = decoded
        return decoded

    def hydrate(self, message_key: str) -> dict[str, Any]:
        """Deliberately resolve one raw message into memory, never for direct output."""
        envelope = self.envelopes().get(message_key)
        if envelope is None:
            raise StoreReviewError("stored message key was not found")
        payload = self._raw_payload(envelope)
        return reconciliation.hydrate_stored_message(envelope, payload["message"])

    def integrity(self) -> LocalStoreIntegrity:
        """Audit one local account without emitting mailbox content."""
        errors: list[dict[str, str]] = []
        envelopes = self.envelopes()
        manifests = self._manifest_map()
        errors.extend(self._manifest_errors or [])
        derived_paths = list((self.root / "derived" / self.account / "messages").glob("**/message.yaml"))
        derived_by_key: dict[str, Path] = {}
        for path in derived_paths:
            try:
                record = loads_yaml(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                errors.append({"kind": "derived_unreadable", "ref": path.name})
                continue
            key = record.get("message_key") if isinstance(record, dict) else None
            if not isinstance(key, str) or not key:
                errors.append({"kind": "derived_missing_key", "ref": path.name})
                continue
            if key in derived_by_key:
                errors.append({"kind": "derived_duplicate_key", "ref": key})
            derived_by_key[key] = path

        index_rows: dict[str, dict[str, Any]] = {}
        try:
            for line in self.index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                key = row.get("message_key") if isinstance(row, dict) else None
                if not isinstance(key, str) or not key:
                    errors.append({"kind": "index_missing_key", "ref": "messages.jsonl"})
                elif key in index_rows:
                    errors.append({"kind": "index_duplicate_key", "ref": key})
                else:
                    index_rows[key] = row
        except (OSError, ValueError):
            errors.append({"kind": "index_unreadable", "ref": "messages.jsonl"})

        blobs_checked = 0
        attachments_checked = 0
        # Audit every account-owned raw payload, not only the current pointer
        # in sync state.  A prior raw revision must never become an attachment-
        # bytes loophole just because a message was refreshed later.
        for fetch_id, (_path, manifest) in sorted(manifests.items()):
            try:
                payload = self._manifest_payload(fetch_id, manifest)
            except StoreReviewError:
                errors.append({"kind": "raw_unavailable", "ref": fetch_id})
                continue
            blobs_checked += 1
            if _contains_attachment_bytes(payload):
                errors.append({"kind": "attachment_bytes_present", "ref": fetch_id})
            metadata = payload.get("attachment_metadata")
            if not isinstance(metadata, list):
                errors.append({"kind": "attachment_metadata_missing", "ref": fetch_id})
                continue
            for item in metadata:
                attachments_checked += 1
                if not isinstance(item, dict) or set(item) - ATTACHMENT_METADATA_FIELDS:
                    errors.append({"kind": "attachment_metadata_shape", "ref": fetch_id})
                    break

        for key, envelope in sorted(envelopes.items()):
            if key not in derived_by_key:
                errors.append({"kind": "derived_missing", "ref": key})
            if key not in index_rows:
                errors.append({"kind": "index_missing", "ref": key})
            elif any(index_rows[key].get(field) != envelope.get(field) for field in
                     ("folder", "in_scope", "tombstoned", "received_at", "sent_at", "modified_at")):
                errors.append({"kind": "index_state_mismatch", "ref": key})
            try:
                self._raw_payload(envelope)
            except StoreReviewError:
                errors.append({"kind": "raw_unavailable", "ref": key})

        for key in sorted(set(derived_by_key) - set(envelopes)):
            errors.append({"kind": "derived_orphan", "ref": key})
        for key in sorted(set(index_rows) - set(envelopes)):
            errors.append({"kind": "index_orphan", "ref": key})
        return LocalStoreIntegrity(
            account=self.account,
            messages=len(envelopes),
            manifests=len(manifests),
            derived_messages=len(derived_by_key),
            index_rows=len(index_rows),
            raw_blobs_checked=blobs_checked,
            attachments_checked=attachments_checked,
            errors=tuple(errors),
        )

    def review(
        self,
        *,
        applications: Iterable[Mapping[str, Any]],
        company_domains: Mapping[str, Iterable[str]],
        human_confirmations: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Categorize every stored message locally and return only safe projections."""
        integrity = self.integrity()
        hydrated: list[dict[str, Any]] = []
        unavailable: list[str] = []
        for key in sorted(self.envelopes()):
            try:
                hydrated.append(self.hydrate(key))
            except StoreReviewError:
                unavailable.append(key)
        result = reconciliation.reconcile_messages(
            hydrated,
            applications,
            company_domains,
            human_confirmations=human_confirmations,
        )
        records = result["records"]
        categories = Counter(
            category for record in records for category in record.get("categories", ())
        )
        output = {
            "account": self.account,
            "review_complete": integrity.ok and not unavailable and len(records) == len(self.envelopes()),
            "integrity": integrity.as_dict(),
            "counts": {
                "stored_messages": len(self.envelopes()),
                "hydrated_messages": len(hydrated),
                "unavailable_messages": len(unavailable),
                "categorized_messages": len(records),
                "categories": dict(sorted(categories.items())),
                "unresolved": len(result["projections"]["unresolved"]),
                "needs_reply": len(result["projections"]["needs_reply"]),
                "deadlines": len(result["projections"]["deadlines"]),
            },
            "unavailable_message_keys": unavailable,
            "records": records,
            "projections": result["projections"],
        }
        if not _content_free(output):  # Defensive tripwire before a CLI can print.
            raise StoreReviewError("store review attempted to expose mailbox content")
        return output
