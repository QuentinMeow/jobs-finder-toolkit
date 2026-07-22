#!/usr/bin/env python3
"""Folder-walking mail-safety checker — fail on ANY send-capable surface.

Replaces the old fixed-file ``check_draft_only.py`` (which scanned a hardcoded
five-file list). This checker walks EVERY provider folder under
``providers/`` — no hardcoded file lists, so a new provider folder is covered
the day it appears (design/raw-data-layer/03-provider-interfaces.md §2b). Per
provider it enforces:

1. **Banned source patterns** in every ``*.py`` file: send scopes/routes
   (``Mail.Send``, ``sendMail``, ``/send``, Gmail's send-capable scopes) and
   send-named function definitions. The single declared
   ``SEND_ENDPOINT_PROBES`` literal is exempt — those URLs exist to be DENIED,
   and check 3 executes that denial.
2. **Import bans**: provider SDKs (runtime-generated API surfaces cannot be
   statically bounded), non-stdlib HTTP clients that would bypass the audited
   transport, direct mail protocols (``smtplib``/``imaplib``/``poplib``), and
   any cross-provider import.
3. **Route-policy probes**: every provider ships ``route_policy.py`` with a
   non-empty ``SEND_ENDPOINT_PROBES``; each probe must raise. A policy that
   allows one is a hard fail.
4. **Scope pins**: any ``*SCOPES``-style literal in a provider must be
   registered here with its exact expected value (the generalization of the
   old ``DELEGATED_SCOPES`` pin).

``--consumer <scripts-dir>`` additionally scans a consumer skill's scripts
(excluding ``tests/`` and the generated ``_vendor/``) for the banned patterns
and pins known CLI surfaces (``outlook_email.py``'s ``CLI_COMMANDS``).

Usage (repo venv; also run by the pre-commit hook):
    .venv/bin/python automation/shared/mail/check_mail_safety.py \
        --consumer skills/email-assistant/scripts
"""
from __future__ import annotations

import argparse
import ast
import importlib
import re
import sys
from pathlib import Path

MAIL_ROOT = Path(__file__).resolve().parent
DEFAULT_PROVIDERS_ROOT = MAIL_ROOT / "providers"
PROBES_NAME = "SEND_ENDPOINT_PROBES"

BANNED_SOURCE_PATTERNS = (
    re.compile(r"mail\.send", re.IGNORECASE),
    re.compile(r"sendmail", re.IGNORECASE),
    re.compile(r"/send(?:\b|[\"'])", re.IGNORECASE),
    re.compile(r"\bdef\s+\w*send\w*\s*\(", re.IGNORECASE),
    re.compile(r"gmail\.(?:send|compose|modify|insert)", re.IGNORECASE),
    re.compile(r"mail\.google\.com", re.IGNORECASE),
)

# Import roots a provider folder may never use: provider SDKs, transport
# bypasses, direct mail protocols. Auth endpoints may use stdlib urllib.
BANNED_IMPORT_ROOTS = {
    "googleapiclient", "google", "google_auth_oauthlib", "google_auth_httplib2",
    "msgraph", "msgraph_core", "msal", "azure", "kiota_abstractions",
    "requests", "httpx", "aiohttp", "urllib3",
    "smtplib", "imaplib", "poplib",
}

# Exact expected value for every ``*SCOPES`` literal in a provider folder.
# A scope literal that is missing here — or that drifted — is a failure.
PROVIDER_SCOPE_PINS: dict[tuple[str, str, str], set[str]] = {
    ("outlook_graph", "auth.py", "DELEGATED_SCOPES"): {
        "https://graph.microsoft.com/User.Read",
        "https://graph.microsoft.com/Mail.ReadWrite",
    },
    ("outlook_graph", "auth.py", "OAUTH_SCOPES"): {
        "openid", "profile", "offline_access",
        "https://graph.microsoft.com/User.Read",
        "https://graph.microsoft.com/Mail.ReadWrite",
    },
}
_SCOPES_NAME_RE = re.compile(r"(?i)(?:^|_)scopes?$")

# Known consumer CLIs: filename -> exact allowed command surface.
CONSUMER_CLI_PINS: dict[str, set[str]] = {
    "outlook_email.py": {
        "doctor", "login", "logout", "inbox", "sent", "drafts", "review-window",
        "read", "match-application", "create-draft", "create-reply-draft",
    },
}


def _python_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _literal_str_elements(node: ast.AST, env: dict[str, set[str]]) -> set[str] | None:
    """String elements of a tuple/list/set literal; resolves one ``*name`` level."""
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return None
    out: set[str] = set()
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            out.add(element.value)
        elif isinstance(element, ast.Starred) and isinstance(element.value, ast.Name):
            referenced = env.get(element.value.id)
            if referenced is None:
                return None
            out.update(referenced)
        else:
            return None
    return out


def _assignments(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    yield target.id, node


def _probe_line_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Line spans of ``SEND_ENDPOINT_PROBES`` assignments (pattern-scan exempt)."""
    spans = []
    for name, node in _assignments(tree):
        if name == PROBES_NAME:
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def _scan_patterns(path: Path, source: str, tree: ast.AST | None,
                   label: str) -> list[str]:
    exempt = _probe_line_ranges(tree) if tree is not None else []
    errors = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        if any(start <= lineno <= end for start, end in exempt):
            continue
        for pattern in BANNED_SOURCE_PATTERNS:
            if pattern.search(line):
                errors.append(
                    f"{label}:{lineno}: banned sending pattern {pattern.pattern!r}"
                )
    return errors


def _import_roots(tree: ast.AST):
    """Yield (root, resolved-module-display) for every import in the module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], alias.name, 0
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0] if module else ""
            yield root, module, node.level


def _check_provider_file(path: Path, provider: str, siblings: set[str],
                         label: str) -> list[str]:
    errors: list[str] = []
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{label}: does not parse: {exc}"]
    errors.extend(_scan_patterns(path, source, tree, label))

    for root, module, level in _import_roots(tree):
        if level == 0 and root in BANNED_IMPORT_ROOTS:
            errors.append(f"{label}: banned import {module!r} (SDK/transport-bypass ban)")
        # Cross-provider reach: absolute (…providers.<other>…) or relative
        # (`from ..<other> import …` climbs out of this provider's folder).
        segments = module.split(".") if module else []
        if "providers" in segments:
            after = segments[segments.index("providers") + 1:]
            if after and after[0] != provider:
                errors.append(f"{label}: cross-provider import {module!r}")
        elif level >= 2 and segments and segments[0] in siblings:
            errors.append(f"{label}: cross-provider import of sibling {segments[0]!r}")

    scope_errors = _check_scope_literals(path, tree, provider, label)
    errors.extend(scope_errors)
    return errors


def _check_scope_literals(path: Path, tree: ast.AST, provider: str,
                          label: str) -> list[str]:
    errors = []
    env: dict[str, set[str]] = {}
    for name, node in _assignments(tree):
        literal = _literal_str_elements(node.value, env)
        if literal is not None:
            env[name] = literal
    for name, node in _assignments(tree):
        if not _SCOPES_NAME_RE.search(name):
            continue
        pin = PROVIDER_SCOPE_PINS.get((provider, path.name, name))
        if pin is None:
            errors.append(
                f"{label}: scope literal {name!r} has no registered pin in "
                f"check_mail_safety.PROVIDER_SCOPE_PINS"
            )
            continue
        literal = _literal_str_elements(node.value, env)
        if literal != pin:
            errors.append(
                f"{label}: pinned scope literal {name!r} changed: {sorted(literal or [])}"
            )
    return errors


def _probe_route_policy(providers_root: Path, provider: str) -> list[str]:
    """Import ``<pkg>.providers.<provider>.route_policy`` and execute its probes."""
    policy_file = providers_root / provider / "route_policy.py"
    label = f"{provider}/route_policy.py"
    if not policy_file.is_file():
        return [f"{provider}: missing route_policy.py (every provider ships one)"]
    package_root = providers_root.parent          # the mail package dir
    search_root = package_root.parent             # dir that makes it importable
    inserted = str(search_root) not in sys.path
    if inserted:
        sys.path.insert(0, str(search_root))
    try:
        module = importlib.import_module(
            f"{package_root.name}.providers.{provider}.route_policy"
        )
    except Exception as exc:
        return [f"{label}: cannot import for probing: {exc}"]
    finally:
        if inserted:
            sys.path.remove(str(search_root))

    policies = [
        obj for obj in vars(module).values()
        if isinstance(obj, type)
        and callable(getattr(obj, "assert_allowed", None))
        and getattr(obj, PROBES_NAME, None)
        and obj.__module__ == module.__name__
    ]
    if not policies:
        return [f"{label}: no route-policy class with a non-empty {PROBES_NAME}"]
    errors = []
    for policy in policies:
        for method, url in getattr(policy, PROBES_NAME):
            try:
                policy.assert_allowed(method, url)
            except Exception:
                continue  # denied — good
            errors.append(
                f"{label}: {policy.__name__} ALLOWED send/mutation endpoint "
                f"{method} {url}"
            )
    return errors


def check_providers_tree(providers_root: Path | None = None) -> list[str]:
    root = (providers_root or DEFAULT_PROVIDERS_ROOT).resolve()
    if not root.is_dir():
        return [f"providers root missing: {root}"]
    providers = sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )
    errors: list[str] = []
    for provider in providers:
        siblings = set(providers) - {provider}
        for path in _python_files(root / provider):
            label = f"{provider}/{path.relative_to(root / provider).as_posix()}"
            errors.extend(_check_provider_file(path, provider, siblings, label))
        errors.extend(_probe_route_policy(root, provider))
    return errors


def check_consumer_dir(scripts_dir: Path) -> list[str]:
    scripts_dir = scripts_dir.resolve()
    if not scripts_dir.is_dir():
        return [f"consumer scripts dir missing: {scripts_dir}"]
    errors: list[str] = []
    for path in _python_files(scripts_dir):
        relative = path.relative_to(scripts_dir).parts
        if "_vendor" in relative or "tests" in relative:
            continue  # _vendor is drift-gated against canonical; tests hold probe URLs
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            errors.append(f"{path.name}: does not parse: {exc}")
            continue
        errors.extend(_scan_patterns(path, source, tree, path.name))
        pin = CONSUMER_CLI_PINS.get(path.name)
        if pin is not None:
            env: dict[str, set[str]] = {}
            commands = None
            for name, node in _assignments(tree):
                literal = _literal_str_elements(node.value, env)
                if literal is not None:
                    env[name] = literal
                if name == "CLI_COMMANDS":
                    commands = literal
            if commands != pin:
                errors.append(
                    f"{path.name}: CLI command surface changed: {sorted(commands or [])}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    # ast end_lineno (probe-span exemption) needs Python 3.8+; fail loudly.
    if sys.version_info < (3, 8):
        got = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(
            f"check_mail_safety.py requires Python 3.8+; got {got} at "
            f"{sys.executable}. Run it with the repo venv (.venv/bin/python).",
            file=sys.stderr,
        )
        return 2
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--providers-root", type=Path, default=None,
        help="providers tree to walk (default: the sibling providers/ folder)",
    )
    parser.add_argument(
        "--consumer", type=Path, action="append", default=[],
        help="consumer skill scripts dir to scan (repeatable)",
    )
    args = parser.parse_args(argv)
    errors = check_providers_tree(args.providers_root)
    for consumer in args.consumer:
        errors.extend(check_consumer_dir(consumer))
    if errors:
        for error in errors:
            print(f"MAIL SAFETY FAIL: {error}", file=sys.stderr)
        return 1
    print("mail safety policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
