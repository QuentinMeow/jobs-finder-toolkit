"""A narrowly allowlisted Microsoft Graph client that can only read mail and edit drafts."""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from mail_reconciliation import reconcile_message, reconcile_recent

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
MAX_LIST_LIMIT = 2000
PAGE_SIZE = 50
REPLY_RECONCILIATION_LIMIT = 500


class GraphError(RuntimeError):
    """Microsoft Graph request failure."""


class DraftPolicyError(GraphError):
    """The requested operation is outside the permanent draft-only boundary."""


class DraftOnlyRoutePolicy:
    _MESSAGE = re.compile(r"^/v1\.0/me/messages/[^/]+$")
    _REPLY = re.compile(r"^/v1\.0/me/messages/[^/]+/createReply$")
    _EXACT = {
        ("GET", "/v1.0/me"),
        ("GET", "/v1.0/me/mailFolders/inbox/messages"),
        ("GET", "/v1.0/me/mailFolders/drafts/messages"),
        ("GET", "/v1.0/me/mailFolders/sentitems/messages"),
        ("POST", "/v1.0/me/messages"),
    }

    @classmethod
    def assert_allowed(cls, method: str, url: str) -> None:
        normalized_method = method.upper()
        path = urlsplit(url).path
        if (normalized_method, path) in cls._EXACT:
            return
        if normalized_method in {"GET", "PATCH"} and cls._MESSAGE.fullmatch(path):
            return
        if normalized_method == "POST" and cls._REPLY.fullmatch(path):
            return
        raise DraftPolicyError(f"Graph route blocked by draft-only policy: {method} {path}")


class HttpTransport:
    def request(
        self,
        method: str,
        url: str,
        access_token: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GraphError(f"Microsoft Graph returned HTTP {exc.code}: {detail[:1000]}") from exc
        except URLError as exc:
            raise GraphError(f"Microsoft Graph connection failed: {exc.reason}") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GraphError("Microsoft Graph returned invalid JSON") from exc


@dataclass
class DraftOnlyGraphClient:
    access_token: str
    transport: Any = None
    base_url: str = GRAPH_BASE_URL

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = HttpTransport()

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
