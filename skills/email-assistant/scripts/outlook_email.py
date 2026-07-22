#!/usr/bin/env python3
"""Draft-only personal Outlook CLI for repository-grounded email assistance."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _vendor import config  # noqa: E402
from _vendor.mail.contract.interface import MailProviderError  # noqa: E402
from _vendor.mail.providers.outlook_graph.auth import (  # noqa: E402
    AuthError,
    AuthManager,
    DELEGATED_SCOPES,
    LoginRequired,
    OutlookSettings,
    dependency_status,
)
from _vendor.mail.providers.outlook_graph.provider import (  # noqa: E402
    DraftOnlyGraphClient,
    GraphError,
)
from _vendor.mail.store_sync import EmailStoreError, EmailStoreSync  # noqa: E402
from _vendor.mail.store_review import EmailStoreReader, StoreReviewError  # noqa: E402
from _vendor.mail.reconciliation import validate_company_email_domains  # noqa: E402
from application_context import find_application_matches, store_review_applications  # noqa: E402

CLI_COMMANDS = (
    "doctor",
    "login",
    "logout",
    "inbox",
    "sent",
    "drafts",
    "review-window",
    "read",
    "sync-store",
    "store-staleness",
    "store-review",
    "match-application",
    "create-draft",
    "create-reply-draft",
)

STORE_REVIEW_SUMMARY_KEY_LIMIT = 20


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

    sync = subparsers.add_parser(
        "sync-store",
        help="sync a private local Inbox/Sent/Drafts evidence window (read-only)",
    )
    sync.add_argument(
        "--days", type=int, default=30,
        help="rolling window to capture in full, including bodies (default: 30)",
    )
    sync.add_argument(
        "--all", action="store_true",
        help="capture all in-scope history instead of a rolling window",
    )
    sync.add_argument(
        "--full", action="store_true",
        help="force an inventory-diff full resync instead of using stored delta tokens",
    )

    stale = subparsers.add_parser(
        "store-staleness",
        help="live-probe local store freshness before a store-first review",
    )
    stale.add_argument(
        "--threshold-seconds", type=int, default=60,
        help="newer-provider watermark tolerance before hard stale banner (default: 60)",
    )

    review = subparsers.add_parser(
        "store-review",
        help="freshness-gated, content-free review of every locally stored message",
    )
    review.add_argument(
        "--threshold-seconds", type=int, default=60,
        help="newer-provider watermark tolerance before hard stale banner (default: 60)",
    )
    review.add_argument(
        "--details", action="store_true",
        help="emit every content-free record and projection instead of the bounded summary",
    )

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


def _email_store(
    client: DraftOnlyGraphClient, settings: OutlookSettings, *, read_only: bool = False
) -> EmailStoreSync:
    data_root = config.data_root()
    if data_root is None:
        raise EmailStoreError(
            "paths.data_root (or JOBHUNT_DATA_ROOT) is required for the private email store"
        )
    return EmailStoreSync(
        data_root=data_root,
        provider=client,
        account_label=settings.account,
        read_only=read_only,
    )


def _domain_mapping_from_path(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return {}
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise StoreReviewError("configured company-domain mapping is unreadable") from exc
    if not isinstance(parsed, Mapping):
        raise StoreReviewError("configured company-domain mapping must be a YAML mapping")
    return parsed


def _store_review_context() -> tuple[list[dict[str, Any]], dict[str, tuple[str, ...]]]:
    """Build minimal application/domain context without exposing recruiter addresses."""
    applications, inferred = store_review_applications(config.applications_root())
    review_config = config.outlook_email_review_config()
    configured = review_config["company_domains"]
    if not isinstance(configured, Mapping):
        raise StoreReviewError("outlook_email.company_domains must be a mapping when configured")
    merged: dict[str, list[Any]] = {}
    for source in (configured, _domain_mapping_from_path(review_config["company_domains_path"])):
        for company, domains in source.items():
            if not isinstance(company, str):
                raise StoreReviewError("company-domain mapping has a non-string company key")
            values = [domains] if isinstance(domains, str) else list(domains) if isinstance(domains, (list, tuple)) else None
            if values is None:
                raise StoreReviewError("company-domain mapping values must be a domain or a list of domains")
            merged.setdefault(company, []).extend(values)

    # Explicit configuration is strict.  A shared ATS vendor is a wiring error,
    # not a permissible company identity.  Existing recruiter domains, however,
    # are only convenience hints: retain individually valid values and silently
    # omit a shared vendor rather than preventing a review of the whole store.
    domains = validate_company_email_domains(merged)
    for company, values in inferred.items():
        for value in values:
            try:
                normalized = validate_company_email_domains({company: [value]})
            except ValueError:
                continue
            for company_key, clean_values in normalized.items():
                domains[company_key] = tuple(sorted(set(domains.get(company_key, ())) | set(clean_values)))
    return applications, domains


def _store_review(store: EmailStoreSync, *, threshold_seconds: int) -> tuple[dict[str, Any], int]:
    """Fail closed on freshness before any local raw-body hydration or claims."""
    freshness = store.staleness_probe(threshold_seconds=threshold_seconds)
    if freshness["store_stale"]:
        return freshness, 2
    data_root = config.data_root()
    if data_root is None:  # _email_store already enforces this; keep it locally total.
        raise EmailStoreError("private email data root is not configured")
    applications, company_domains = _store_review_context()
    reader = EmailStoreReader.for_account_label(
        data_root=data_root, account_label=_settings().account
    )
    report = reader.review(applications=applications, company_domains=company_domains)
    report["freshness"] = freshness
    report["context_counts"] = {
        "applications": len(applications),
        "company_domain_mappings": len(company_domains),
    }
    return report, 0 if report["review_complete"] else 2


def _store_review_summary(
    report: Mapping[str, Any], *, key_limit: int = STORE_REVIEW_SUMMARY_KEY_LIMIT
) -> dict[str, Any]:
    """Bound the default CLI review result while retaining safe next-step cues."""
    if key_limit < 1:
        raise ValueError("store-review summary key limit must be positive")
    projections = report.get("projections")
    projections = projections if isinstance(projections, Mapping) else {}
    freshness = report.get("freshness")
    if not isinstance(freshness, Mapping) and isinstance(report.get("folders"), Mapping):
        # A stale store returns the staleness probe directly, before any raw
        # hydration. Preserve that bounded folder-level evidence in summary mode.
        freshness = {
            "store_stale": bool(report.get("store_stale")),
            "banner": report.get("banner"),
            "folders": report.get("folders"),
        }

    def keys(name: str) -> list[str]:
        values = projections.get(name)
        if not isinstance(values, list):
            return []
        return [str(item["message_key"]) for item in values[:key_limit]
                if isinstance(item, Mapping) and isinstance(item.get("message_key"), str)]

    summary = {
        "account": report.get("account"),
        "review_complete": bool(report.get("review_complete")),
        "store_stale": bool(report.get("store_stale", False)),
        "banner": report.get("banner"),
        "freshness": freshness,
        "integrity": report.get("integrity"),
        "counts": report.get("counts"),
        "context_counts": report.get("context_counts"),
        "sample_message_keys": {
            "needs_reply": keys("needs_reply"),
            "deadlines": keys("deadlines"),
            "unresolved": keys("unresolved"),
            "limit_per_queue": key_limit,
        },
        "details_available": bool(projections),
        "details_flag": "--details",
    }
    # The full reader has its own content-free tripwire.  This projection never
    # introduces arbitrary record fields, so it stays bounded and safe to print.
    return summary


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
    if args.command == "sync-store":
        if args.all and args.days != 30:
            raise EmailStoreError("use either --all or --days, not both")
        days = None if args.all else args.days
        _json(_email_store(client, settings).sync(days=days, force_full=args.full).as_dict())
        return 0
    if args.command == "store-staleness":
        _json(
            _email_store(client, settings, read_only=True).staleness_probe(
                threshold_seconds=args.threshold_seconds
            )
        )
        return 0
    if args.command == "store-review":
        report, code = _store_review(
            _email_store(client, settings, read_only=True), threshold_seconds=args.threshold_seconds
        )
        _json(report if args.details else _store_review_summary(report))
        return code
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
    except (AuthError, LoginRequired, MailProviderError, EmailStoreError, StoreReviewError) as exc:
        # MailProviderError covers GraphError, DraftPolicyError, and transport
        # failures — the same surface the old GraphError hierarchy caught.
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
