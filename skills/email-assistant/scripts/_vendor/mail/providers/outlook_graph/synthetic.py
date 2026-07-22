"""Synthetic Graph-shaped mailbox for the provider conformance suite.

GENERATED data only — never seeded from real mail; every address is
``@example.com`` (fictional "Jordan Rivers" world), so the fixture can never
fight the leak guard. The synthetic transport honors the same draft-only route
allowlist as the real audited transport, dispatches the allowlisted routes
against an in-memory mailbox, and can be told to *lie* about draft evidence so
conformance can prove the provider fails closed.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from ...contract.transport import TransportError
from .provider import DraftOnlyGraphClient
from .route_policy import DraftOnlyRoutePolicy

SYNTHETIC_ACCOUNT = "jordan.rivers@example.com"
_RECRUITER = "recruiter@example.com"


class SyntheticGraphTransport:
    """In-memory, route-allowlisted stand-in for the audited HTTP transport."""

    def __init__(self) -> None:
        self.inbox: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.drafts: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.lie_about_drafts = False
        self._counter = 0

    # ── seeding (synthetic data only) ────────────────────────────────────
    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def _register(self, folder: list[dict[str, Any]], message: dict[str, Any]) -> dict[str, Any]:
        folder.append(message)
        self.by_id[str(message["id"])] = message
        return message

    def seed_inbox(
        self,
        *,
        subject: str,
        conversation_id: str,
        received_at: str = "2026-01-05T10:00:00Z",
        body: str = "Synthetic message body.",
    ) -> dict[str, Any]:
        return self._register(self.inbox, {
            "id": self._next_id("inbox"),
            "subject": subject,
            "from": {"emailAddress": {"address": _RECRUITER}},
            "toRecipients": [{"emailAddress": {"address": SYNTHETIC_ACCOUNT}}],
            "receivedDateTime": received_at,
            "isRead": False,
            "isDraft": False,
            "conversationId": conversation_id,
            "bodyPreview": body[:80],
            "body": {"contentType": "Text", "content": body},
            "webLink": "https://mail.example.com/synthetic",
        })

    def seed_sent(
        self,
        *,
        conversation_id: str,
        sent_at: str = "2026-01-05T11:00:00Z",
        subject: str = "Re: synthetic",
    ) -> dict[str, Any]:
        return self._register(self.sent, {
            "id": self._next_id("sent"),
            "subject": subject,
            "sentDateTime": sent_at,
            "isDraft": False,
            "conversationId": conversation_id,
            "webLink": "https://mail.example.com/synthetic",
        })

    def seed_draft(
        self,
        *,
        conversation_id: str,
        modified_at: str = "2026-01-05T12:00:00Z",
        subject: str = "Re: synthetic",
    ) -> dict[str, Any]:
        return self._register(self.drafts, {
            "id": self._next_id("draft"),
            "subject": subject,
            "lastModifiedDateTime": modified_at,
            "isDraft": True,
            "conversationId": conversation_id,
            "body": {"contentType": "Text", "content": "Synthetic draft body."},
            "webLink": "https://mail.example.com/synthetic",
        })

    # ── transport surface (same shape as AuditedHttpTransport.request) ──
    def request(
        self,
        method: str,
        url: str,
        access_token: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Mirror the real chokepoint: the allowlist runs before any dispatch.
        DraftOnlyRoutePolicy.assert_allowed(method, url)
        split = urlsplit(url)
        path, query = split.path, parse_qs(split.query)
        self.calls.append((method.upper(), path))
        if (method.upper(), path) == ("GET", "/v1.0/me"):
            return {
                "displayName": "Jordan Rivers",
                "mail": SYNTHETIC_ACCOUNT,
                "userPrincipalName": SYNTHETIC_ACCOUNT,
            }
        if method.upper() == "GET" and path.startswith("/v1.0/me/mailFolders/"):
            folder = path.split("/")[4]
            items = {"inbox": self.inbox, "drafts": self.drafts, "sentitems": self.sent}[folder]
            top = int(query.get("$top", ["50"])[0])
            skip = int(query.get("$skip", ["0"])[0])
            return {"value": [dict(item) for item in items[skip:skip + top]]}
        if path.startswith("/v1.0/me/messages/"):
            segments = path.split("/")
            message_id = unquote(segments[4])
            message = self.by_id.get(message_id)
            if message is None:
                raise TransportError(f"synthetic mailbox has no message {message_id!r}")
            if len(segments) == 6 and segments[5] == "createReply" and method.upper() == "POST":
                reply = self._register(self.drafts, {
                    "id": self._next_id("draft"),
                    "subject": f"Re: {message.get('subject') or ''}",
                    "lastModifiedDateTime": "2026-01-05T13:00:00Z",
                    "isDraft": not self.lie_about_drafts,
                    "conversationId": message.get("conversationId"),
                    "body": {"contentType": "Text", "content": ""},
                    "webLink": "https://mail.example.com/synthetic",
                })
                return dict(reply)
            if method.upper() == "GET":
                return dict(message)
            if method.upper() == "PATCH":
                message.update(payload or {})
                if self.lie_about_drafts:
                    message["isDraft"] = False
                return dict(message)
        if (method.upper(), path) == ("POST", "/v1.0/me/messages"):
            created = self._register(self.drafts, {
                "id": self._next_id("draft"),
                "subject": (payload or {}).get("subject"),
                "toRecipients": (payload or {}).get("toRecipients"),
                "lastModifiedDateTime": "2026-01-05T13:00:00Z",
                "isDraft": not self.lie_about_drafts,
                "conversationId": self._next_id("conversation"),
                "body": (payload or {}).get("body"),
                "webLink": "https://mail.example.com/synthetic",
            })
            return dict(created)
        raise TransportError(f"synthetic mailbox cannot dispatch {method} {path}")


class OutlookSyntheticFixture:
    """The provider-conformance fixture protocol for ``outlook_graph``.

    Attributes/methods the conformance suite relies on (every provider's
    ``synthetic.conformance_fixture()`` must return an object like this):
    ``provider``, ``seed_inbox_message``, ``seed_sent_reply``,
    ``seed_conversation_draft``, ``force_non_draft_evidence``, ``request_log``.
    """

    def __init__(self) -> None:
        self.transport = SyntheticGraphTransport()
        self.provider = DraftOnlyGraphClient("synthetic-token", transport=self.transport)
        # A small default mailbox so read paths have something to return.
        self.transport.seed_inbox(
            subject="Interview availability — Platform Engineer",
            conversation_id="conversation-alpha",
            received_at="2026-01-05T09:00:00Z",
        )
        self.transport.seed_inbox(
            subject="Application received — Example Corp",
            conversation_id="conversation-beta",
            received_at="2026-01-04T09:00:00Z",
        )
        self.transport.seed_sent(
            conversation_id="conversation-unrelated", sent_at="2026-01-03T09:00:00Z"
        )
        self.transport.seed_draft(
            conversation_id="conversation-unrelated", modified_at="2026-01-03T10:00:00Z"
        )

    def seed_inbox_message(self, *, subject: str, conversation_id: str,
                           received_at: str = "2026-01-05T10:00:00Z") -> str:
        return str(self.transport.seed_inbox(
            subject=subject, conversation_id=conversation_id, received_at=received_at
        )["id"])

    def seed_sent_reply(self, *, conversation_id: str,
                        sent_at: str = "2026-01-05T11:00:00Z") -> str:
        return str(self.transport.seed_sent(
            conversation_id=conversation_id, sent_at=sent_at
        )["id"])

    def seed_conversation_draft(self, *, conversation_id: str) -> str:
        return str(self.transport.seed_draft(conversation_id=conversation_id)["id"])

    def force_non_draft_evidence(self) -> None:
        self.transport.lie_about_drafts = True

    def request_log(self) -> list[tuple[str, str]]:
        return list(self.transport.calls)


def conformance_fixture() -> OutlookSyntheticFixture:
    """Fresh synthetic fixture (the entry point conformance discovers)."""
    return OutlookSyntheticFixture()
