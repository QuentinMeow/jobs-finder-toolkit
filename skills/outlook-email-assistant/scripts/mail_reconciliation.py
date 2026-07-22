"""Correlate inbox messages with Sent Items and Drafts without mutating mail."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _timestamp(message: dict[str, Any], *fields: str) -> datetime | None:
    for field in fields:
        raw = str(message.get(field) or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _summary(message: dict[str, Any], *, timestamp_field: str) -> dict[str, Any]:
    return {
        "id": message.get("id"),
        "subject": message.get("subject"),
        "timestamp": message.get(timestamp_field),
        "webLink": message.get("webLink"),
    }


def reconcile_message(
    inbox_message: dict[str, Any],
    sent_messages: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return reply/draft state for one inbound message, keyed by conversation ID."""
    conversation_id = str(inbox_message.get("conversationId") or "").strip()
    received_at = _timestamp(inbox_message, "receivedDateTime")

    related_sent = [
        item for item in sent_messages
        if conversation_id and str(item.get("conversationId") or "") == conversation_id
    ]
    sent_after = [
        item for item in related_sent
        if received_at is None
        or (_timestamp(item, "sentDateTime", "lastModifiedDateTime") or datetime.min.replace(
            tzinfo=timezone.utc
        )) > received_at
    ]
    sent_after.sort(
        key=lambda item: _timestamp(item, "sentDateTime", "lastModifiedDateTime")
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    related_drafts = [
        item for item in drafts
        if conversation_id and str(item.get("conversationId") or "") == conversation_id
    ]
    related_drafts.sort(
        key=lambda item: _timestamp(item, "lastModifiedDateTime")
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    if sent_after and related_drafts:
        status = "already_replied_with_redundant_draft"
        warning = (
            "⚠️ ACTION REQUIRED: A later Sent reply exists and a draft remains in this "
            "conversation. Review the Sent reply, then manually delete the redundant draft in "
            "Outlook if it is no longer needed."
        )
    elif sent_after:
        status = "already_replied"
        warning = None
    elif related_drafts:
        status = "draft_exists"
        warning = (
            "⚠️ ACTION REQUIRED: A draft already exists in this conversation. Review and "
            "edit that draft instead of creating another one."
        )
    else:
        status = "reply_may_be_needed"
        warning = None

    return {
        "message": {
            "id": inbox_message.get("id"),
            "subject": inbox_message.get("subject"),
            "from": inbox_message.get("from"),
            "receivedDateTime": inbox_message.get("receivedDateTime"),
            "conversationId": inbox_message.get("conversationId"),
            "bodyPreview": inbox_message.get("bodyPreview"),
            "webLink": inbox_message.get("webLink"),
        },
        "status": status,
        "action_required": warning is not None,
        "warning": warning,
        "review_note": (
            "Review the message content and sender before deciding whether a reply is useful."
            if status == "reply_may_be_needed" else None
        ),
        "latest_sent_reply": _summary(sent_after[0], timestamp_field="sentDateTime")
        if sent_after else None,
        "existing_drafts": [
            _summary(item, timestamp_field="lastModifiedDateTime") for item in related_drafts
        ],
    }


def reconcile_recent(
    inbox_messages: list[dict[str, Any]],
    sent_messages: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an action-oriented, read-only review window for recent mail."""
    messages = [reconcile_message(item, sent_messages, drafts) for item in inbox_messages]
    counts: dict[str, int] = {}
    for item in messages:
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1
    alerts = [str(item["warning"]) for item in messages if item.get("warning")]
    return {
        "draft_only": True,
        "sending_is_manual": True,
        "summary": {
            "inbox_messages_reviewed": len(inbox_messages),
            "sent_messages_compared": len(sent_messages),
            "drafts_compared": len(drafts),
            "status_counts": counts,
            "action_required_count": len(alerts),
        },
        "alerts": alerts,
        "messages": messages,
    }
