"""Microsoft Graph draft-only route allowlist (the outlook_graph policy).

Relocated unchanged from the Outlook assistant's ``graph_client.py``: the same
exact-route set and message/createReply shapes, still raising
``DraftPolicyError`` before any network I/O. ``SEND_ENDPOINT_PROBES`` carries
the must-deny probes the old ``check_draft_only.py`` hardcoded; the conformance
suite and ``check_mail_safety.py`` fail if the policy ever allows one.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ...contract.interface import DraftPolicyError
from ...contract.transport import RoutePolicy


class DraftOnlyRoutePolicy(RoutePolicy):
    _MESSAGE = re.compile(r"^/v1\.0/me/messages/[^/]+$")
    _REPLY = re.compile(r"^/v1\.0/me/messages/[^/]+/createReply$")
    _ATTACHMENTS = re.compile(r"^/v1\.0/me/messages/[^/]+/attachments$")
    _FOLDER_MESSAGES = re.compile(
        r"^/v1\.0/me/mailFolders(?:/(?:inbox|drafts|sentitems)"
        r"|\('(?:inbox|drafts|sentitems)'\))/messages$"
    )
    _DELTA = re.compile(
        r"^/v1\.0/me/mailFolders(?:/(?:inbox|drafts|sentitems)"
        r"|\('(?:inbox|drafts|sentitems)'\))/messages/delta$"
    )
    _EXACT = {
        ("GET", "/v1.0/me"),
        ("GET", "/v1.0/me/mailFolders/inbox/messages"),
        ("GET", "/v1.0/me/mailFolders/drafts/messages"),
        ("GET", "/v1.0/me/mailFolders/sentitems/messages"),
        ("POST", "/v1.0/me/messages"),
    }

    # Send/mutation endpoints this policy MUST deny (probed by conformance and
    # the folder-walking safety checker; a pass on any probe is a hard fail).
    SEND_ENDPOINT_PROBES = (
        ("POST", "https://graph.microsoft.com/v1.0/me/sendMail"),
        ("POST", "https://graph.microsoft.com/v1.0/me/messages/example/send"),
        ("DELETE", "https://graph.microsoft.com/v1.0/me/messages/example"),
    )

    @classmethod
    def assert_allowed(cls, method: str, url: str) -> None:
        normalized_method = method.upper()
        path = urlsplit(url).path
        if (normalized_method, path) in cls._EXACT:
            return
        if normalized_method in {"GET", "PATCH"} and cls._MESSAGE.fullmatch(path):
            return
        if normalized_method == "GET" and (
            cls._ATTACHMENTS.fullmatch(path)
            or cls._FOLDER_MESSAGES.fullmatch(path)
            or cls._DELTA.fullmatch(path)
        ):
            return
        if normalized_method == "POST" and cls._REPLY.fullmatch(path):
            return
        raise DraftPolicyError(f"Graph route blocked by draft-only policy: {method} {path}")
