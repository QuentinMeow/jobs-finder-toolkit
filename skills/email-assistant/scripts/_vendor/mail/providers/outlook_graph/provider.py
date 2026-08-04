"""A narrowly allowlisted Microsoft Graph client that can only read mail and edit drafts.

The ``outlook_graph`` provider behind the send-less ``MailProvider`` contract.
Behavior-identical relocation of the Outlook assistant's ``graph_client.py``:
same routes, same Sent/Drafts duplicate-reply preflight, same ``isDraft: true``
assertions. Network I/O goes through the contract's audited transport with the
draft-only route allowlist (``route_policy.py``).
"""
from __future__ import annotations

import html
import hashlib
from dataclasses import dataclass
from typing import Any, Callable, ClassVar
from urllib.parse import quote, urlencode

from ...contract.interface import (
    DraftPolicyError,
    MailCapabilities,
    MailProvider,
    MailProviderError,
    MessageNotFound,
    SyncTokenExpired,
)
from ...contract.transport import AuditedHttpTransport, TransportError
from .reconciliation import reconcile_message, reconcile_recent
from .route_policy import DraftOnlyRoutePolicy

__all__ = [
    "DraftOnlyGraphClient",
    "DraftOnlyRoutePolicy",
    "DraftPolicyError",
    "GraphError",
    "live_provider",
]

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
MAX_LIST_LIMIT = 2000
PAGE_SIZE = 50
REPLY_RECONCILIATION_LIMIT = 500
# Graph only keeps move-stable provider IDs when every relevant request carries
# this preference.  The email store keys exclusively on those immutable IDs.
IMMUTABLE_ID_HEADERS = {"Prefer": 'IdType="ImmutableId"'}
# The exact initial delta field set is part of Graph's opaque delta token.  A
# change is deliberately versioned so callers trigger a planned full resync.
DELTA_FIELD_SET_VERSION = 1
DELTA_SELECT = (
    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,sentDateTime,"
    "lastModifiedDateTime,isRead,isDraft,bodyPreview,conversationId,"
    "internetMessageId,parentFolderId,webLink"
)
SYNC_WELL_KNOWN_FOLDERS = ("inbox", "sentitems", "drafts", "deleteditems")


class GraphError(MailProviderError):
    """Microsoft Graph request failure."""


@dataclass
class DraftOnlyGraphClient(MailProvider):
    access_token: str
    transport: Any = None
    base_url: str = GRAPH_BASE_URL
    token_refresher: Callable[[], str] | None = None

    name: ClassVar[str] = "outlook_graph"
    route_policy: ClassVar[type[DraftOnlyRoutePolicy]] = DraftOnlyRoutePolicy

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = AuditedHttpTransport(
                DraftOnlyRoutePolicy,
                provider=self.name,
                provider_label="Microsoft Graph",
            )

    def capabilities(self) -> MailCapabilities:
        # Draft-capable: Microsoft grants mail-read/write WITHOUT mail-send.
        return MailCapabilities(read=True, drafts=True, delta_sync=True, search=False)

    def verify_account(self) -> dict[str, Any]:
        return self.me()

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path, params)
        return self._request_url(method, url, payload=payload)

    def _request_url(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not url.startswith(f"{self.base_url}/"):
            raise GraphError("Graph delta link used an unexpected host or API version")
        # Belt: assert the allowlist here too, so even a replaced/fake
        # transport (as in the unit tests) never sees a blocked route.
        DraftOnlyRoutePolicy.assert_allowed(method, url)
        try:
            return self.transport.request(
                method,
                url,
                self.access_token,
                payload,
                headers=IMMUTABLE_ID_HEADERS,
            )
        except TransportError as exc:
            # Long all-time syncs can outlive Graph's access token. A rejected
            # GET is safe to replay once after refreshing; call the transport
            # directly for the retry so a second 401 cannot form a loop. Draft
            # POST/PATCH requests are never replayed automatically.
            if (
                exc.status_code != 401
                or method.upper() != "GET"
                or self.token_refresher is None
            ):
                raise
            refreshed = self.token_refresher()
            if not isinstance(refreshed, str) or not refreshed:
                raise GraphError("Microsoft authentication refresh returned no access token")
            self.access_token = refreshed
            return self.transport.request(
                method,
                url,
                self.access_token,
                payload,
                headers=IMMUTABLE_ID_HEADERS,
            )

    @staticmethod
    def _message_path(message_id: str) -> str:
        if not message_id:
            raise GraphError("message ID is required")
        return f"/me/messages/{quote(message_id, safe='')}"

    @staticmethod
    def _assert_draft(message: dict[str, Any]) -> dict[str, Any]:
        if message.get("isDraft") is not True:
            raise DraftPolicyError("Graph did not confirm isDraft: true; refusing mailbox write")
        if not message.get("id"):
            raise DraftPolicyError("Graph draft response did not include a message ID")
        return message

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/me", params={"$select": "displayName,mail,userPrincipalName"})

    @staticmethod
    def _discovered_folder_key(display_name: str, folder_id: str) -> str:
        del display_name  # Folder names may change; provider IDs are the stable identity.
        digest = hashlib.sha256(folder_id.encode("utf-8")).hexdigest()[:10]
        return f"folder-{digest}"

    def _list_folder_collection(self, path: str) -> list[dict[str, Any]]:
        folders: list[dict[str, Any]] = []
        next_url: str | None = None
        while True:
            data = (
                self._request_url("GET", next_url)
                if next_url
                else self._request(
                    "GET",
                    path,
                    params={
                        "includeHiddenFolders": "true",
                        "$top": 100,
                        "$select": (
                            "id,displayName,parentFolderId,childFolderCount,totalItemCount"
                        ),
                    },
                )
            )
            folders.extend(item for item in (data.get("value") or []) if isinstance(item, dict))
            possible_next = data.get("@odata.nextLink")
            if not isinstance(possible_next, str) or not possible_next:
                return folders
            next_url = possible_next

    def list_mail_folders(self) -> list[dict[str, str]]:
        """Discover every Outlook mail folder, including Archive and custom folders."""
        canonical_ids: dict[str, str] = {}
        for well_known in SYNC_WELL_KNOWN_FOLDERS:
            item = self._request(
                "GET",
                f"/me/mailFolders/{well_known}",
                params={"$select": "id,displayName"},
            )
            folder_id = str(item.get("id") or "")
            if not folder_id:
                raise GraphError(f"Graph omitted the {well_known} folder ID")
            canonical_ids[folder_id] = well_known

        discovered: list[dict[str, Any]] = []
        pending = self._list_folder_collection("/me/mailFolders")
        seen_ids: set[str] = set()
        while pending:
            item = pending.pop(0)
            folder_id = str(item.get("id") or "")
            if not folder_id or folder_id in seen_ids:
                continue
            seen_ids.add(folder_id)
            discovered.append(item)
            if int(item.get("childFolderCount") or 0) > 0:
                encoded = quote(folder_id, safe="")
                pending.extend(self._list_folder_collection(f"/me/mailFolders/{encoded}/childFolders"))

        result: list[dict[str, str]] = []
        for item in discovered:
            folder_id = str(item.get("id") or "")
            display_name = str(item.get("displayName") or "Unnamed folder").strip()
            key = canonical_ids.get(folder_id) or self._discovered_folder_key(
                display_name, folder_id
            )
            result.append({"key": key, "id": folder_id, "display_name": display_name})
        missing = set(SYNC_WELL_KNOWN_FOLDERS) - {item["key"] for item in result}
        if missing:
            raise GraphError(
                "Graph folder discovery omitted required folder(s): " + ", ".join(sorted(missing))
            )
        return sorted(result, key=lambda item: (item["key"] not in SYNC_WELL_KNOWN_FOLDERS, item["display_name"].casefold(), item["key"]))

    def _list_folder(
        self, folder: str, limit: int | None, since: str | None = None
    ) -> list[dict[str, Any]]:
        if not isinstance(folder, str) or not folder:
            raise DraftPolicyError("mail folder ID is required")
        bounded = None if limit is None else max(1, min(int(limit), MAX_LIST_LIMIT))
        order_by = {
            "inbox": "receivedDateTime desc",
            "drafts": "lastModifiedDateTime desc",
            "sentitems": "sentDateTime desc",
            "deleteditems": "lastModifiedDateTime desc",
        }.get(folder, "lastModifiedDateTime desc")
        filter_field = {
            "inbox": "receivedDateTime",
            "drafts": "lastModifiedDateTime",
            "sentitems": "sentDateTime",
            "deleteditems": "lastModifiedDateTime",
        }.get(folder, "lastModifiedDateTime")
        messages: list[dict[str, Any]] = []
        next_url: str | None = None
        while bounded is None or len(messages) < bounded:
            page_limit = PAGE_SIZE if bounded is None else min(PAGE_SIZE, bounded - len(messages))
            params: dict[str, Any] = {
                "$top": page_limit,
                "$orderby": order_by,
                "$select": (
                    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,"
                    "sentDateTime,lastModifiedDateTime,isRead,isDraft,bodyPreview,"
                    "conversationId,internetMessageId,webLink"
                ),
            }
            if since:
                params["$filter"] = f"{filter_field} ge {since}"
            if messages and next_url is None:
                # Synthetic/fake transports used by older tests may omit Graph's
                # next-link. Keep the legacy skip fallback there; live Graph uses
                # the opaque continuation URL so concurrent changes cannot make us
                # manufacture an offset locally.
                params["$skip"] = len(messages)
            data = (
                self._request_url("GET", next_url)
                if next_url is not None
                else self._request(
                    "GET", f"/me/mailFolders/{quote(folder, safe='')}/messages", params=params
                )
            )
            page = list(data.get("value") or [])
            messages.extend(page)
            if len(page) < page_limit:
                break
            possible_next = data.get("@odata.nextLink")
            next_url = possible_next if isinstance(possible_next, str) and possible_next else None
        return messages

    def list_inbox(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._list_folder("inbox", limit)

    def list_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        drafts = self._list_folder("drafts", limit)
        for draft in drafts:
            self._assert_draft(draft)
        return drafts

    def list_sent(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._list_folder("sentitems", limit)

    def list_deleted(self, limit: int = 10) -> list[dict[str, Any]]:
        """List Deleted Items without mutating or restoring messages."""
        return self._list_folder("deleteditems", limit)

    def list_folder(
        self, folder: str, limit: int | None = None, since: str | None = None
    ) -> list[dict[str, Any]]:
        """Walk an approved folder without a count cap, optionally server-filtered."""
        return self._list_folder(folder, limit, since)

    def probe_folder(self, folder: str) -> dict[str, Any]:
        messages = self._list_folder(folder, 1)
        latest = None
        if messages:
            item = messages[0]
            latest = next(
                (
                    item.get(key)
                    for key in ("receivedDateTime", "sentDateTime", "lastModifiedDateTime")
                    if item.get(key)
                ),
                None,
            )
        return {"folder": folder, "latest_at": latest, "item_count": None}

    def review_window(self, limit: int = 20) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 50))
        return reconcile_recent(
            self.list_inbox(bounded),
            self.list_sent(bounded),
            self.list_drafts(bounded),
        )

    def read_message(self, message_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            self._message_path(message_id),
            params={
                "$select": (
                    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,isDraft,"
                    "sentDateTime,lastModifiedDateTime,body,bodyPreview,conversationId,"
                    "internetMessageId,parentFolderId,webLink"
                )
            },
        )

    def attachment_metadata(self, message_id: str) -> list[dict[str, Any]]:
        """Fetch only attachment descriptors; attachment bytes never cross this API.

        Graph's file-attachment payload contains ``contentBytes`` unless callers
        constrain the select list.  Keep the allowlisted metadata shape narrow
        even if Graph adds fields later.
        """
        path = f"{self._message_path(message_id)}/attachments"
        metadata: list[dict[str, Any]] = []
        skip = 0
        while True:
            data = self._request(
                "GET",
                path,
                params={
                    "$top": PAGE_SIZE,
                    "$skip": skip,
                    "$select": "id,name,size,contentType,isInline",
                },
            )
            page = list(data.get("value") or [])
            for item in page:
                metadata.append(
                    {
                        "attachment_id": str(item.get("id") or ""),
                        "name": str(item.get("name") or ""),
                        "size": int(item.get("size") or 0),
                        "content_type": str(item.get("contentType") or ""),
                        "is_inline": bool(item.get("isInline", False)),
                    }
                )
            if len(page) < PAGE_SIZE:
                break
            skip += len(page)
        return metadata

    def delta_sync(self, folder: str, sync_token: str | None = None) -> dict[str, Any]:
        """Read one folder's Graph delta stream, preserving the opaque token.

        The first call (``sync_token=None``) is a full inventory walk.  Later
        calls replay changes in arbitrary order; the store engine is therefore
        idempotent and resolves removals only after all folders complete.
        """
        if not isinstance(folder, str) or not folder:
            raise DraftPolicyError("mail folder ID is required")
        url = sync_token or self._url(
            f"/me/mailFolders/{quote(folder, safe='')}/messages/delta",
            params={"$select": DELTA_SELECT},
        )
        messages: list[dict[str, Any]] = []
        try:
            while True:
                data = self._request_url("GET", url)
                messages.extend(list(data.get("value") or []))
                next_link = data.get("@odata.nextLink")
                if not next_link:
                    delta_link = data.get("@odata.deltaLink")
                    if not isinstance(delta_link, str) or not delta_link:
                        raise GraphError("Graph delta response omitted @odata.deltaLink")
                    return {
                        "messages": messages,
                        "sync_token": delta_link,
                        "field_set_version": DELTA_FIELD_SET_VERSION,
                    }
                if not isinstance(next_link, str):
                    raise GraphError("Graph delta response returned malformed @odata.nextLink")
                url = next_link
        except MessageNotFound as exc:
            raise SyncTokenExpired("Graph delta token expired; full resync required") from exc
        except TransportError as exc:
            if exc.status_code in {400, 404, 410}:
                raise SyncTokenExpired("Graph delta token expired; full resync required") from exc
            raise

    @staticmethod
    def _recipients(addresses: list[str]) -> list[dict[str, dict[str, str]]]:
        cleaned = [address.strip() for address in addresses if address.strip()]
        if not cleaned:
            raise GraphError("at least one recipient is required")
        return [{"emailAddress": {"address": address}} for address in cleaned]

    def create_draft(
        self,
        *,
        subject: str,
        body_text: str,
        to: list[str],
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        if not subject.strip() or not body_text.strip():
            raise GraphError("draft subject and body must not be empty")
        payload: dict[str, Any] = {
            "subject": subject.strip(),
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": self._recipients(to),
        }
        if cc:
            payload["ccRecipients"] = self._recipients(cc)
        created = self._request("POST", "/me/messages", payload=payload)
        return self._assert_draft(created)

    def update_draft(self, *, draft_message_id: str, body_text: str) -> dict[str, Any]:
        """Replace one existing draft's body after verifying draft evidence.

        This is intentionally an exact-body replacement.  Callers that are
        revising an Outlook reply draft must not prepend a second reply above
        stale text or create another draft for the same conversation.
        """
        if not body_text.strip():
            raise GraphError("draft body must not be empty")
        draft_path = self._message_path(draft_message_id)
        current = self._request(
            "GET",
            draft_path,
            params={"$select": "id,isDraft"},
        )
        self._assert_draft(current)
        updated = self._request(
            "PATCH",
            draft_path,
            payload={"body": {"contentType": "Text", "content": body_text}},
        )
        self._assert_draft(updated)
        verified = self._request(
            "GET",
            draft_path,
            params={"$select": "id,subject,toRecipients,ccRecipients,isDraft,body,webLink"},
        )
        return self._assert_draft(verified)

    @staticmethod
    def _prepend_reply(reply_text: str, existing_body: dict[str, Any]) -> dict[str, str]:
        content_type = str(existing_body.get("contentType") or "Text")
        existing = str(existing_body.get("content") or "")
        if content_type.casefold() == "html":
            escaped = html.escape(reply_text).replace("\n", "<br>")
            return {"contentType": "HTML", "content": f"{escaped}<br><br>{existing}"}
        separator = "\n\n" if existing else ""
        return {"contentType": "Text", "content": f"{reply_text}{separator}{existing}"}

    def create_reply_draft(self, *, source_message_id: str, body_text: str) -> dict[str, Any]:
        if not body_text.strip():
            raise GraphError("reply body must not be empty")
        source_path = self._message_path(source_message_id)
        source = self._request(
            "GET",
            source_path,
            params={
                "$select": (
                    "id,subject,from,receivedDateTime,isDraft,bodyPreview,conversationId,webLink"
                )
            },
        )
        if source.get("isDraft") is True:
            raise DraftPolicyError("source message is already a draft; refusing to create another")
        state = reconcile_message(
            source,
            self.list_sent(REPLY_RECONCILIATION_LIMIT),
            self.list_drafts(REPLY_RECONCILIATION_LIMIT),
        )
        if state["status"] in {"already_replied", "already_replied_with_redundant_draft"}:
            raise DraftPolicyError(
                "a later Sent reply already exists for this message; refusing to create a duplicate "
                "draft. Review Sent Items and manually remove any redundant draft"
            )
        if state["status"] == "draft_exists":
            raise DraftPolicyError(
                "a draft already exists for this conversation; review it instead of creating a "
                "duplicate"
            )
        created = self._request("POST", f"{source_path}/createReply")
        self._assert_draft(created)
        draft_path = self._message_path(str(created["id"]))
        updated = self._request(
            "PATCH",
            draft_path,
            payload={"body": self._prepend_reply(body_text, created.get("body") or {})},
        )
        self._assert_draft(updated)
        verified = self._request(
            "GET",
            draft_path,
            params={"$select": "id,subject,toRecipients,ccRecipients,isDraft,webLink"},
        )
        return self._assert_draft(verified)


def live_provider() -> DraftOnlyGraphClient:
    """Authenticated client for the owner-requested read-only ``--live``
    conformance run. Uses the same config + keyring auth as the skill CLI and
    pins the Graph mailbox to the configured account. Never called by CI."""
    import config  # canonical automation/shared/config.py or the skill's _vendor copy

    from .auth import AuthError, AuthManager, OutlookSettings

    raw = config.outlook_email_config()
    settings = OutlookSettings(
        account=raw["account"], client_id=raw["client_id"], tenant=raw["tenant"]
    )
    settings.validate()
    auth = AuthManager(settings)
    token = auth.access_token()
    client = DraftOnlyGraphClient(token, token_refresher=auth.access_token)
    me = client.me()
    actual = str(me.get("mail") or me.get("userPrincipalName") or "").strip()
    if not actual or actual.casefold() != settings.account.casefold():
        raise AuthError(
            f"Graph mailbox {actual!r} does not match configured account {settings.account!r}"
        )
    return client
