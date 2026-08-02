#!/usr/bin/env python3
"""Draft-only personal Outlook CLI for repository-grounded email assistance."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

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
    "deleted",
    "review-window",
    "read",
    "sync-store",
    "store-staleness",
    "store-review",
    "store-search",
    "store-coverage",
    "match-application",
    "create-draft",
    "create-reply-draft",
    "update-draft",
)

STORE_REVIEW_SUMMARY_KEY_LIMIT = 20
_JOB_ID_QUERY_KEYS = frozenset({
    "gh_jid", "jid", "job", "job_id", "jobid", "req", "req_id", "reqid",
    "requisition", "requisition_id", "requisitionid",
})
_EXPLICIT_JOB_ID_FIELDS = (
    "requisition_id",
    "req_id",
    "job_id",
    "posting_id",
    "ats_id",
    "external_id",
    "store_key",
)
_EXPLICIT_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,127}$")
_UUID_RE = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_PATH_JOB_ID_RE = re.compile(r"(?i)^(?:\d{4,}|r\d{3,}|[a-z]{1,8}-\d{4,})$")
_EMBEDDED_REQ_RE = re.compile(r"(?i)(?:^|[_-])(r\d{3,})(?:$|[_-])")


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _compact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep live bounded-review output useful without streaming body previews."""
    fields = (
        "id",
        "subject",
        "from",
        "toRecipients",
        "receivedDateTime",
        "sentDateTime",
        "lastModifiedDateTime",
        "isDraft",
        "conversationId",
    )
    return [{key: message.get(key) for key in fields if message.get(key) is not None}
            for message in messages]


def _job_url_identifiers(value: Any) -> tuple[str, ...]:
    """Extract conservative stable job identifiers from one posting URL."""
    if not isinstance(value, str) or not value.strip():
        return ()
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ()
    found: set[str] = set()
    for key, raw in parse_qsl(parsed.query, keep_blank_values=False):
        candidate = unquote(raw).strip()
        if (
            key.casefold() in _JOB_ID_QUERY_KEYS
            and 3 <= len(candidate) <= 128
            and any(character.isdigit() for character in candidate)
            and not any(character.isspace() for character in candidate)
        ):
            found.add(candidate)
    for raw_segment in parsed.path.split("/"):
        segment = unquote(raw_segment).strip()
        if not segment or len(segment) > 128:
            continue
        if _UUID_RE.fullmatch(segment) or _PATH_JOB_ID_RE.fullmatch(segment):
            found.add(segment)
        match = _EMBEDDED_REQ_RE.search(segment)
        if match:
            found.add(match.group(1))
    return tuple(sorted(found, key=lambda item: (item.casefold(), item)))


def _job_field_identifiers(job: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract conservative identifiers from explicit per-job metadata fields."""
    found: set[str] = set()
    for field in _EXPLICIT_JOB_ID_FIELDS:
        value = job.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            candidate = str(value)
        elif isinstance(value, str):
            candidate = value.strip()
        else:
            continue
        if (
            any(character.isdigit() for character in candidate)
            and _EXPLICIT_JOB_ID_RE.fullmatch(candidate)
        ):
            found.add(candidate)
    return tuple(sorted(found, key=lambda item: (item.casefold(), item)))


def _coverage_query_families(
    *,
    manual_queries: list[str],
    applications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build deduplicated manual and active-application literal families."""
    families: dict[str, dict[str, Any]] = {}

    def add(value: Any, source: str) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        display = " ".join(value.split())
        normalized = display.casefold()
        family = families.setdefault(normalized, {"query": display, "sources": []})
        if source not in family["sources"]:
            family["sources"].append(source)

    for query in manual_queries:
        add(query, "manual")
    for application in applications:
        if not isinstance(application, Mapping):
            continue
        raw_jobs = application.get("jobs")
        jobs = [job for job in raw_jobs if isinstance(job, Mapping)] if isinstance(raw_jobs, list) else []
        active_jobs = [job for job in jobs if job.get("status") == "in_progress"]
        if not active_jobs:
            continue
        add(application.get("company"), "in_progress_company")
        for job in active_jobs:
            add(job.get("role"), "in_progress_role")
            for identifier in _job_field_identifiers(job):
                add(identifier, "job_field_identifier")
            for identifier in _job_url_identifiers(job.get("url")):
                add(identifier, "job_url_identifier")
    if not families:
        raise StoreReviewError(
            "store-coverage requires --query or at least one in-progress application family"
        )
    return list(families.values())


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
    auth = AuthManager(settings)
    token = auth.access_token()
    client = DraftOnlyGraphClient(token, token_refresher=auth.access_token)
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
        ("deleted", "list recent Deleted Items messages without restoring them"),
        ("review-window", "reconcile recent Inbox messages against Sent Items and Drafts"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--limit", type=int, default=10)
        if name in {"inbox", "sent", "deleted"}:
            command.add_argument(
                "--since",
                help="server-filter messages at or after this ISO-8601 timestamp",
            )
            command.add_argument(
                "--compact",
                action="store_true",
                help="omit body previews and web links from list output",
            )

    read = subparsers.add_parser("read", help="read one message by Graph message ID")
    read.add_argument("--message-id", required=True)

    sync = subparsers.add_parser(
        "sync-store",
        help="sync a private local Inbox/Sent/Drafts/Deleted evidence window (read-only)",
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

    search = subparsers.add_parser(
        "store-search",
        help="freshness-gated search across stored subjects, full bodies, and participants",
    )
    search.add_argument(
        "--query",
        action="append",
        required=True,
        help="literal required in the subject, full body, or sender/To/Cc participants (repeatable)",
    )
    search.add_argument(
        "--include-content",
        action="store_true",
        help="include matching private subjects, full bodies, and participants in output",
    )
    search.add_argument(
        "--threshold-seconds", type=int, default=60,
        help="newer-provider watermark tolerance before hard stale banner (default: 60)",
    )

    coverage = subparsers.add_parser(
        "store-coverage",
        help="read-only, single-scan coverage for independent literal query families",
    )
    coverage.add_argument(
        "--query",
        action="append",
        default=[],
        help="independent literal family such as a recruiter domain or thread alias (repeatable)",
    )
    coverage.add_argument(
        "--in-progress-applications",
        action="store_true",
        help="add each active company, role, explicit job ID, and stable URL job ID",
    )
    coverage.add_argument(
        "--threshold-seconds", type=int, default=60,
        help="newer-provider watermark tolerance before hard stale banner (default: 60)",
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

    update = subparsers.add_parser(
        "update-draft", help="replace the body of an existing unsent Outlook draft"
    )
    update.add_argument("--message-id", required=True)
    update.add_argument("--body-file", required=True)
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
            for company_match_key, clean_values in normalized.items():
                domains[company_match_key] = tuple(sorted(set(domains.get(company_match_key, ())) | set(clean_values)))
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


def _store_search(
    store: EmailStoreSync,
    *,
    queries: list[str],
    include_content: bool,
    threshold_seconds: int,
) -> tuple[dict[str, Any], int]:
    """Fail closed on freshness before a full-body and participant search."""
    freshness = store.staleness_probe(threshold_seconds=threshold_seconds)
    if freshness["store_stale"]:
        return freshness, 2
    data_root = config.data_root()
    if data_root is None:
        raise EmailStoreError("private email data root is not configured")
    reader = EmailStoreReader.for_account_label(
        data_root=data_root, account_label=_settings().account
    )
    report = reader.search_raw(queries=queries, include_content=include_content)
    report["freshness"] = freshness
    return report, 0 if report["audit_complete"] else 2


def _store_coverage(
    store: EmailStoreSync,
    *,
    families: list[dict[str, Any]],
    threshold_seconds: int,
) -> tuple[dict[str, Any], int]:
    """Fail closed, then evaluate all independent families in one local scan."""
    freshness = store.staleness_probe(threshold_seconds=threshold_seconds)
    if freshness["store_stale"]:
        return freshness, 2
    data_root = config.data_root()
    if data_root is None:
        raise EmailStoreError("private email data root is not configured")
    reader = EmailStoreReader.for_account_label(
        data_root=data_root, account_label=_settings().account
    )
    report = reader.coverage_raw(queries=[family["query"] for family in families])
    sources_by_query = {
        " ".join(str(family["query"]).split()).casefold(): list(family["sources"])
        for family in families
    }
    for family in report["query_families"]:
        normalized = " ".join(str(family["query"]).split()).casefold()
        family["sources"] = sources_by_query[normalized]
    report["freshness"] = freshness
    return report, 0 if report["coverage_complete"] else 2


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
    if args.command == "store-search":
        report, code = _store_search(
            _email_store(client, settings, read_only=True),
            queries=args.query,
            include_content=args.include_content,
            threshold_seconds=args.threshold_seconds,
        )
        _json(report)
        return code
    if args.command == "store-coverage":
        applications = []
        if args.in_progress_applications:
            applications, _domains = store_review_applications(config.applications_root())
        families = _coverage_query_families(
            manual_queries=args.query,
            applications=applications,
        )
        report, code = _store_coverage(
            _email_store(client, settings, read_only=True),
            families=families,
            threshold_seconds=args.threshold_seconds,
        )
        _json(report)
        return code
    if args.command == "inbox":
        messages = client.list_folder("inbox", args.limit, args.since)
        _json(_compact_messages(messages) if args.compact else messages)
    elif args.command == "sent":
        messages = client.list_folder("sentitems", args.limit, args.since)
        _json(_compact_messages(messages) if args.compact else messages)
    elif args.command == "drafts":
        _json(client.list_drafts(args.limit))
    elif args.command == "deleted":
        messages = client.list_folder("deleteditems", args.limit, args.since)
        _json(_compact_messages(messages) if args.compact else messages)
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
    elif args.command == "update-draft":
        _json(
            client.update_draft(
                draft_message_id=args.message_id,
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
