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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..store.blobs import BlobCorrupt, BlobStore
from ..store.identifiers import IdentifierRegistry
from ..store.serialization import loads_yaml
from . import reconciliation
from .store_sync import FOLDERS

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
    banned = {
        "subject", "sender", "from", "body", "body_text", "content", "bodypreview",
        "participants", "recipients", "torecipients", "ccrecipients", "emailaddress",
        "address",
    }
    if isinstance(value, Mapping):
        return all(
            str(key).casefold() not in banned and _content_free(child)
            for key, child in value.items()
        )
    if isinstance(value, (tuple, list)):
        return all(_content_free(item) for item in value)
    return True


def _participant_records(message: Mapping[str, Any]) -> list[dict[str, str]]:
    """Normalize sender and To/Cc mailboxes from one raw provider message."""
    found: dict[tuple[str, str, str], dict[str, str]] = {}
    fields = (
        ("from", "sender"),
        ("sender", "sender"),
        ("toRecipients", "to"),
        ("ccRecipients", "cc"),
    )

    def add(value: Any, kind: str) -> None:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                add(item, kind)
            return
        if not isinstance(value, Mapping):
            return
        mailbox = value.get("emailAddress")
        mailbox = mailbox if isinstance(mailbox, Mapping) else value
        name = str(mailbox.get("name") or "").strip()
        address = str(mailbox.get("address") or "").strip()
        if not name and not address:
            return
        key = (kind, name.casefold(), address.casefold())
        found[key] = {"kind": kind, "name": name, "address": address}

    for field, kind in fields:
        add(message.get(field), kind)
    order = {"sender": 0, "to": 1, "cc": 2}
    return sorted(
        found.values(),
        key=lambda item: (
            order[item["kind"]],
            item["address"].casefold(),
            item["name"].casefold(),
        ),
    )


def _normalize_queries(queries: Iterable[str]) -> list[tuple[str, str]]:
    """Return stable display/normalized literal pairs, removing duplicates."""
    normalized_queries: list[tuple[str, str]] = []
    seen_queries: set[str] = set()
    for value in queries:
        if not isinstance(value, str) or not value.strip():
            raise StoreReviewError("mail-store queries must be non-empty strings")
        display = " ".join(value.split())
        normalized = display.casefold()
        if normalized not in seen_queries:
            normalized_queries.append((display, normalized))
            seen_queries.add(normalized)
    if not normalized_queries:
        raise StoreReviewError("at least one mail-store query is required")
    return normalized_queries


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
        self._envelopes: dict[str, dict[str, Any]] | None = None
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

    def _envelope_map(self) -> dict[str, dict[str, Any]]:
        """Build one private, read-only-in-practice snapshot for keyed lookups."""
        if self._envelopes is None:
            messages = self.state().get("messages") or {}
            self._envelopes = {
                str(key): dict(record)
                for key, record in messages.items()
                if isinstance(record, dict)
            }
        return self._envelopes

    def envelopes(self) -> dict[str, dict[str, Any]]:
        """Return defensive copies without rebuilding the snapshot from sync state."""
        return {key: dict(record) for key, record in self._envelope_map().items()}

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
        # A complete all-history review calls this once per message. Looking up
        # through ``envelopes()`` rebuilt the complete defensive-copy map on
        # every call, turning review into O(messages^2) work.
        envelope = self._envelope_map().get(message_key)
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
                     ("folder", "direction", "in_scope", "tombstoned", "received_at", "sent_at", "modified_at")):
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

    def _scan_search_documents(self) -> dict[str, Any]:
        """Hydrate and normalize each current discovered-folder message once."""
        integrity = self.integrity()
        state = self.state()
        folder_state = state.get("folders") if isinstance(state.get("folders"), dict) else {}
        folders = tuple(sorted(set(FOLDERS) | {str(folder) for folder in folder_state}))
        unsynced_folders = [
            folder
            for folder in folders
            if not isinstance(folder_state.get(folder), dict)
            or not folder_state[folder].get("last_successful_sync")
        ]
        envelopes = self.envelopes()
        current = {
            key: envelope
            for key, envelope in envelopes.items()
            if envelope.get("in_scope") is True
            and envelope.get("tombstoned") is not True
            and envelope.get("folder") in folders
        }
        scanned_by_folder = {folder: 0 for folder in folders}
        unavailable: list[str] = []
        documents: list[dict[str, Any]] = []
        for key, envelope in sorted(current.items()):
            try:
                message = self.hydrate(key)
                raw_message = self._raw_payload(envelope)["message"]
            except StoreReviewError:
                unavailable.append(key)
                continue
            folder = str(message.get("folder") or "")
            scanned_by_folder[folder] += 1
            subject = str(message.get("subject") or "")
            body = str(message.get("body_text") or "")
            participants = _participant_records(raw_message)
            fields = {
                "subject": " ".join(subject.split()).casefold(),
                "body": " ".join(body.split()).casefold(),
                "participants": " ".join(
                    " ".join(part.split())
                    for participant in participants
                    for part in (participant["name"], participant["address"])
                    if part
                ).casefold(),
            }
            documents.append({
                "message_key": key,
                "folder": folder,
                "direction": message.get("direction"),
                "timestamp": message.get("timestamp"),
                "subject": subject,
                "body_text": body,
                "participants": participants,
                "fields": fields,
                "combined": "\n".join(fields.values()),
            })

        messages_scanned = sum(scanned_by_folder.values())
        return {
            "folders": folders,
            "integrity": integrity,
            "stored_messages": len(envelopes),
            "current_in_scope_messages": len(current),
            "documents": documents,
            "messages_scanned": messages_scanned,
            "scanned_by_folder": scanned_by_folder,
            "unavailable_message_keys": unavailable,
            "unsynced_folders": unsynced_folders,
            "complete": (
                integrity.ok
                and not unavailable
                and not unsynced_folders
                and messages_scanned == len(current)
            ),
        }

    def search_raw(
        self,
        *,
        queries: Iterable[str],
        include_content: bool = False,
    ) -> dict[str, Any]:
        """Search every current subject/body/participant set deterministically.

        Query terms are case-insensitive literals and are ANDed across the
        subject, full raw body, and normalized sender/To/Cc participant names
        and addresses. Results default to neutral keys and folder provenance;
        callers must explicitly opt in before mailbox content is returned. The
        method is local and read-only: it performs no provider or filesystem
        writes.
        """
        normalized_queries = _normalize_queries(queries)
        scan = self._scan_search_documents()
        matches: list[dict[str, Any]] = []
        for document in scan["documents"]:
            if not all(term in document["combined"] for _display, term in normalized_queries):
                continue
            match: dict[str, Any] = {
                "message_key": document["message_key"],
                "folder": document["folder"],
                "direction": document["direction"],
                "timestamp": document["timestamp"],
                "matched_fields": [
                    name
                    for name, text in document["fields"].items()
                    if any(term in text for _display, term in normalized_queries)
                ],
            }
            if include_content:
                match["subject"] = document["subject"]
                match["body_text"] = document["body_text"]
                match["participants"] = document["participants"]
            matches.append(match)

        output = {
            "account": self.account,
            "read_only": True,
            "audit_complete": scan["complete"],
            "queries": [display for display, _normalized in normalized_queries],
            "query_mode": (
                "all case-insensitive literals across full subject, body, and "
                "sender/To/Cc participants"
            ),
            "folders": list(scan["folders"]),
            "unsynced_folders": scan["unsynced_folders"],
            "integrity": scan["integrity"].as_dict(),
            "counts": {
                "stored_messages": scan["stored_messages"],
                "current_in_scope_messages": scan["current_in_scope_messages"],
                "messages_scanned": scan["messages_scanned"],
                "matches": len(matches),
                "scanned_by_folder": scan["scanned_by_folder"],
                "unavailable_messages": len(scan["unavailable_message_keys"]),
            },
            "unavailable_message_keys": scan["unavailable_message_keys"],
            "matches": matches,
            "content_included": include_content,
        }
        if not include_content and not _content_free(output):
            raise StoreReviewError("store search attempted to expose mailbox content")
        return output

    def coverage_raw(self, *, queries: Iterable[str]) -> dict[str, Any]:
        """Evaluate independent literal families in one complete raw-store scan."""
        normalized_queries = _normalize_queries(queries)
        scan = self._scan_search_documents()
        matches_by_query = {
            normalized: {folder: [] for folder in scan["folders"]}
            for _display, normalized in normalized_queries
        }
        for document in scan["documents"]:
            for _display, normalized in normalized_queries:
                if normalized in document["combined"]:
                    matches_by_query[normalized][document["folder"]].append(
                        document["message_key"]
                    )
        query_families = [
            {
                "query": display,
                "match_count": sum(
                    len(keys) for keys in matches_by_query[normalized].values()
                ),
                "matches_by_folder": {
                    folder: {
                        "match_count": len(matches_by_query[normalized][folder]),
                        "message_keys": matches_by_query[normalized][folder],
                    }
                    for folder in scan["folders"]
                },
            }
            for display, normalized in normalized_queries
        ]
        zero_matches = [
            family["query"] for family in query_families if family["match_count"] == 0
        ]
        output = {
            "account": self.account,
            "read_only": True,
            "coverage_complete": scan["complete"],
            "query_mode": (
                "independent case-insensitive literals across full subject, body, and "
                "sender/To/Cc participants"
            ),
            "folders": list(scan["folders"]),
            "unsynced_folders": scan["unsynced_folders"],
            "integrity": scan["integrity"].as_dict(),
            "counts": {
                "stored_messages": scan["stored_messages"],
                "current_in_scope_messages": scan["current_in_scope_messages"],
                "messages_scanned": scan["messages_scanned"],
                "query_families": len(query_families),
                "zero_match_queries": len(zero_matches),
                "scanned_by_folder": scan["scanned_by_folder"],
                "unavailable_messages": len(scan["unavailable_message_keys"]),
            },
            "unavailable_message_keys": scan["unavailable_message_keys"],
            "query_families": query_families,
            "zero_match_queries": zero_matches,
            "content_included": False,
        }
        if not _content_free(output):
            raise StoreReviewError("store coverage attempted to expose mailbox content")
        return output

    def review(
        self,
        *,
        applications: Iterable[Mapping[str, Any]],
        company_domains: Mapping[str, Iterable[str]],
        human_confirmations: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Categorize every stored message locally and return only safe projections."""
        integrity = self.integrity()
        envelopes = self.envelopes()
        hydrated: list[dict[str, Any]] = []
        unavailable: list[str] = []
        for key in sorted(envelopes):
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
            "review_complete": integrity.ok and not unavailable and len(records) == len(envelopes),
            "integrity": integrity.as_dict(),
            "counts": {
                "stored_messages": len(envelopes),
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
