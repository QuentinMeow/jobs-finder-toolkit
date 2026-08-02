"""Publish-time leak guard: verify a checkout is safe to publish PUBLICLY.

This is the PUBLIC toolkit repo; personal data lives in a separate PRIVATE
overlay repo mounted at the git-ignored ``private/`` path, so the TRACKED
tree must always be publishable.
This script gates that invariant: it runs in CI (blocking), in the pre-push
hook, and by hand — zero findings is the steady state; ANY finding is a
regression.

It scans a set of files (TRACKED git files by default, or every file under a plain
directory tree — see ``scan()``) and FAILS (exit 1) if any of these appear,
printing a clear report of every violation; otherwise it exits 0 with an "OK"
message:

  1. Private skill leak. A skill whose ``skills/<skill>/SKILL.md``
     frontmatter declares ``visibility: private`` MUST have zero tracked files.
  2. Personal overlay leak. Any tracked path under the private overlay prefix
     (``private/``) must never ship.
  3. Per-skill private-notes leak. Any tracked file under a per-skill notes folder
     — ``skill-notes/`` (current) or ``references_private/`` (its former name) —
     which holds candidate-specific skill content.
  4. Path/filename denylist (defense in depth). Any tracked path under a private
     product tree (``applications/``, ``interviews/``, ``.agents/inputs/``), any
     non-markdown, non-example file under ``templates/`` (root templates/ =
     tracked process schemas), any ``meta.yaml`` outside ``examples/``, or any
     ``.docx`` / ``.pdf`` outside ``examples/``. This catches private trees even
     when zero identity tokens are active.
  5. Structural PII (independent of the token list). Raw emails, US phone shapes,
     absolute home paths (``/Users/<name>``, ``/home/<name>``), and
     ``linkedin.com/in/<handle>`` handles are flagged even with 0 tokens. A small
     allowlist keeps the fictional example identity ("Jordan Rivers",
     ``example.com`` addresses) green; real-domain emails still flag.
  6. Personal-identity token leak. Any file whose PATH or CONTENT contains a
     personal-identity token. Tokens are NOT hardcoded here; they are resolved at
     runtime by ``personal_tokens()`` (env var + git-ignored config identity +
     ``private/leak_tokens.txt``) so this shipped guard carries zero real
     identity.
  7. Unscannable binaries (fail closed). Document binaries (``.docx``/``.pdf``/...)
     AND images (``.png``/``.jpg``/...) that cannot be text-extracted count as
     FAILURES (they might hide a real name/resume/screenshot). A narrow explicit
     allowlist (``BINARY_ALLOWLIST`` + the ``examples/`` placeholder dataset)
     covers intentionally-shipped binaries.
  8. Unreadable tracked files (fail closed). A tracked path the guard could not
     OPEN at all — a dangling symlink, a permission error, an I/O error — is a
     FAILURE: its bytes ship and the guard inspected none of them. The line is
     OPENABILITY, not extractability. A file that opened but holds no scannable
     text (a raw binary blob, a non-UTF-8 file, an image with no extractor) is
     counted in the report's ``content read: N of M`` line but is never fatal
     (rationale: the "inspection accounting" comment above ``_probe_open``).

This guard is designed to go GREEN on a properly genericized public checkout. Run
it in a maintainer checkout (where ``config.yaml`` supplies the real tokens)
before publishing, and the exporter (``export_public.py``) runs it against the
freshly copied tree as the final gate.

FAIL CLOSED WHEN UNARMED. Check 6 is only meaningful when the guard actually
knows the owner's identity, so the identity-derived token set is tracked
SEPARATELY from the supplementary one (``private/leak_tokens.txt``) and an empty
identity set is a hard error (exit 2) BEFORE any scanning — otherwise a tree full
of the owner's real name reports "Safe to publish". Only the two channels that
carry a real identity arm the guard:
  * a REAL (non-example) ``config.yaml`` discovered by ``automation/shared/config.py``;
  * the ``JOBHUNT_PERSONAL_TOKENS`` env var (how the exporter/CI forward it).
``private/leak_tokens.txt`` is supplementary: it adds tokens but can NEVER arm the
guard on its own (it holds employers/schools, not the name/email/handles). Pass
``--allow-unarmed`` to run the token-independent checks (1-5, 7-8) knowingly — the
pre-commit hook does exactly that, while the pre-push hook does NOT.

Exit codes: 0 clean · 1 violations found · 2 unarmed (no identity tokens).

Usage:
    .venv/bin/python automation/publish/check_public.py
    .venv/bin/python automation/publish/check_public.py --json
    .venv/bin/python automation/publish/check_public.py --staged [--allow-unarmed]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# The sibling manifest module owns the ONE SKILL.md frontmatter parser in the
# repo (the exporter and the reconciler read the same one), so the guard's
# ``visibility: private`` detection can never disagree with what actually ships.
# Both files live in ``automation/publish/`` and are always exported together.
_PUBLISH_DIR = str(Path(__file__).resolve().parent)
if _PUBLISH_DIR not in sys.path:
    sys.path.insert(0, _PUBLISH_DIR)
import sync_skill_manifests  # noqa: E402

# automation/publish/check_public.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# This guard's own path (relative to the repo root). Its CONTENT is exempt from the
# token/structural-PII scans because it deliberately embeds the detection regexes
# and example patterns (e.g. ``/Users/alex/...``, ``linkedin.com/in/...``); its
# PATH is still screened. The file carries no real identity, so it is safe to
# publish verbatim.
GUARD_REL_PATH = "automation/publish/check_public.py"

# Personal-identity tokens are NEVER hardcoded in this shipped file. They are
# derived at runtime by ``personal_tokens()`` from:
#   1. the ``JOBHUNT_PERSONAL_TOKENS`` env var (comma/newline separated) — used by
#      the exporter to forward the REAL token set into a freshly exported checkout
#      that has no config.yaml of its own;
#   2. the git-ignored ``config.yaml`` candidate identity (name parts, email,
#      linkedin/github handles) — ONLY when a real config is active, so the
#      fictional "Jordan Rivers" example never contributes tokens;
#   3. an optional git-ignored leak-token file (one token per line) for identity
#      attributes that do not live in config.yaml (school, GPA, employer/product
#      names, prior employers, extra handles).
# The shipped default below is EMPTY, so the public copy of this guard carries
# zero real identity while remaining a fully functional screen when tokens are
# supplied by the maintainer's environment/overlay.
PERSONAL_TOKENS: list[str] = []

# Optional git-ignored file of extra personal tokens (one per line; blank lines
# and ``#`` comments ignored). It lives under the overlay prefix so it is never
# tracked/shipped.
LEAK_TOKENS_FILES = [
    REPO_ROOT / "private" / "leak_tokens.txt",
]

# Env var the exporter uses to forward the resolved real token set into the guard
# run against a freshly copied (config-less) export tree.
TOKENS_ENV_VAR = "JOBHUNT_PERSONAL_TOKENS"

# The private overlay prefix that must never be tracked in the public repo.
PERSONAL_OVERLAY_PREFIXES = ("private/",)

# Where skills live, relative to the repo root.
SKILLS_DIR = "skills"

# Per-skill folder that holds candidate-specific ("private") skill content. It is
# git-ignored and must never be tracked/shipped; any tracked file under it is a
# leak. (The sibling ``references_public/`` folder IS public and ships.)
#
# APPEND-ONLY UNION, for the same reason as ``_DENY_TREES`` below. Workspace phase 5
# renamed ``references_private/`` to ``skill-notes/`` and moved it into the overlay;
# keying on the old name alone left this check enforcing nothing at its stated
# purpose. The old name stays denied: a stale checkout, an old branch or a restored
# backup can still put it in the public tree. Matching is per PATH SEGMENT, so a file
# whose name merely ends in ``-skill-notes`` is not hit.
SKILL_NOTES_DIRNAMES = ("references_private", "skill-notes")
_SKILL_NOTES_RE = re.compile(
    r"(^|/)(" + "|".join(re.escape(n) for n in SKILL_NOTES_DIRNAMES) + r")(/|$)")

# The genericized, publicly-shippable example dataset. Files under it carry the
# fictional "Jordan Rivers" persona by design and are the ONLY place a tracked
# ``meta.yaml`` / ``.docx`` / ``.pdf`` is tolerated.
EXAMPLES_PREFIX = "examples/"


# ── path/filename denylist (defense in depth, token-independent) ──────────────
# Root-anchored private product trees that must never appear in a public tree.
# Anchored (``^``) so the tracked ``examples/applications/**`` dataset is NOT hit
# (``examples/me/``, ``examples/companies/``, ``examples/store/`` likewise).
#
# APPEND-ONLY UNION — entries are NEVER removed, only added.
# A rename does not retire the old name: a stale checkout, an old branch, a
# restored backup, or a half-finished migration can still put the historical tree
# at the public root, and a detector that forgot the old name is a detector that
# fails open exactly when it matters. So this list carries the HISTORICAL names,
# the CURRENT ones, and the names a planned rename will introduce
# (docs/designs/workspace-restructure/): ``data/``->``store/``,
# ``interviews/``->``me/interviews/`` + ``companies/``,
# ``job-search-profiles/``->``market/searches/``.
# Only add a root that must never be public: ``docs/``, ``memory/``, ``tasks/``,
# ``message-queue/``, ``evals/``, ``skills/`` and ``examples/`` are legitimate
# PUBLIC roots and must stay off this list.
# ``private/`` is deliberately absent: it is reported by
# ``find_personal_overlay_violations`` (check 2) so its findings stay one category.
_DENY_TREES = [
    # current / historical private product trees
    (re.compile(r"^applications/"), "applications/"),
    (re.compile(r"^interviews/"), "interviews/"),
    (re.compile(r"^\.agents/inputs/"), ".agents/inputs/"),
    (re.compile(r"^data/"), "data/"),
    (re.compile(r"^job-search-profiles/"), "job-search-profiles/"),
    # Local metrics output (automation/metrics/hook_collect.py writes
    # REPO_ROOT/logs/metrics.jsonl, which summarizes session transcripts). It is
    # opt-in and local-only, so nothing tracked ever lives here — but it is
    # session telemetry about a real person's work and must never be published.
    # Added when `.gitignore` anchored the rule to `/logs/`; the `^` keeps the
    # tracked `examples/market/logs/**` fixture out of scope.
    (re.compile(r"^logs/"), "logs/"),
    # names the planned private-tree renames introduce (denied before they exist)
    (re.compile(r"^store/"), "store/"),
    (re.compile(r"^me/"), "me/"),
    (re.compile(r"^companies/"), "companies/"),
    (re.compile(r"^market/"), "market/"),
    # Local opt-in metrics output (automation/metrics/hook_collect.py writes
    # logs/metrics.jsonl). Denied rather than exempted via the test's
    # NON_PRODUCT_ROOTS: today the payload is counters and ids — timestamps,
    # session_id, model, git_sha, tool names, token sums, line counts — and
    # carries no prompt text or file path, so it is not personal data as
    # written. It is denied because the schema is explicitly version-brittle
    # and grows with Claude Code releases; an exemption would publish a future
    # field that carries a path, whereas a deny only ever inconveniences
    # somebody deliberately tracking a root logs/ tree, which nothing wants.
    (re.compile(r"^logs/"), "logs/"),
]


def find_path_denylist_violations(tracked: list[str]) -> list[dict]:
    """Flag tracked paths that a public tree must never carry.

    ``private/`` overlay paths are reported by
    ``find_personal_overlay_violations`` and are intentionally not repeated here.
    """
    violations: list[dict] = []
    for rel in tracked:
        reason = None
        for rx, label in _DENY_TREES:
            if rx.match(rel):
                reason = f"private-tree:{label}"
                break
        if reason is None and rel.startswith("templates/"):
            # Root ``templates/`` holds the tracked process-file SCHEMAS
            # (markdown only; retired the pre-2026-07-22 in-place products
            # meaning). Markdown ships; anything else here — above all a
            # resume/reference document binary — is a leak candidate. An
            # example-named asset stays allowed for continuity.
            if Path(rel).suffix.lower() != ".md" and ".example." not in Path(rel).name:
                reason = "templates-nonschema"
        elif reason is None:
            name = Path(rel).name
            suffix = Path(rel).suffix.lower()
            if name == "meta.yaml" and not rel.startswith(EXAMPLES_PREFIX):
                reason = "meta.yaml-outside-examples"
            elif suffix in (".docx", ".pdf") and not rel.startswith(EXAMPLES_PREFIX):
                reason = f"binary-outside-examples:{suffix}"
        if reason is not None:
            violations.append({"category": "path_denylist", "path": rel, "reason": reason})
    return violations


# ── structural PII (independent of the token list) ───────────────────────────
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# US phone: optional +1, area code (parenthesized or bare) then 3 then 4 digits.
# A separator (space / dot / hyphen) is REQUIRED between the exchange and the last
# four (and after a bare area code) so bare digit runs — IDs, timestamps — do not
# trip. Non-digit lookaround keeps it from matching inside a longer number.
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[ .\-]?)?(?:\(\d{3}\)[ .\-]?|\d{3}[ .\-])\d{3}[ .\-]\d{4}(?!\d)"
)
HOME_PATH_RE = re.compile(r"/(Users|home)/([A-Za-z0-9][A-Za-z0-9._\-]*)")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9_\-]+)", re.IGNORECASE)

# Reserved / placeholder identities that keep the fictional example dataset green.
# NOTE: only PERSON-NAME placeholders live here — functional ATS local-parts
# (careers@, recruiting@, jobs@) are deliberately absent so a real-domain company
# address still flags (it reveals a targeted employer).
_PLACEHOLDER_EMAIL_LOCALPARTS = frozenset({
    "jane", "john", "jane.doe", "john.doe", "jane.smith", "john.smith",
    "jdoe", "jsmith", "jordan", "jordan.rivers", "you", "your.name", "name",
    "user", "username", "example", "first.last", "firstname.lastname", "alex",
    "test", "noreply", "git",
})
_PLACEHOLDER_LINKEDIN_HANDLES = frozenset({
    "jordanrivers", "yourhandle", "your-handle", "username", "handle", "name",
    "you", "in",
})
_PLACEHOLDER_HOME_USERS = frozenset({
    "you", "user", "username", "name", "me", "yourname", "your-name", "home",
    "someone", "alex", "jordan", "jordanrivers", "mac", "admin", "runner",
})


def _domain_is_example(domain: str) -> bool:
    domain = domain.lower().rstrip(".")
    for d in ("example.com", "example.org", "example.net"):
        if domain == d or domain.endswith("." + d):
            return True
    for tld in ("example", "invalid", "test", "localhost"):
        if domain == tld or domain.endswith("." + tld):
            return True
    return False


def _email_allowed(match: re.Match, text: str) -> bool:
    """True if an email match is a placeholder / not really a contact address."""
    end = match.end()
    # SCP-style git URL (``git@github.com:owner/repo``) — a remote, not a contact.
    if end < len(text) and text[end] == ":":
        return True
    email = match.group(0)
    local, _, domain = email.partition("@")
    if _domain_is_example(domain):
        return True
    if local.lower() in _PLACEHOLDER_EMAIL_LOCALPARTS:
        return True
    return False


def _phone_allowed(match: re.Match) -> bool:
    """True for fictional numbers (555 area code / exchange) or non-10-digit runs."""
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) != 10:
        return True
    area, exchange = digits[0:3], digits[3:6]
    return exchange == "555" or area == "555"


def _home_allowed(match: re.Match) -> bool:
    return match.group(2).lower() in _PLACEHOLDER_HOME_USERS


def _linkedin_allowed(match: re.Match) -> bool:
    return match.group(1).lower() in _PLACEHOLDER_LINKEDIN_HANDLES


def _structural_hits(text: str) -> list[tuple[str, str]]:
    """Return ``(kind, matched-text)`` structural-PII hits in ``text``."""
    hits: list[tuple[str, str]] = []
    for m in EMAIL_RE.finditer(text):
        if not _email_allowed(m, text):
            hits.append(("email", m.group(0)))
    for m in PHONE_RE.finditer(text):
        if not _phone_allowed(m):
            hits.append(("phone", m.group(0)))
    for m in HOME_PATH_RE.finditer(text):
        if not _home_allowed(m):
            hits.append(("home_path", m.group(0)))
    for m in LINKEDIN_RE.finditer(text):
        if not _linkedin_allowed(m):
            hits.append(("linkedin", m.group(1)))
    return hits


# ── binary handling / fail-closed set ────────────────────────────────────────
# Extensions never scanned for token CONTENT via substring (still checked by PATH
# and, for extractable documents, by their extracted text). Binary or document
# formats where a raw substring scan is meaningless or destructive.
BINARY_EXTENSIONS = frozenset({
    ".docx", ".doc", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".ico", ".svgz", ".zip", ".gz", ".tar", ".tgz", ".xz", ".7z", ".rar",
    ".xlsx", ".xls", ".pptx", ".ppt", ".pyc", ".pyo", ".so", ".dylib", ".dll",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi",
    ".wav",
})

# Binaries that MUST be scannable — if we cannot extract their text we FAIL CLOSED
# (they could hide a real name/resume/screenshot). Covers office documents AND
# raster images (images are never content-scannable, so an unscannable image is a
# hard failure unless explicitly allowlisted).
FAIL_CLOSED_EXTENSIONS = frozenset({
    ".docx", ".doc", ".pdf", ".xlsx", ".pptx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
})

# Narrow, explicit allowlist of intentionally-shipped binaries that are exempt
# from the fail-closed check even if unextractable. The fictional ``examples/``
# dataset (the "Jordan Rivers" placeholder resume/cover binaries) ships publicly
# by design; the private product trees that hold real binaries are path-denied
# above, so exempting the example dataset here cannot mask a real leak.
#
# The one entry below is REDUNDANT today: ``_binary_allowed`` already exempts
# everything under ``examples/``, so the set only matters for a binary that ships
# from somewhere else. It is kept — repointed, not dropped, when the reference
# DOCX moved to ``me/resume/`` — because it is the worked example of the escape
# hatch's shape; an empty frozenset reads like an unused mechanism and invites
# deleting the hatch itself. Being unreachable is also why it went stale unnoticed,
# so anything added here needs a test, not just a line.
BINARY_ALLOWLIST = frozenset({
    "examples/me/resume/reference.example.docx",
})


def _binary_allowed(rel: str) -> bool:
    """True if ``rel`` is an intentionally-shipped binary (fail-closed exempt)."""
    return rel in BINARY_ALLOWLIST or rel.startswith(EXAMPLES_PREFIX)


def _load_shared_config():
    """Import the shared config loader (automation/shared/config.py), or None.

    Repo-root tooling may import ``automation/shared`` directly (see AGENTS.md). The
    guard uses it only to DERIVE tokens; a failure to import simply yields no
    identity tokens (the env var / overlay file still apply).
    """
    shared = REPO_ROOT / "automation" / "shared"
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    try:
        import config  # type: ignore  # noqa: E402
        return config
    except Exception:
        return None


def config_identity_status() -> str:
    """One line describing which config (if any) supplied identity tokens.

    NEVER raises. The config layer refuses to resolve when no real ``config.yaml``
    is reachable while a private overlay is mounted; a traceback out of this guard
    (it runs in pre-push / pre-commit) would be a strictly worse failure than a
    report that says the scan resolved no identity. The refusal is surfaced in the
    report instead, so an unarmed run is never mistaken for a clean one.
    """
    config = _load_shared_config()
    if config is None:
        return "config loader unavailable — no identity resolved from config"
    try:
        active = Path(config.config_path())
    except Exception as exc:  # noqa: BLE001 — report, never crash
        return (f"config unresolved ({type(exc).__name__}: {exc}) — "
                f"no identity resolved from config")
    try:
        is_example = active.resolve() == Path(config.EXAMPLE_CONFIG).resolve()
    except Exception:  # noqa: BLE001
        is_example = False
    if is_example:
        return f"fictional example config ({active}) — no identity resolved from config"
    return f"real config ({active})"


def _identity_tokens(config) -> set[str]:
    """Derive identity tokens from the ACTIVE config — only if it is a real one.

    When the discovered config is the tracked ``config.example.yaml`` fallback
    (the fictional "Jordan Rivers" persona), this returns an empty set so the
    example identity is never treated as a leak.
    """
    toks: set[str] = set()
    try:
        active = config.config_path().resolve()
        example = config.EXAMPLE_CONFIG.resolve()
    except Exception:
        return toks
    if active == example:
        return toks

    name = config.candidate_name()
    for part in re.split(r"[^A-Za-z0-9']+", name or ""):
        part = part.strip("'")
        if len(part) >= 3:
            toks.add(part)

    contact = config.contact_line() or ""
    for email in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", contact):
        toks.add(email)
        local = email.split("@", 1)[0]
        if len(local) >= 3:
            toks.add(local)
    for handle in re.findall(r"(?:linkedin\.com/in/|github\.com/)([A-Za-z0-9\-_]+)", contact):
        if len(handle) >= 3:
            toks.add(handle)

    # The machine home-directory basename (e.g. ``alex``) catches leaked absolute
    # paths like ``/Users/alex/...``. Only added alongside a real config, so CI /
    # example runs (which use the fictional fallback) never pick up a CI home name.
    home = Path.home().name
    if len(home) >= 3:
        toks.add(home)
    return toks


def _tokens_from_file(path: Path) -> set[str]:
    toks: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return toks
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            toks.add(line)
    return toks


def _overlay_skill_name_tokens(root: Path = REPO_ROOT) -> set[str]:
    """Exact overlay-only skill names, derived locally and never hardcoded.

    A private skill is a direct child of ``private/skills/`` that owns a
    ``SKILL.md``. Adding or renaming one therefore arms the local content/path
    scan for that name automatically, while the public copy of this guard never
    carries the name itself.
    """
    skills = Path(root) / "private" / "skills"
    if not skills.is_dir():
        return set()
    return {
        child.name
        for child in skills.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    }


def _env_tokens() -> set[str]:
    """Tokens forwarded through ``JOBHUNT_PERSONAL_TOKENS``.

    Same comment/blank handling as the leak-token files, so the env var can be
    populated verbatim from private/leak_tokens.txt (e.g. as a CI secret).
    Comment LINES are dropped before comma-splitting, so a comma inside a comment
    can never shed token fragments.
    """
    toks: set[str] = set()
    for line in os.environ.get(TOKENS_ENV_VAR, "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for raw in line.split(","):
            raw = raw.strip()
            if raw:
                toks.add(raw)
    return toks


def identity_tokens() -> set[str]:
    """The ARMING token set: tokens that prove the guard knows the real identity.

    Exactly two channels qualify — a REAL (non-example) ``config.yaml`` and the
    ``JOBHUNT_PERSONAL_TOKENS`` env var the exporter/CI use to forward that same
    identity into a config-less tree. When this set is EMPTY the token scan
    (check 6) is inert and the guard must refuse to run (see ``main``).
    """
    toks = _env_tokens()
    config = _load_shared_config()
    if config is not None:
        toks |= _identity_tokens(config)
    return toks


def supplementary_tokens() -> set[str]:
    """Extra tokens that widen the scan but can NEVER arm it.

    ``private/leak_tokens.txt`` holds identity ATTRIBUTES (employers, school,
    product names), and mounted overlay skill directory names protect the
    repository structure itself. Neither source proves that the candidate's
    name/email/handles are known. Gating on the union of this set and
    ``identity_tokens()`` is exactly the fail-open bug this split exists to
    prevent.
    """
    toks: set[str] = set(PERSONAL_TOKENS)
    for leak_file in LEAK_TOKENS_FILES:
        toks |= _tokens_from_file(leak_file)
    toks |= _overlay_skill_name_tokens()
    return toks


def personal_tokens() -> list[str]:
    """The full active token set: ``identity_tokens() | supplementary_tokens()``."""
    return sorted(identity_tokens() | supplementary_tokens())


def unarmed_report() -> list[str]:
    """Diagnostic lines naming WHICH config was looked for, WHERE, and what was found.

    Printed when the guard refuses to run unarmed, so the operator can tell a
    missing overlay from a wrong cwd from an unset CI secret.
    """
    lines: list[str] = []
    config = _load_shared_config()
    if config is None:
        lines.append("  config loader:  FAILED to import automation/shared/config.py "
                     "(no identity could be derived)")
    else:
        env_name = getattr(config, "ENV_VAR", "JOBHUNT_CONFIG")
        env_val = os.environ.get(env_name) or "unset"
        filename = getattr(config, "CONFIG_FILENAME", "config.yaml")
        shared_dir = REPO_ROOT / "automation" / "shared"
        lines.append(f"  looked for:     '{filename}' via ${env_name} ({env_val}), then "
                     f"upward from {Path.cwd()}, then upward from {shared_dir}")
        try:
            active = Path(config.config_path()).resolve()
            example = Path(config.EXAMPLE_CONFIG).resolve()
        except Exception:
            active = example = None
        if active is None:
            lines.append("  active config:  <could not be resolved>")
        elif active == example:
            lines.append(f"  active config:  {active}")
            lines.append("                  ^ the TRACKED example fallback — the fictional "
                         "persona contributes zero tokens by design")
        else:
            lines.append(f"  active config:  {active} (no identity fields resolved from it)")
    lines.append(f"  ${TOKENS_ENV_VAR}: "
                 f"{'set but empty' if TOKENS_ENV_VAR in os.environ else 'unset'}")
    supplementary = supplementary_tokens()
    for leak_file in LEAK_TOKENS_FILES:
        state = "present" if leak_file.exists() else "absent"
        lines.append(f"  {leak_file}: {state} "
                     f"({len(supplementary)} supplementary token(s) — cannot arm the guard)")
    return lines


def _list_files(root: Path) -> list[str]:
    """Return files under ``root`` (repo-root-relative, forward slashes).

    Uses ``git ls-files`` when ``root`` is a git work tree (``.git`` present) so
    the CLI keeps its "tracked files only" semantics; otherwise walks the plain
    directory tree (used by the fixture tests and any non-git export scratch).
    """
    root = Path(root)
    if (root / ".git").exists():
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return [line for line in out.splitlines() if line]
    files: list[str] = []
    for dirpath, dirs, fnames in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fname in fnames:
            files.append((Path(dirpath) / fname).relative_to(root).as_posix())
    return sorted(files)


def git_tracked_files() -> list[str]:
    """Return every tracked path (repo-root-relative, forward slashes)."""
    return _list_files(REPO_ROOT)


def parse_frontmatter_visibility(skill_md: Path) -> str | None:
    """Return the ``visibility`` value from a SKILL.md YAML frontmatter block.

    Reads only the block between the leading ``---`` fences. Returns the lowercased
    value (e.g. ``"private"``/``"public"``) or ``None`` when the key is absent or
    there is no frontmatter.

    Delegates to ``sync_skill_manifests`` so this guard, the exporter's public-skill
    list, ``.claude-plugin/marketplace.json`` and the runtime symlink trees are all
    derived by ONE parser — a second copy here could drift and let a skill declared
    private ship anyway.
    """
    return sync_skill_manifests.frontmatter_visibility(skill_md)


def find_private_skill_violations(root: Path, tracked: list[str]) -> list[dict]:
    """Private skills (visibility: private) must have NO tracked files."""
    violations: list[dict] = []
    skills_root = Path(root) / SKILLS_DIR
    if not skills_root.is_dir():
        return violations
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        if parse_frontmatter_visibility(skill_md) != "private":
            continue
        skill_dir = skill_md.parent
        rel = f"{SKILLS_DIR}/{skill_dir.name}"
        under = [p for p in tracked if p == rel or p.startswith(rel + "/")]
        if under:
            violations.append({
                "category": "private_skill_tracked",
                "skill": skill_dir.name,
                "path": rel,
                "tracked_files": under,
            })
    return violations


def find_personal_overlay_violations(tracked: list[str]) -> list[dict]:
    """Any tracked path under the private overlay prefix (``private/``)."""
    violations: list[dict] = []
    for p in tracked:
        for prefix in PERSONAL_OVERLAY_PREFIXES:
            if p == prefix.rstrip("/") or p.startswith(prefix):
                violations.append({"category": "personal_overlay", "path": p, "prefix": prefix})
                break
    return violations


def find_skill_notes_violations(tracked: list[str]) -> list[dict]:
    """Any tracked file under a per-skill private-notes folder is a leak.

    Both names in ``SKILL_NOTES_DIRNAMES`` count — the current ``skill-notes/`` and
    the retired ``references_private/``.
    """
    return [
        {"category": "skill_notes", "path": p}
        for p in tracked
        if _SKILL_NOTES_RE.search(p)
    ]


# ── inspection accounting (check 8) ──────────────────────────────────────────
# A publish gate must never certify bytes it did not look at, so every tracked
# path lands in EXACTLY ONE of three buckets and the summary prints the split:
#
#   read       the content was inspected — text lines, an extracted document, or
#              (for a symlink) the target path the link stores.
#   skipped    the guard OPENED it and there was legitimately no text to scan: a
#              raw binary blob, a non-UTF-8 file, an image or archive it has no
#              extractor for. Expected, counted, named — never fatal. Failing
#              here would fail on every ordinary binary in the tree, and a guard
#              that cries wolf on `examples/screenshots/*.jpg` is a guard someone
#              switches off.
#   unreadable the guard could not OPEN it: a dangling symlink, a permission
#              error, an I/O error. Git tracks the path, so the content ships,
#              and the guard knows NOTHING about it. That is a finding (check 8).
#
# The line between the last two is OPENABILITY, not extractability. A corrupt
# .docx WAS opened — it is check 7's business, and the tracked fixture
# ``examples/fixtures/resume-writer/empty-corrupt/corrupt-docx.docx`` exists on
# purpose. A broken symlink was never opened at all.
SKIP_GUARD_SELF = "guard-self"          # this file: content-exempt by design
SKIP_BINARY_SNIFF = "binary-sniff"      # NUL byte — a binary blob, no text
SKIP_NOT_UTF8 = "not-utf8"              # decoded as neither UTF-8 nor binary
SKIP_NO_EXTRACTOR = "no-text-extractor"  # image/archive: nothing to extract
SKIP_EXTRACT_FAILED = "extract-failed"  # extractor ran; container malformed/lib missing
UNREADABLE_BROKEN_SYMLINK = "broken-symlink"
UNREADABLE_OPEN_FAILED = "open-failed"


def _oserror_detail(exc: OSError) -> str:
    return f"{type(exc).__name__}: {exc.strerror or exc}"


def _probe_open(path: Path) -> str | None:
    """Return why ``path`` cannot be opened for reading, or None if it can.

    Used before handing a binary to an extractor, so "could not open it" is never
    mistaken for "opened it and found no text".
    """
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        return _oserror_detail(exc)
    return None


def _read_text_classified(path: Path) -> tuple[list[str] | None, str, str]:
    """Read ``path`` as UTF-8 lines AND say why, when that did not happen.

    Returns ``(lines, status, detail)``. ``status`` is ``"read"`` with the lines,
    or one of ``SKIP_BINARY_SNIFF`` / ``SKIP_NOT_UTF8`` (opened, no text to scan)
    or ``UNREADABLE_OPEN_FAILED`` (never opened — a check-8 finding).
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, UNREADABLE_OPEN_FAILED, _oserror_detail(exc)
    if b"\x00" in data:
        return None, SKIP_BINARY_SNIFF, ""
    try:
        return data.decode("utf-8").splitlines(), "read", ""
    except UnicodeDecodeError as exc:
        return None, SKIP_NOT_UTF8, f"undecodable byte at offset {exc.start}"


def _read_text(path: Path) -> list[str] | None:
    """Return the file's lines as text, or ``None`` if it looks binary/unreadable.

    Content-only wrapper for callers that just want the lines (the exporter's
    token screen). The guard's own scan uses ``_read_text_classified`` so a file
    it could never open becomes a finding instead of a silent skip.
    """
    return _read_text_classified(path)[0]


def _docx_text(path: Path) -> str | None:
    """Concatenate every XML part of a DOCX/zip-based Office file as text.

    Reading the raw parts (body + headers/footers + docProps metadata) needs only
    the stdlib and catches a real name hiding in document text OR in the author /
    lastModifiedBy metadata. Returns None if the file is not a readable zip.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            parts = []
            for name in zf.namelist():
                if name.endswith(".xml") or name.endswith(".rels"):
                    try:
                        parts.append(zf.read(name).decode("utf-8", "ignore"))
                    except KeyError:
                        continue
            return "\n".join(parts)
    except (zipfile.BadZipFile, OSError):
        return None


def _pdf_text(path: Path) -> str | None:
    """Extract PDF page text + metadata via PyMuPDF (fitz), else pypdf, else None."""
    try:
        import fitz  # type: ignore  # PyMuPDF
        doc = fitz.open(path)
        chunks = [page.get_text() for page in doc]
        chunks.extend(str(v) for v in (doc.metadata or {}).values() if v)
        return "\n".join(chunks)
    except Exception:
        pass
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        chunks = [(page.extract_text() or "") for page in reader.pages]
        meta = reader.metadata or {}
        chunks.extend(str(v) for v in meta.values() if v)
        return "\n".join(chunks)
    except Exception:
        return None


_EXTRACTABLE_SUFFIXES = frozenset({".docx", ".doc", ".xlsx", ".pptx", ".pdf"})


def _has_extractor(suffix: str) -> bool:
    """True if the guard even HAS a text extractor for ``suffix``.

    Separates "there is no extractor for a .png" from "the .docx extractor ran
    and the container was malformed" — different problems, different fixes.
    """
    return suffix in _EXTRACTABLE_SUFFIXES


def _binary_text(path: Path, suffix: str) -> str | None:
    """Best-effort text extraction for a shipped binary, or None if unscannable."""
    if suffix in (".docx", ".doc", ".xlsx", ".pptx"):
        return _docx_text(path)
    if suffix == ".pdf":
        return _pdf_text(path)
    return None


def _scan_blob(rel: str, blob: str, where: str, note: str,
               lowered: list[tuple[str, str]],
               token_viols: list[dict], pii_viols: list[dict]) -> None:
    """Scan one whole-file string for tokens (first hit) + structural PII (per kind)."""
    blob_lower = blob.lower()
    hit = next((tok for tok, low in lowered if low in blob_lower), None)
    if hit is not None:
        token_viols.append({
            "category": "personal_token",
            "where": where,
            "path": rel,
            "line": None,
            "token": hit,
            "text": note,
        })
    seen_kinds: set[str] = set()
    for kind, matched in _structural_hits(blob):
        if kind in seen_kinds:
            continue
        seen_kinds.add(kind)
        pii_viols.append({
            "category": "structural_pii",
            "kind": kind,
            "path": rel,
            "line": None,
            "match": matched,
        })


def find_token_and_pii_violations(
    root: Path, tracked: list[str], tokens: list[str]
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Scan file PATHs and CONTENT for personal tokens AND structural PII.

    Path token matches apply to every file. Text-file content is scanned line by
    line; document binaries have their extracted text + metadata scanned; a
    symlink's stored TARGET PATH is its content; images and other unextractable
    fail-closed binaries are reported for manual review. The guard file itself is
    content-exempt (it embeds the detection patterns).

    Returns ``(token_violations, structural_pii_violations, unscanned_binaries,
    inspection)``, where ``inspection`` accounts for every tracked path exactly
    once — ``files_read`` + ``files_skipped`` + ``unreadable`` — so a caller can
    tell "clean" from "inspected nothing" (see the INSPECTION notes above).
    """
    root = Path(root)
    lowered = [(tok, tok.lower()) for tok in tokens]
    token_viols: list[dict] = []
    pii_viols: list[dict] = []
    unscanned: list[dict] = []
    skipped: list[dict] = []
    unreadable: list[dict] = []
    files_read = 0

    for rel in tracked:
        rel_lower = rel.lower()
        path_tok = next((tok for tok, low in lowered if low in rel_lower), None)
        if path_tok is not None:
            token_viols.append({
                "category": "personal_token",
                "where": "path",
                "path": rel,
                "line": None,
                "token": path_tok,
                "text": rel,
            })

        if rel == GUARD_REL_PATH:
            skipped.append({"path": rel, "reason": SKIP_GUARD_SELF})
            continue

        src = root / rel
        # A tracked SYMLINK's own content is the TARGET PATH it stores — that is
        # the blob git ships, and it can name a private tree
        # (``.claude/skills/<x> -> ../../private/skills/<x>``). ``--staged``
        # already scans exactly that (see ``_materialize_index``); doing it here
        # keeps the two modes in agreement. A link to a DIRECTORY has nothing
        # further to read (its files are tracked in their own right); a link to a
        # file falls through so the file is scanned too; a link that resolves to
        # nothing is a check-8 finding — its bytes are gone, and a dangling link
        # in a published tree is broken output besides.
        if src.is_symlink():
            target = os.readlink(src)
            _scan_blob(rel, target, "symlink-target", f"-> {target}",
                       lowered, token_viols, pii_viols)
            if not src.exists():
                unreadable.append({"path": rel, "reason": UNREADABLE_BROKEN_SYMLINK,
                                   "detail": f"-> {target}"})
                continue
            if src.is_dir():
                files_read += 1
                continue

        suffix = Path(rel).suffix.lower()
        if suffix in BINARY_EXTENSIONS:
            open_error = _probe_open(src)
            if open_error is not None:
                unreadable.append({"path": rel, "reason": UNREADABLE_OPEN_FAILED,
                                   "detail": open_error})
                continue
            blob = _binary_text(src, suffix)
            if blob is None:
                # Opened fine, but yielded no text. Two different problems: there
                # is no extractor for this type at all (an image, an archive), or
                # the extractor ran and the container was malformed / its library
                # is missing. Either way fail closed for a fail-closed extension,
                # unless it is an intentionally-shipped example asset.
                reason = (SKIP_EXTRACT_FAILED if _has_extractor(suffix)
                          else SKIP_NO_EXTRACTOR)
                if suffix in FAIL_CLOSED_EXTENSIONS and not _binary_allowed(rel):
                    unscanned.append({"path": rel, "reason": reason})
                skipped.append({"path": rel, "reason": reason})
                continue
            files_read += 1
            _scan_blob(rel, blob, "binary-content", f"(inside {suffix} text/metadata)",
                       lowered, token_viols, pii_viols)
            continue

        lines, status, detail = _read_text_classified(src)
        if lines is None:
            if status == UNREADABLE_OPEN_FAILED:
                unreadable.append({"path": rel, "reason": status, "detail": detail})
            else:
                skipped.append({"path": rel, "reason": status})
            continue
        files_read += 1
        token_found = False
        seen_kinds: set[str] = set()
        for lineno, line in enumerate(lines, start=1):
            if not token_found:
                line_lower = line.lower()
                hit = next((tok for tok, low in lowered if low in line_lower), None)
                if hit is not None:
                    token_viols.append({
                        "category": "personal_token",
                        "where": "content",
                        "path": rel,
                        "line": lineno,
                        "token": hit,
                        "text": line.strip()[:200],
                    })
                    token_found = True
            for kind, matched in _structural_hits(line):
                if kind in seen_kinds:
                    continue
                seen_kinds.add(kind)
                pii_viols.append({
                    "category": "structural_pii",
                    "kind": kind,
                    "path": rel,
                    "line": lineno,
                    "match": matched,
                })
    inspection = {
        "files_read": files_read,
        "files_skipped": skipped,
        "unreadable": unreadable,
    }
    return token_viols, pii_viols, unscanned, inspection


def scan(root: Path = REPO_ROOT, tracked: list[str] | None = None,
         tokens: list[str] | None = None,
         visibility_root: Path | None = None) -> dict:
    """Run every check and return a structured result.

    ``root`` may be a git work tree (default: this repo) or any plain directory
    tree (used by the tests / an export scratch). ``tracked`` / ``tokens`` can be
    supplied to make a scan fully deterministic (the tests do this).
    ``visibility_root`` is where ``skills/*/SKILL.md`` frontmatter is READ from; it
    defaults to ``root`` and differs only in ``--staged`` mode, where the scanned
    tree holds just the staged blobs while the visibility declarations live in the
    work tree.

    NOTE: this function never gates on the token set being armed — it is pure
    detection, so a fixture scan can pass ``tokens=[]`` deliberately. The
    fail-closed arming gate lives in ``main()``.
    """
    root = Path(root).resolve()
    if tracked is None:
        tracked = _list_files(root)
    identity_count: int | None = None
    supplementary_count: int | None = None
    if tokens is None:
        identity = identity_tokens()
        supplementary = supplementary_tokens()
        identity_count = len(identity)
        supplementary_count = len(supplementary - identity)
        tokens = sorted(identity | supplementary)

    private_skill = find_private_skill_violations(
        Path(visibility_root).resolve() if visibility_root else root, tracked)
    overlay = find_personal_overlay_violations(tracked)
    skill_notes = find_skill_notes_violations(tracked)
    path_denylist = find_path_denylist_violations(tracked)
    token_viols, pii_viols, unscanned, inspection = find_token_and_pii_violations(
        root, tracked, tokens)
    unreadable = inspection["unreadable"]

    violations = {
        "private_skill_tracked": private_skill,
        "personal_overlay": overlay,
        "skill_notes": skill_notes,
        "path_denylist": path_denylist,
        "structural_pii": pii_viols,
        "personal_token": token_viols,
        "unscanned_binary": [
            {"category": "unscanned_binary", **item} for item in unscanned],
        "unreadable_file": [{"category": "unreadable_file", **item} for item in unreadable],
    }
    total = sum(len(v) for v in violations.values())
    return {
        "repo_root": str(root),
        "tracked_file_count": len(tracked),
        "personal_token_count": len(tokens),
        # None when the caller injected an explicit token list (fixture scans);
        # otherwise the identity/supplementary split, so an UNARMED run
        # (identity 0) is visible at a glance instead of hiding inside the union.
        "identity_token_count": identity_count,
        "supplementary_token_count": supplementary_count,
        # WHY the identity count is what it is: a real config, the fictional
        # example, or a config layer that refused/failed. Never raises.
        "config_status": config_identity_status(),
        # Paths only (the reasons live in ``violations['unscanned_binary']``) —
        # callers assert membership by path.
        "unscanned_binaries": [item["path"] for item in unscanned],
        # Inspection accounting: files_read + files_skipped + unreadable_files
        # == tracked_file_count, so "clean" is never confused with "nothing was
        # inspected" (check 8).
        "files_read": inspection["files_read"],
        "files_skipped": inspection["files_skipped"],
        "unreadable_files": unreadable,
        "ok": total == 0,
        "total_violations": total,
        "violations": violations,
    }


# ── staged-index mode (pre-commit) ───────────────────────────────────────────
# The empty tree, so the very first commit in a repo (no HEAD) still diffs.
_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(args: list[str], repo_root: Path, binary: bool = False):
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True,
        text=not binary,
    )


def staged_paths(repo_root: Path = REPO_ROOT) -> list[str]:
    """Paths staged for commit (added/copied/modified/renamed/type-changed).

    Deletions are excluded: their blobs are leaving the tree, and REMOVING a file
    that should never have been committed must stay possible.
    """
    try:
        _git(["rev-parse", "--verify", "--quiet", "HEAD"], repo_root)
        base = "HEAD"
    except subprocess.CalledProcessError:
        base = _EMPTY_TREE_SHA
    out = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT", base],
               repo_root).stdout
    return [p for p in out.split("\0") if p]


def _materialize_index(repo_root: Path, paths: list[str], dest: Path) -> None:
    """Write the INDEX content of ``paths`` under ``dest`` (never the worktree).

    Reading blobs out of the index is the whole point of ``--staged``: an unstaged
    edit must neither hide a leak that is being committed nor fail a commit that
    does not contain it. ``git checkout-index`` does it in one process and creates
    the leading directories itself.
    """
    subprocess.run(
        ["git", "checkout-index", f"--prefix={dest.as_posix()}/", "-z", "--stdin", "--force"],
        cwd=repo_root, check=True, capture_output=True,
        input="\0".join(paths).encode(),
    )
    # A symlink entry checks out as a symlink whose target may not exist here; its
    # blob content IS the target path, which is exactly what must be scanned (an
    # overlay symlink's target names private paths). Replace it with that text.
    for rel in paths:
        p = dest / rel
        if p.is_symlink():
            target = os.readlink(p)
            p.unlink()
            p.write_text(target + "\n", encoding="utf-8")


def scan_staged(repo_root: Path = REPO_ROOT, tokens: list[str] | None = None) -> dict:
    """Run the full guard over the STAGED INDEX content of a commit."""
    repo_root = Path(repo_root).resolve()
    paths = staged_paths(repo_root)
    if not paths:
        result = scan(root=repo_root, tracked=[], tokens=tokens)
        result["mode"] = "staged"
        return result
    with tempfile.TemporaryDirectory(prefix="leak-guard-staged-") as td:
        dest = Path(td)
        _materialize_index(repo_root, paths, dest)
        # Visibility (``visibility: private`` frontmatter) is read from the WORK
        # TREE: a commit that stages one file of a private skill without its
        # SKILL.md must still be caught.
        result = scan(root=dest, tracked=paths, tokens=tokens, visibility_root=repo_root)
    result["repo_root"] = f"{repo_root} (staged index)"
    result["mode"] = "staged"
    return result


def print_report(result: dict) -> None:
    """Print a human-readable report of the scan result."""
    v = result["violations"]

    private_skill = v["private_skill_tracked"]
    overlay = v["personal_overlay"]
    skill_notes = v["skill_notes"]
    path_denylist = v["path_denylist"]
    structural = v["structural_pii"]
    tokens = v["personal_token"]
    unscanned = result.get("unscanned_binaries") or []
    unreadable = result.get("unreadable_files") or []

    print("Public-repo leak guard")
    print(f"  repo root:      {result['repo_root']}")
    label = "staged files: " if result.get("mode") == "staged" else "tracked files:"
    print(f"  {label}  {result['tracked_file_count']}")
    # How much of that was actually looked at. Printed ALWAYS, clean or not: a
    # "Safe to publish" over zero inspected files must never read like a pass.
    if result.get("files_read") is not None:
        print(f"  content read:   {result['files_read']} of "
              f"{result['tracked_file_count']} file(s)")
        by_reason: dict[str, int] = {}
        for item in result.get("files_skipped") or []:
            by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
        if by_reason:
            summary = ", ".join(f"{k}: {n}" for k, n in sorted(by_reason.items()))
            print(f"  not inspected:  {sum(by_reason.values())} ({summary}) "
                  "— opened, no text to scan")
        if unreadable:
            print(f"  UNREADABLE:     {len(unreadable)} file(s) could not be opened "
                  "— see [8] below")
    identity = result.get("identity_token_count")
    supplementary = result.get("supplementary_token_count")
    if identity is None:
        print(f"  active tokens:  {result.get('personal_token_count', 0)} (caller-supplied)")
    else:
        armed = "" if identity else "   <-- UNARMED: the token scan cannot see the real identity"
        print(f"  identity tokens:      {identity}"
              f" (config.yaml / ${TOKENS_ENV_VAR}){armed}")
        print(f"  supplementary tokens: {supplementary}"
              f" ({'/'.join(f.name for f in LEAK_TOKENS_FILES)} + mounted "
              "overlay skill names; never arming)")
        print(f"  active tokens:        {result.get('personal_token_count', 0)} (union, deduped)")
    if result.get("config_status"):
        # Says WHY the identity count is what it is — a refused or failed config
        # layer reads identically to a clean unarmed run without this line.
        print(f"  identity source:      {result['config_status']}")
    print()

    if result["ok"]:
        print("OK: no public-repo leaks detected. Safe to publish.")
        return

    print(f"FAIL: {result['total_violations']} violation(s) found.\n")

    if private_skill:
        print(f"[1] Private skills with tracked files ({len(private_skill)}):")
        for item in private_skill:
            print(f"  - skill '{item['skill']}' ({item['path']}) has "
                  f"{len(item['tracked_files'])} tracked file(s):")
            for f in item["tracked_files"]:
                print(f"      {f}")
        print()

    if overlay:
        print(f"[2] Tracked paths under a private overlay prefix ({len(overlay)}):")
        for item in overlay:
            print(f"  - {item['path']}  [{item.get('prefix', '')}]")
        print()

    if skill_notes:
        names = " / ".join(f"'{n}/'" for n in SKILL_NOTES_DIRNAMES)
        print(f"[3] Tracked files under a per-skill private-notes folder "
              f"({names}) ({len(skill_notes)}):")
        for item in skill_notes:
            print(f"  - {item['path']}")
        print()

    if path_denylist:
        print(f"[4] Denylisted paths (private product trees / stray binaries) "
              f"({len(path_denylist)}):")
        for item in path_denylist:
            print(f"  - {item['path']}  [{item['reason']}]")
        print()

    if structural:
        by_kind: dict[str, int] = {}
        for item in structural:
            by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
        summary = ", ".join(f"{k}: {n}" for k, n in sorted(by_kind.items()))
        files_hit = {item["path"] for item in structural}
        print(f"[5] Structural PII hits (token-independent): {len(structural)} "
              f"({summary}) across {len(files_hit)} file(s):")
        for item in structural:
            loc = f":{item['line']}" if item.get("line") else ""
            print(f"  - {item['kind'].upper():9} {item['path']}{loc}  "
                  f"(match: {item['match']!r})")
        print()

    if tokens:
        path_hits = [t for t in tokens if t["where"] == "path"]
        content_hits = [t for t in tokens if t["where"] != "path"]
        files_hit = {t["path"] for t in tokens}
        print(f"[6] Personal-identity token hits: {len(tokens)} "
              f"({len(path_hits)} in paths, {len(content_hits)} in content) "
              f"across {len(files_hit)} file(s):")
        for item in tokens:
            if item["where"] == "path":
                print(f"  - PATH    {item['path']}  (token: {item['token']!r})")
            else:
                loc = f":{item['line']}" if item.get("line") else ""
                print(f"  - CONTENT {item['path']}{loc}  "
                      f"(token: {item['token']!r})  {item['text']!r}")
        print()

    if unscanned:
        print(f"[7] Unscannable binaries (fail closed — cannot verify contents) "
              f"({len(unscanned)}):")
        for item in v["unscanned_binary"]:
            why = f"  [{item['reason']}]" if item.get("reason") else ""
            print(f"  - {item['path']}{why}")
        print()

    if unreadable:
        print(f"[8] Unreadable tracked files (fail closed — the guard could not open "
              f"them, so NOTHING in them was inspected) ({len(unreadable)}):")
        for item in unreadable:
            detail = f"  ({item['detail']})" if item.get("detail") else ""
            print(f"  - {item['reason'].upper():15} {item['path']}{detail}")
        print("  Fix: repoint or remove the dangling link, restore read permission, "
              "or untrack the file.\n")


EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_UNARMED = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON results instead of the text report",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="scan the STAGED INDEX content of the pending commit instead of the "
             "tracked work tree (used by the pre-commit hook)",
    )
    parser.add_argument(
        "--allow-unarmed",
        action="store_true",
        help="run the token-independent checks even with ZERO identity tokens "
             "(default: refuse with exit 2, because the token scan is inert)",
    )
    args = parser.parse_args(argv)

    # ── fail closed when unarmed ────────────────────────────────────────────
    # Checked BEFORE scanning: a scan that cannot see the owner's identity must
    # never be able to print "Safe to publish", and failing fast keeps the
    # message the only thing on screen.
    identity = identity_tokens()
    if not identity:
        if not args.allow_unarmed:
            print("Public-repo leak guard")
            print("FAIL: the guard is UNARMED — zero identity tokens resolved, so the "
                  "personal-token\n      scan (check 6) would inspect nothing and report "
                  "'Safe to publish'.")
            for line in unarmed_report():
                print(line)
            print("\nArm it (any one of):")
            print("  * run in a maintainer checkout whose config.yaml carries the real "
                  "candidate identity;")
            print(f"  * export {TOKENS_ENV_VAR}='<token>[,<token>...]' (how the exporter "
                  "and CI forward it);")
            print("  * point $JOBHUNT_CONFIG at that config.yaml.")
            print("Or run the token-independent checks knowingly with --allow-unarmed.")
            return EXIT_UNARMED
        print("WARNING: leak guard is UNARMED (--allow-unarmed): zero identity tokens, "
              "so checks 1-5, 7\n         and 8 run but the personal-token scan "
              "(check 6) inspects nothing.", file=sys.stderr)

    result = scan_staged() if args.staged else scan()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_report(result)
    return EXIT_OK if result["ok"] else EXIT_VIOLATIONS


if __name__ == "__main__":
    raise SystemExit(main())
