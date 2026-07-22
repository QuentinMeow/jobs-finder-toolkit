#!/usr/bin/env python3
"""Provider conformance suite — every mail provider must pass.

Two modes (design/raw-data-layer/03-provider-interfaces.md, isolation rules):

* **Synthetic (default, CI-safe).** Runs against the provider's generated
  fixture mailbox (``providers/<name>/synthetic.py`` →
  ``conformance_fixture()``; ``example.com`` addresses only, never seeded from
  real mail). No network, no credentials.
* **Read-only live (``--live``).** Owner opt-in only, never CI (decided
  2026-07-21). Authenticates the real provider and performs READ operations
  only; the audited transport's log is then asserted to contain nothing but
  GET requests. No draft is created, nothing is mutated.

The suite probes each provider's route policy against *that provider's* send
endpoints (``SEND_ENDPOINT_PROBES``) and fails on any pass; verifies no
send-like operation exists on the provider surface; and checks the declared
capabilities are honest (unsupported operations fail closed, draft mutations
carry draft evidence, the duplicate-reply preflight refuses duplicates).

Usage (repo venv):
    .venv/bin/python automation/shared/mail/contract/conformance.py
    .venv/bin/python automation/shared/mail/contract/conformance.py --provider outlook_graph --live
"""
from __future__ import annotations

import argparse
import importlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):  # direct script run: re-anchor as a package module
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    _pkg = Path(__file__).resolve().parents[1].name  # "mail"
    module = importlib.import_module(f"{_pkg}.contract.conformance")
    raise SystemExit(module.main())

from .interface import (  # noqa: E402
    CapabilityNotSupported,
    DraftPolicyError,
    MailCapabilities,
    MailProvider,
)

_SEND_LIKE_RE = re.compile(r"send(?!er)", re.IGNORECASE)
DEFAULT_PROVIDER = "outlook_graph"


@dataclass
class ConformanceResult:
    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed.append(name)
        else:
            self.failures.append(f"{name}: {detail}" if detail else name)

    @property
    def ok(self) -> bool:
        return not self.failures


def _provider_package(name: str) -> str:
    root = __package__.rsplit(".contract", 1)[0]
    return f"{root}.providers.{name}"


def load_fixture_factory(name: str) -> Callable[[], Any]:
    module = importlib.import_module(f"{_provider_package(name)}.synthetic")
    return module.conformance_fixture


def load_live_factory(name: str) -> Callable[[], MailProvider]:
    module = importlib.import_module(f"{_provider_package(name)}.provider")
    return module.live_provider


# ── shared structural checks ─────────────────────────────────────────────

def _check_structure(provider: MailProvider, result: ConformanceResult) -> None:
    result.check(
        "provider-implements-contract",
        isinstance(provider, MailProvider),
        f"{type(provider).__name__} is not a MailProvider",
    )
    send_like = [
        attr for attr in dir(provider)
        if not attr.startswith("_") and _SEND_LIKE_RE.search(attr)
    ]
    result.check(
        "no-send-surface",
        not send_like,
        f"send-like attribute(s) on provider: {send_like}",
    )
    caps = provider.capabilities()
    result.check(
        "capabilities-shape",
        isinstance(caps, MailCapabilities),
        f"capabilities() returned {type(caps).__name__}",
    )
    policy = provider.route_policy
    if policy is None or not callable(getattr(policy, "assert_allowed", None)):
        result.check("route-policy-present", False, "provider declares no route policy")
        return
    result.check("route-policy-present", True)
    probes = tuple(getattr(policy, "SEND_ENDPOINT_PROBES", ()) or ())
    result.check(
        "send-probes-declared",
        bool(probes),
        "route policy declares no SEND_ENDPOINT_PROBES",
    )
    for method, url in probes:
        try:
            policy.assert_allowed(method, url)
        except Exception:
            result.check(f"send-endpoint-denied [{method} {url}]", True)
        else:
            result.check(
                f"send-endpoint-denied [{method} {url}]", False,
                "route policy ALLOWED a send/mutation endpoint",
            )


def _expect_raises(fn: Callable[[], Any], exc: type[BaseException]) -> bool:
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


# ── synthetic mode ───────────────────────────────────────────────────────

def run_synthetic(fixture_factory: Callable[[], Any]) -> ConformanceResult:
    result = ConformanceResult()
    fixture = fixture_factory()
    provider: MailProvider = fixture.provider
    _check_structure(provider, result)
    caps = provider.capabilities()

    # Read surface.
    inbox = provider.list_inbox(10)
    result.check("list-inbox", isinstance(inbox, list) and len(inbox) >= 1,
                 "empty/invalid inbox listing from the synthetic mailbox")
    result.check("list-sent", isinstance(provider.list_sent(10), list))
    drafts = provider.list_drafts(10)
    result.check(
        "drafts-carry-evidence",
        all(item.get("isDraft") is True for item in drafts),
        "a listed draft lacked draft evidence",
    )
    if inbox:
        message = provider.read_message(str(inbox[0]["id"]))
        result.check("read-message", message.get("id") == inbox[0]["id"],
                     "read_message did not return the requested message")
    window = provider.review_window(10)
    result.check(
        "review-window-read-only-contract",
        window.get("draft_only") is True and window.get("sending_is_manual") is True,
        "review_window must declare draft_only + sending_is_manual",
    )

    # Undeclared capabilities fail closed.
    if not caps.delta_sync:
        result.check(
            "delta-sync-fails-closed",
            _expect_raises(lambda: provider.delta_sync("inbox"), CapabilityNotSupported),
            "delta_sync did not raise CapabilityNotSupported",
        )
    if not caps.search:
        result.check(
            "search-fails-closed",
            _expect_raises(lambda: provider.search("interview"), CapabilityNotSupported),
            "search did not raise CapabilityNotSupported",
        )

    if not caps.drafts:
        result.check(
            "draft-ops-fail-closed",
            _expect_raises(
                lambda: provider.create_draft(
                    subject="x", body_text="y", to=["someone@example.com"]
                ),
                CapabilityNotSupported,
            ),
            "read-only provider did not refuse create_draft",
        )
        return result

    # Draft-capable providers: evidence + duplicate-reply preflight.
    created = provider.create_draft(
        subject="Conformance draft",
        body_text="Synthetic-only draft body.",
        to=["hiring.team@example.com"],
    )
    result.check("create-draft-evidence", created.get("isDraft") is True,
                 "created draft lacked draft evidence")

    fixture = fixture_factory()
    provider = fixture.provider
    replied = fixture.seed_inbox_message(
        subject="Synthetic thread", conversation_id="conversation-replied",
        received_at="2026-01-05T10:00:00Z",
    )
    fixture.seed_sent_reply(
        conversation_id="conversation-replied", sent_at="2026-01-05T11:00:00Z"
    )
    result.check(
        "preflight-refuses-after-sent-reply",
        _expect_raises(
            lambda: provider.create_reply_draft(
                source_message_id=replied, body_text="duplicate"
            ),
            DraftPolicyError,
        ),
        "provider drafted a reply although a later Sent reply exists",
    )

    fixture = fixture_factory()
    provider = fixture.provider
    drafted = fixture.seed_inbox_message(
        subject="Synthetic thread", conversation_id="conversation-drafted",
    )
    fixture.seed_conversation_draft(conversation_id="conversation-drafted")
    result.check(
        "preflight-refuses-existing-draft",
        _expect_raises(
            lambda: provider.create_reply_draft(
                source_message_id=drafted, body_text="duplicate"
            ),
            DraftPolicyError,
        ),
        "provider drafted a duplicate although a conversation draft exists",
    )

    fixture = fixture_factory()
    provider = fixture.provider
    fixture.force_non_draft_evidence()
    result.check(
        "draft-evidence-tripwire",
        _expect_raises(
            lambda: provider.create_draft(
                subject="Conformance draft",
                body_text="Synthetic-only draft body.",
                to=["hiring.team@example.com"],
            ),
            DraftPolicyError,
        ),
        "provider accepted a mutation without draft evidence",
    )
    return result


# ── read-only live mode (owner opt-in; never CI) ─────────────────────────

def run_live(provider: MailProvider) -> ConformanceResult:
    result = ConformanceResult()
    _check_structure(provider, result)
    account = provider.verify_account()
    result.check("live-verify-account", bool(account), "verify_account returned nothing")
    result.check("live-list-inbox", isinstance(provider.list_inbox(5), list))
    result.check("live-list-sent", isinstance(provider.list_sent(5), list))
    drafts = provider.list_drafts(5)
    result.check(
        "live-drafts-carry-evidence",
        all(item.get("isDraft") is True for item in drafts),
        "a live draft listing item lacked draft evidence",
    )
    window = provider.review_window(5)
    result.check(
        "live-review-window",
        window.get("draft_only") is True,
        "review_window must declare draft_only",
    )
    audit = getattr(provider.transport, "audit_log", None)
    if audit is None:
        result.check("live-read-only-proof", False,
                     "provider transport has no audit log to prove read-only")
    else:
        methods = {entry["method"] for entry in audit}
        result.check(
            "live-read-only-proof",
            methods <= {"GET"},
            f"non-GET request observed during the live run: {sorted(methods)}",
        )
    return result


def _report(result: ConformanceResult, label: str) -> int:
    for name in result.passed:
        print(f"PASS {name}")
    for failure in result.failures:
        print(f"FAIL {failure}", file=sys.stderr)
    status = "PASS" if result.ok else "FAIL"
    print(f"mail conformance [{label}]: {status} "
          f"({len(result.passed)} passed, {len(result.failures)} failed)")
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--provider", default=DEFAULT_PROVIDER,
                        help=f"provider folder name (default: {DEFAULT_PROVIDER})")
    parser.add_argument(
        "--live", action="store_true",
        help="owner opt-in READ-ONLY run against the real account (never CI); "
             "requires config + a cached login",
    )
    args = parser.parse_args(argv)
    if args.live:
        print(f"read-only LIVE conformance for {args.provider!r} — no mailbox mutation")
        provider = load_live_factory(args.provider)()
        return _report(run_live(provider), f"{args.provider} live")
    return _report(
        run_synthetic(load_fixture_factory(args.provider)),
        f"{args.provider} synthetic",
    )


if __name__ == "__main__":
    raise SystemExit(main())
