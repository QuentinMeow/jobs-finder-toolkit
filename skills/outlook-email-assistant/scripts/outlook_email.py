#!/usr/bin/env python3
"""Draft-only personal Outlook CLI for repository-grounded email assistance."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _vendor import config  # noqa: E402
from application_context import find_application_matches  # noqa: E402
from auth import (  # noqa: E402
    AuthError,
    AuthManager,
    DELEGATED_SCOPES,
    LoginRequired,
    OutlookSettings,
    dependency_status,
)
from graph_client import DraftOnlyGraphClient, GraphError  # noqa: E402

CLI_COMMANDS = (
    "doctor",
    "login",
    "logout",
    "inbox",
    "sent",
    "drafts",
    "review-window",
    "read",
    "match-application",
    "create-draft",
    "create-reply-draft",
)


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _settings(validate: bool = True) -> OutlookSettings:
    raw = config.outlook_email_config()
    settings = OutlookSettings(
        account=raw["account"],
        client_id=raw["client_id"],
        tenant=raw["tenant"],
    )
    if validate:
        settings.validate()
    return settings


def _client() -> tuple[OutlookSettings, DraftOnlyGraphClient]:
    settings = _settings()
    token = AuthManager(settings).access_token()
    client = DraftOnlyGraphClient(token)
    me = client.me()
    actual = str(me.get("mail") or me.get("userPrincipalName") or "").strip()
    if not actual or actual.casefold() != settings.account.casefold():
        raise AuthError(
            f"Graph mailbox {actual!r} does not match configured account {settings.account!r}"
        )
    return settings, client


def _read_body(path_value: str) -> str:
    path = Path(path_value).expanduser().resolve()
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GraphError(f"could not read draft body file {path}: {exc}") from exc
    if not body.strip():
        raise GraphError("draft body file is empty")
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="check dependencies, private config, and policy")
    subparsers.add_parser("login", help="authenticate by Microsoft device-code flow")
    subparsers.add_parser("logout", help="remove this mailbox's OAuth cache from the OS keyring")

    for name, help_text in (
        ("inbox", "list recent inbox messages"),
        ("sent", "list recent Sent Items messages"),
        ("drafts", "list existing Outlook drafts"),
        ("review-window", "reconcile recent Inbox messages against Sent Items and Drafts"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--limit", type=int, default=10)

    read = subparsers.add_parser("read", help="read one message by Graph message ID")
    read.add_argument("--message-id", required=True)

    match = subparsers.add_parser(
        "match-application", help="rank repository applications for email sender/subject cues"
    )
    match.add_argument("--query", required=True)
    match.add_argument("--sender", default="")
    match.add_argument("--limit", type=int, default=5)

    create = subparsers.add_parser("create-draft", help="create a new unsent Outlook draft")
    create.add_argument("--to", action="append", required=True)
    create.add_argument("--cc", action="append", default=[])
    create.add_argument("--subject", required=True)
    create.add_argument("--body-file", required=True)

    reply = subparsers.add_parser(
        "create-reply-draft", help="create and populate an unsent Outlook reply draft"
    )
    reply.add_argument("--message-id", required=True)
    reply.add_argument("--body-file", required=True)
    return parser


def _doctor() -> int:
    raw = config.outlook_email_config()
    errors: list[str] = []
    try:
        _settings().validate()
    except AuthError as exc:
        errors.append(str(exc))
    dependencies = dependency_status()
    for name, status in dependencies.items():
        if status == "missing":
            errors.append(f"dependency missing: {name}")
    _json(
        {
            "account_configured": bool(raw["account"]),
            "client_id_configured": bool(raw["client_id"]),
            "config_path": str(config.config_path()),
            "dependencies": dependencies,
            "draft_only": True,
            "errors": errors,
            "oauth_scopes": list(DELEGATED_SCOPES),
            "tenant": raw["tenant"],
        }
    )
    return 0 if not errors else 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command == "match-application":
        matches = find_application_matches(
            config.applications_root(), query=args.query, sender=args.sender, limit=args.limit
        )
        _json([match.as_dict() for match in matches])
        return 0

    settings = _settings()
    auth = AuthManager(settings)
    if args.command == "login":
        token = auth.login()
        client = DraftOnlyGraphClient(token)
        me = client.me()
        actual = str(me.get("mail") or me.get("userPrincipalName") or "").strip()
        if actual.casefold() != settings.account.casefold():
            auth.logout()
            raise AuthError(
                f"Graph mailbox {actual!r} does not match configured account; run logout"
            )
        _json({"authenticated": True, "account": actual, "draft_only": True})
        return 0
    if args.command == "logout":
        _json({"oauth_cache_removed": auth.logout()})
        return 0

    _, client = _client()
    if args.command == "inbox":
        _json(client.list_inbox(args.limit))
    elif args.command == "sent":
        _json(client.list_sent(args.limit))
    elif args.command == "drafts":
        _json(client.list_drafts(args.limit))
    elif args.command == "review-window":
        _json(client.review_window(args.limit))
    elif args.command == "read":
        _json(client.read_message(args.message_id))
    elif args.command == "create-draft":
        _json(
            client.create_draft(
                subject=args.subject,
                body_text=_read_body(args.body_file),
                to=args.to,
                cc=args.cc,
            )
        )
    elif args.command == "create-reply-draft":
        _json(
            client.create_reply_draft(
                source_message_id=args.message_id,
                body_text=_read_body(args.body_file),
            )
        )
    else:  # pragma: no cover - argparse restricts the command set
        raise GraphError(f"unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuthError, LoginRequired, GraphError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
