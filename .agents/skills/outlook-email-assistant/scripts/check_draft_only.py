#!/usr/bin/env python3
"""Fail when executable Outlook-assistant code gains email-sending capability."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_FILES = (
    SCRIPT_DIR / "auth.py",
    SCRIPT_DIR / "graph_client.py",
    SCRIPT_DIR / "application_context.py",
    SCRIPT_DIR / "mail_reconciliation.py",
    SCRIPT_DIR / "outlook_email.py",
)
ALLOWED_COMMANDS = {
    "doctor", "login", "logout", "inbox", "sent", "drafts", "review-window", "read",
    "match-application", "create-draft", "create-reply-draft",
}
BANNED_SOURCE_PATTERNS = (
    re.compile(r"mail\.send", re.IGNORECASE),
    re.compile(r"sendmail", re.IGNORECASE),
    re.compile(r"/send(?:\b|[\"'])", re.IGNORECASE),
    re.compile(r"\bdef\s+\w*send\w*\s*\(", re.IGNORECASE),
)


def _literal_assignment(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                value = node.value
                if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                    return {
                        item.value for item in value.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    }
    return None


def check() -> list[str]:
    errors: list[str] = []
    for path in RUNTIME_FILES:
        source = path.read_text(encoding="utf-8")
        for pattern in BANNED_SOURCE_PATTERNS:
            if pattern.search(source):
                errors.append(f"{path.name}: banned sending pattern {pattern.pattern!r}")

    auth_tree = ast.parse((SCRIPT_DIR / "auth.py").read_text(encoding="utf-8"))
    scopes = _literal_assignment(auth_tree, "DELEGATED_SCOPES")
    expected_scopes = {
        "https://graph.microsoft.com/User.Read",
        "https://graph.microsoft.com/Mail.ReadWrite",
    }
    if scopes != expected_scopes:
        errors.append(f"auth.py: delegated scopes changed: {sorted(scopes or [])}")

    cli_tree = ast.parse((SCRIPT_DIR / "outlook_email.py").read_text(encoding="utf-8"))
    commands = _literal_assignment(cli_tree, "CLI_COMMANDS")
    if commands != ALLOWED_COMMANDS:
        errors.append(f"outlook_email.py: CLI command surface changed: {sorted(commands or [])}")

    sys.path.insert(0, str(SCRIPT_DIR))
    from graph_client import DraftOnlyRoutePolicy, DraftPolicyError

    for method, url in (
        ("POST", "https://graph.microsoft.com/v1.0/me/sendMail"),
        ("POST", "https://graph.microsoft.com/v1.0/me/messages/example/send"),
        ("DELETE", "https://graph.microsoft.com/v1.0/me/messages/example"),
    ):
        try:
            DraftOnlyRoutePolicy.assert_allowed(method, url)
        except DraftPolicyError:
            pass
        else:
            errors.append(f"route policy unexpectedly allowed {method} {url}")
    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print(f"DRAFT-ONLY POLICY FAIL: {error}", file=sys.stderr)
        return 1
    print("draft-only policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
