"""A narrowly allowlisted Microsoft Graph client that can only read mail and edit drafts.

The ``outlook_graph`` provider behind the send-less ``MailProvider`` contract.
Behavior-identical relocation of the Outlook assistant's ``graph_client.py``:
same routes, same Sent/Drafts duplicate-reply preflight, same ``isDraft: true``
assertions. Network I/O goes through the contract's audited transport with the
draft-only route allowlist (``route_policy.py``).
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import quote, urlencode

from ...contract.interface import (
    DraftPolicyError,
    MailCapabilities,
    MailProvider,
    MailProviderError,
)
from ...contract.transport import AuditedHttpTransport
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


class GraphError(MailProviderError):
    """Microsoft Graph request failure."""


@dataclass
class DraftOnlyGraphClient(MailProvider):
    access_token: str
    transport: Any = None
    base_url: str = GRAPH_BASE_URL

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
        # delta_sync/search arrive with the email-store stage, not stage 1.
        return MailCapabilities(read=True, drafts=True, delta_sync=False, search=False)

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
        # Belt: assert the allowlist here too, so even a replaced/fake
        # transport (as in the unit tests) never sees a blocked route.
        DraftOnlyRoutePolicy.assert_allowed(method, url)
        return self.transport.request(method, url, self.access_token, payload)

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

    def _list_folder(self, folder: str, limit: int) -> list[dict[str, Any]]:
        if folder not in {"inbox", "drafts", "sentitems"}:
            raise DraftPolicyError(f"mail folder blocked by policy: {folder}")
        bounded = max(1, min(int(limit), MAX_LIST_LIMIT))
        order_by = {
            "inbox": "receivedDateTime desc",
            "drafts": "lastModifiedDateTime desc",
            "sentitems": "sentDateTime desc",
        }[folder]
        messages: list[dict[str, Any]] = []
        while len(messages) < bounded:
            page_limit = min(PAGE_SIZE, bounded - len(messages))
            params: dict[str, Any] = {
                "$top": page_limit,
                "$orderby": order_by,
                "$select": (
                    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,"
                    "sentDateTime,lastModifiedDateTime,isRead,isDraft,bodyPreview,"
                    "conversationId,internetMessageId,webLink"
                ),
            }
            if messages:
                params["$skip"] = len(messages)
            data = self._request(
                "GET",
                f"/me/mailFolders/{folder}/messages",
                params=params,
            )
            page = list(data.get("value") or [])
            messages.extend(page)
            if len(page) < page_limit:
                break
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
                    "internetMessageId,webLink"
                )
            },
        )

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
    token = AuthManager(settings).access_token()
    client = DraftOnlyGraphClient(token)
    me = client.me()
    actual = str(me.get("mail") or me.get("userPrincipalName") or "").strip()
    if not actual or actual.casefold() != settings.account.casefold():
        raise AuthError(
            f"Graph mailbox {actual!r} does not match configured account {settings.account!r}"
        )
    return client
