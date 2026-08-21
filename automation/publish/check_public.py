"""Publish-time leak guard: verify a checkout is safe to publish PUBLICLY.

This is the PUBLIC toolkit repo; personal data lives in a separate PRIVATE
overlay repo mounted at the git-ignored ``private/`` path, so the TRACKED
tree must always be publishable.
This script gates that invariant: it runs in CI (blocking), in the pre-push
hook, and by hand — zero findings is the steady state; ANY finding is a
regression.

It scans a set of files (TRACKED git files by default, an immutable Git tree with
``--git-object``, or every file under a plain directory tree — see ``scan()``)
and FAILS (exit 1) if any of these appear, printing a clear report of every
violation; otherwise it exits 0 with an "OK" message:

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
  6. Personal-identity token leak. Any file whose PATH or CONTENT matches a
     personal-identity token. Tokens are NOT hardcoded here; they are resolved at
     runtime by ``personal_tokens()`` (env var + git-ignored config identity +
     ``private/leak_tokens.txt``) so this shipped guard carries zero real
     identity. Matching is HYBRID (see the ``TOKEN_BOUNDARY`` section): a bare
     word like a name part hits only at a word/identifier/case-hump EDGE, so an
     owner surnamed "King" is not flagged by ``making``; high-specificity tokens
     (email, handle, home basename, and the name COMPOUNDS derived alongside
     them — ``jordanrivers``, ``jrivers``, ``jordan-rivers``) keep plain
     containment, so a glued leak like ``linkedin.com/in/jordanrivers`` is still
     caught. Boundaries cannot help a name that IS an ordinary word ("Green",
     "Long", "Park"): that case has an opt-in, per-token allowance the OWNER
     declares in the git-ignored ``config.yaml`` as
     ``leak_guard.english_word_tokens`` (or ``$JOBHUNT_LEAK_GUARD_WORD_TOKENS``
     for CI / the exporter). It reaches BOUNDARY tokens only — the address, the
     handles, the home basename and the full-name compounds are never weakened
     by it — and every run afterwards prints what it skipped. The guard names
     this itself under check 6 whenever a boundary token is what blocked you.
  7. Unscannable binaries (fail closed). Document binaries (``.docx``/``.pdf``/...)
     AND images (``.png``/``.jpg``/...) that cannot be text-extracted count as
     FAILURES (they might hide a real name/resume/screenshot). A narrow explicit
     allowlist (``BINARY_ALLOWLIST`` + the ``examples/`` placeholder dataset)
     covers intentionally-shipped binaries.
  8. Unreadable tracked files (fail closed). A tracked path the guard could not
     OPEN at all — a dangling symlink, a permission error, an I/O error — is a
     FAILURE: its bytes ship and the guard inspected none of them. The line is
     OPENABILITY, not extractability. A file that opened but holds no scannable
     text (a raw binary blob, an image with no extractor) is counted in the
     report's ``content read: N of M`` line but is never fatal (rationale: the
     "inspection accounting" comment above ``_probe_open``). A text file that is
     not valid UTF-8 is NOT in that bucket — it is decoded by ``_decode_lossless``
     and scanned like any other, because a name in a latin-1 note is still a name.
  9. Unreadable personal-token source (fail closed). A token file that EXISTS but
     cannot be READ narrows check 6 silently — every employer/school/product token
     vanishes and the guard still certifies. That is a FAILURE. A token file that
     is simply ABSENT stays legitimate: the overlay may not be mounted.

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
    .venv/bin/python automation/publish/check_public.py --git-object <oid>
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
from typing import NamedTuple

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

# Optional git-ignored file of SAFE WORDS — strings that must NOT be treated as
# secrets even when an overlay skill folder is named that. Same format as the
# leak-token file (one per line, ``#`` comments and blanks ignored), and it lives
# under the same overlay prefix, for the same reason plus one more: a safe word
# names a private skill, so a TRACKED list of them would disclose exactly what
# ``_overlay_skill_name_tokens`` exists to hide. The MECHANISM ships; the values
# never do.
#
# Why this exists. ``_overlay_skill_name_tokens`` derives a token from every
# ``private/skills/<name>/`` folder, so creating a skill whose name is also an
# ordinary phrase retroactively turns pre-existing public prose into a leak
# report. That is a false positive of the classic filter kind: banning the word
# "grape" reddens every old post about fruit salad. The public tree here has used
# one such phrase since before the skill existed, and nothing about the old text
# discloses the new skill.
#
# Scope, deliberately narrow: safe words filter ONLY the auto-derived overlay
# skill-name tokens. They can never remove a token the maintainer DECLARED — the
# config identity, ``$JOBHUNT_PERSONAL_TOKENS``, or a ``leak_tokens.txt`` line.
# The line is inferred-vs-declared, not importance: a mechanism able to silently
# un-declare a declared secret is a disarming vector, and the guard has already
# had to close three of those. Undeclaring a declared token is done by editing
# the file that declares it, where the change is visible.
#
# There is no env-var channel and none is needed: the filter is applied where the
# set is BUILT, so anything ``personal_tokens()`` later forwards through
# ``$JOBHUNT_PERSONAL_TOKENS`` is already filtered.
SAFE_WORDS_FILES = [
    REPO_ROOT / "private" / "leak_safe_words.txt",
]

# Safe words and skill names are compared with separators unified, so a folder
# named ``field-notes`` is covered by the safe word ``field notes`` (or
# ``field_notes``). Matching is on the WHOLE name, never a substring: a safe word
# is permission to stop protecting one specific skill name, and substring
# semantics would let ``a`` exempt everything.
_SAFE_WORD_SEP_RE = re.compile(r"[\s_-]+")

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
# Anchored (``^``) so the tracked ``examples/me/applications/**`` dataset is NOT
# hit (``examples/me/``, ``examples/store/`` likewise).
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
    # The `^` anchor is what keeps the tracked examples/market/logs/** fixture
    # in scope for tracking while a root logs/ stays denied.
    (re.compile(r"^logs/"), "logs/"),
    # Harness agent worktrees: one FULL checkout of this repo per parallel
    # subagent. Denied rather than exempted because the content is a whole
    # second copy of the tree at whatever state that agent left it — including
    # a config.yaml, an unreviewed branch, or a half-finished edit — so a single
    # tracked file from here republishes an arbitrary snapshot the review gate
    # never saw. Nothing legitimate is ever tracked under it: work leaves a
    # worktree through a branch or a commit, never through this path.
    (re.compile(r"^\.claude/worktrees/"), ".claude/worktrees/"),
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
    "examples/me/career/resume/reference.example.docx",
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


def _same_file_content(a: Path, b: Path) -> bool:
    """True when two paths hold byte-identical content. Missing/unreadable -> False."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def is_example_config(active: Path, example: Path) -> bool:
    """Is the ACTIVE config the fictional example persona? Identity, not location.

    The old test was ``active.resolve() == example.resolve()``, which is only
    correct while both paths live in the same tree. The exporter breaks that
    assumption by construction: it runs this guard with ``cwd`` inside a freshly
    copied export, so ``EXAMPLE_CONFIG`` resolves to the EXPORT's copy while an
    inherited absolute ``$JOBHUNT_CONFIG`` still names the SOURCE checkout's file.
    Same file, two absolute paths, and the answer flipped to "real" — after which
    ``Jordan`` and ``Rivers`` became personal-identity tokens and a clean export
    failed on the toolkit's own documentation.

    So: the same resolved path (the fast, ordinary case) OR byte-identical
    content. Content is what makes the answer travel between trees, because the
    exporter copies ``config.example.yaml`` verbatim.

    The NAME is deliberately never consulted. A REAL config that merely happens to
    be called ``config.example.yaml`` holds different bytes and stays REAL — this
    must not become a way for an owner's real identity to disarm the guard. And a
    config that is a verbatim copy of the example IS the example: it carries no
    real identity, so refusing to arm on it is the correct answer.

    Both ways of being wrong fail CLOSED. Mistaking a real config for the example
    yields zero identity tokens, which is the UNARMED refusal (exit 2) — loud,
    never a silent pass. Mistaking the example for a real config yields false
    violations (exit 1). Neither certifies a tree it should not.
    """
    try:
        if Path(active).resolve() == Path(example).resolve():
            return True
    except OSError:
        pass
    return _same_file_content(Path(active), Path(example))


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
        is_example = is_example_config(active, Path(config.EXAMPLE_CONFIG))
    except Exception:  # noqa: BLE001
        is_example = False
    if is_example:
        return f"fictional example config ({active}) — no identity resolved from config"
    return f"real config ({active})"


# Shortest name compound the guard will trust as a high-specificity token,
# counted in ALPHANUMERICS. Two real name parts glued together are effectively
# collision-free, but ``li`` + ``wu`` is four letters and would start hitting
# inside base64 and hex runs, so short pairings are dropped rather than shipped
# as a new class of false positive.
_MIN_COMPOUND_LEN = 6

# Separators a written full name is spelled with. Joined forms are what still
# catches "Long Green" when BOTH parts carry an English-word allowance (see
# ``word_token_allowances``); the glued forms cover filenames and handles.
_NAME_JOINERS = (" ", "-", "_", ".", ", ")


def _name_compounds(parts: list[str]) -> set[str]:
    """Two-part combinations of a name — all of them high-specificity.

    ``Jordan`` + ``Rivers`` yields ``jordanrivers``, ``jrivers``, ``jordanr``,
    ``jordan rivers``, ``jordan-rivers``, ``jordan_rivers``, ``jordan.rivers``,
    ``jordan, rivers`` and the same list with the parts swapped.

    These are what BUYS the word-boundary rule for the individual parts. Every
    leak shape that glues the name to something else — ``linkedin.com/in/
    jordanrivers``, ``github.com/JordanRivers``, ``jrivers@corp``,
    ``acme-jordanrivers/``, ``/Users/jordanrivers`` — is a compound, so the
    parts themselves no longer need to match inside ordinary words to be
    caught. Pinned by ``MUST_STILL_CATCH`` in the test module.
    """
    usable = [p.lower() for p in parts if len(p) >= 2]
    out: set[str] = set()
    for i, first in enumerate(usable):
        for j, second in enumerate(usable):
            if i == j:
                continue
            candidates = [first + second, first[0] + second, first + second[0]]
            candidates += [first + sep + second for sep in _NAME_JOINERS]
            # The floor is measured on ALPHANUMERICS, so a separator cannot
            # smuggle a short pairing past it (``li, wu`` is six characters and
            # four letters — still ``liwu``).
            out.update(c for c in candidates
                       if len(re.sub(r"[^A-Za-z0-9]", "", c)) >= _MIN_COMPOUND_LEN)
    return out


def _derive_identity(config) -> tuple[set[str], set[str]]:
    """``(identity tokens, the subset that keeps SUBSTRING matching)``.

    Derived from the ACTIVE config — only if it is a real one. When the
    discovered config is the tracked ``config.example.yaml`` fallback (the
    fictional example persona), BOTH sets are empty so the example identity is
    never treated as a leak. "Is it the example" is decided by
    ``is_example_config`` — content identity, not an absolute path, because the
    exporter reads the same file from two different trees.

    The second set is the HIGH-SPECIFICITY half: the full email address, the
    linkedin/github handles, the machine home-directory basename, and the name
    compounds. Those keep the old containment semantics unconditionally, because
    a chance collision with ordinary prose is not a real possibility for any of
    them — and because they are what still catches a glued leak once the bare
    name parts are boundary-matched. Everything else (the name parts, a bare
    email local part) is classified by shape in ``classify_tokens``.
    """
    toks: set[str] = set()
    strict: set[str] = set()
    try:
        active = Path(config.config_path())
        example = Path(config.EXAMPLE_CONFIG)
    except Exception:
        return toks, strict
    if is_example_config(active, example):
        return toks, strict

    name = config.candidate_name()
    parts = [p for p in (raw.strip("'")
                         for raw in re.split(r"[^A-Za-z0-9']+", name or "")) if p]
    for part in parts:
        if len(part) >= 3:
            toks.add(part)
    for compound in _name_compounds(parts):
        toks.add(compound)
        strict.add(compound)

    contact = config.contact_line() or ""
    for email in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", contact):
        toks.add(email)
        strict.add(email)
        # The LOCAL PART is deliberately not marked high-specificity: it is very
        # often just the surname (``green@``), and forcing containment on it
        # would put the false positives straight back. Its usual shapes —
        # ``jordan.rivers``, ``jrivers`` — are classified as substring anyway,
        # by punctuation and by compound-containment respectively.
        local = email.split("@", 1)[0]
        if len(local) >= 3:
            toks.add(local)
    for handle in re.findall(r"(?:linkedin\.com/in/|github\.com/)([A-Za-z0-9\-_]+)", contact):
        if len(handle) >= 3:
            toks.add(handle)
            strict.add(handle)

    # The machine home-directory basename (e.g. ``alex``) catches leaked absolute
    # paths like ``/Users/alex/...``. Only added alongside a real config, so CI /
    # example runs (which use the fictional fallback) never pick up a CI home name.
    home = Path.home().name
    if len(home) >= 3:
        toks.add(home)
        strict.add(home)
    return toks, strict


def _identity_tokens(config) -> set[str]:
    """Identity tokens derived from the ACTIVE config (see ``_derive_identity``)."""
    return _derive_identity(config)[0]


def high_specificity_tokens() -> set[str]:
    """Identity tokens that keep SUBSTRING matching whatever their shape.

    Only the config derivation knows a token's PROVENANCE, so this is where an
    email / handle / home basename / name compound is named as such. Tokens that
    arrive flat through ``$JOBHUNT_PERSONAL_TOKENS`` or ``leak_tokens.txt`` have
    no provenance to read and are classified by SHAPE instead — punctuation, a
    digit, or containing another active token — which recovers the mode for
    every derived compound and every address the exporter forwards.
    """
    config = _load_shared_config()
    if config is None:
        return set()
    return _derive_identity(config)[1]


def _display_path(path: Path) -> str:
    """Repo-relative when possible, so a printed path never echoes a home directory."""
    try:
        return Path(path).relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _read_token_source(path: Path) -> tuple[set[str], str | None]:
    """Read one personal-token file. Returns ``(tokens, error)``.

    ABSENT is legitimate and returns ``(set(), None)`` — ``private/leak_tokens.txt``
    only exists in a maintainer checkout with the overlay mounted, and a public
    clone must still be able to run the guard.

    PRESENT BUT UNREADABLE is not. A permission error, an I/O error or a dangling
    symlink used to return that same empty set, so every employer/school/product
    token silently vanished from check 6 and the guard went on to print "Safe to
    publish" over a scan it had quietly narrowed. The guard fails CLOSED for the
    files it SCANS (check 8); its own arming input gets the same treatment — the
    reason comes back and ``scan()`` turns it into a violation (check 9).

    ENCODING is deliberately not an error: ``_decode_lossless`` recovers the
    tokens byte-for-byte, so one stray byte can never drop the whole set.
    """
    toks: set[str] = set()
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        # A DANGLING SYMLINK raises this too and is NOT an absence: something is
        # there, it claims to be the token file, and its content is gone.
        if path.is_symlink():
            return toks, "FileNotFoundError: dangling symlink"
        return toks, None
    except OSError as exc:
        return toks, _oserror_detail(exc)
    for line in _decode_lossless(data).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            toks.add(line)
    return toks, None


def token_source_errors(paths: list[Path] | None = None) -> list[dict]:
    """Personal-token files that EXIST but could not be read (check 9).

    Empty in the normal case, including the common one where the overlay is not
    mounted and the file is simply absent.
    """
    out: list[dict] = []
    for path in (LEAK_TOKENS_FILES if paths is None else paths):
        _, error = _read_token_source(path)
        if error is not None:
            out.append({"path": _display_path(path), "detail": error})
    return out


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


def _normalize_safe_word(word: str) -> str:
    """Fold a safe word or skill name to its comparison form.

    Lowercase, and every run of whitespace/underscore/hyphen becomes one space,
    so the three spellings a folder name and a written phrase differ by
    (``field-notes`` / ``field_notes`` / ``field notes``) compare equal. Nothing
    else is stripped — this decides only whether two names are the same name.
    """
    return _SAFE_WORD_SEP_RE.sub(" ", word.strip().lower()).strip()


def safe_words(paths: list[Path] | None = None) -> set[str]:
    """Normalized safe words the maintainer declared (see ``SAFE_WORDS_FILES``).

    ABSENT is legitimate and yields an empty set: a public clone has no overlay,
    and a maintainer who never hit a collision has no file.

    UNREADABLE is deliberately NOT a violation here, which looks inconsistent with
    ``_read_token_source``'s fail-closed contract until you check the direction.
    Losing a leak TOKEN narrows the scan — the guard stops looking for something
    and still says "Safe to publish", which is fail-OPEN and is what check 9
    exists to catch. Losing a safe WORD widens it: the exemption is not applied,
    the skill-name token stays live, and the guard over-reports. Over-reporting
    is the safe direction, so an unreadable file degrades to "no exemptions"
    rather than blocking the run. It is still SURFACED by ``safe_word_report()``,
    because a silently-ignored file means a red gate the maintainer cannot explain.
    """
    out: set[str] = set()
    for path in (SAFE_WORDS_FILES if paths is None else paths):
        raw, _error = _read_token_source(path)
        for word in raw:
            normalized = _normalize_safe_word(word)
            if normalized:
                out.add(normalized)
    return out


def _apply_safe_words(names: set[str], safe: set[str] | None = None) -> set[str]:
    """Drop the skill names the maintainer declared safe. Whole-name match only."""
    safe = safe_words() if safe is None else safe
    if not safe:
        return names
    return {n for n in names if _normalize_safe_word(n) not in safe}


def safe_word_report(root: Path = REPO_ROOT) -> dict:
    """What the safe-word list actually DID, so it is never silently in effect.

    ``exempted`` is the honest count of protection given up. ``ineffective`` names
    safe words that collide with a DECLARED token: those tokens stay live by
    design (see ``SAFE_WORDS_FILES``), and saying so beats letting the maintainer
    believe a word is exempt when the union puts it straight back.
    """
    safe = safe_words()
    names = _overlay_skill_name_tokens(root)
    exempted = sorted(n for n in names if _normalize_safe_word(n) in safe)
    declared = identity_tokens()
    for leak_file in LEAK_TOKENS_FILES:
        declared |= _read_token_source(leak_file)[0]
    ineffective = sorted(
        {_normalize_safe_word(t) for t in declared} & safe)
    errors = [
        {"path": _display_path(path), "detail": error}
        for path in SAFE_WORDS_FILES
        if (error := _read_token_source(path)[1]) is not None
    ]
    return {
        "declared": len(safe),
        "exempted": exempted,
        "ineffective": ineffective,
        "unreadable": errors,
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

    Returns only the tokens it could read. Whether a token FILE was unreadable —
    a narrowed scan rather than an empty one — is reported separately by
    ``token_source_errors()`` and gates in ``scan()`` (check 9).
    """
    toks: set[str] = set(PERSONAL_TOKENS)
    for leak_file in LEAK_TOKENS_FILES:
        toks |= _read_token_source(leak_file)[0]
    # Safe words are applied HERE, to the derived skill names only — not to the
    # union, and not to the leak-token lines read just above. Filtering at the
    # source is also what keeps the exemption true for anything
    # ``personal_tokens()`` forwards onward (see ``SAFE_WORDS_FILES``).
    toks |= _apply_safe_words(_overlay_skill_name_tokens())
    return toks


def personal_tokens() -> list[str]:
    """The full active token set: ``identity_tokens() | supplementary_tokens()``."""
    return sorted(identity_tokens() | supplementary_tokens())


# ── how a token MATCHES (hybrid: word boundary + high-specificity substring) ──
# Matching used to be pure case-insensitive containment — ``tok.lower() in
# text.lower()`` — with a ``len(part) >= 3`` filter as its only mitigation. That
# is unusable for an ordinary surname. Measured on this repo's 1209 tracked
# files, 17 of the 40 most common US surnames produced false violations: "King"
# inside ``making`` (491 files), "Long" (374), "Ross" inside ``cross-session``
# (327), "Green" (268), "Ward" inside ``outward`` (186), "Lee" inside
# ``time.sleep`` and ``FileExistsError`` (69), "Park" inside ``sparkling`` (50),
# "Hall" inside ``shallow`` (29), "Reed" inside ``agreed`` (17).
#
# That is not a cosmetic defect. The guard runs in pre-commit AND pre-push, so
# such an owner cannot commit at all, and their only two exits are
# ``--no-verify`` (forbidden by AGENTS.md) or deleting their identity from
# config.yaml — which DISARMS the guard completely. The false positive is the
# pressure that produces a fail-open checkout, which is why fixing it is a
# safety change and not a convenience one.
#
# So a token now carries a MODE:
#
#   BOUNDARY   a bare alphabetic word: a name part, a one-word employer, a
#              one-word skill name. It hits only at a word EDGE, where "edge"
#              means the seams identifiers and filenames actually use as well as
#              the ones prose does — punctuation, ``_``, ``-``, ``/``, a digit,
#              or a case hump (``JordanRivers``, ``HTTPRivers``). ``making``
#              does not contain "King" at an edge; ``?owner=jordan&`` does.
#   SUBSTRING  the pre-existing rule, kept verbatim, for tokens specific enough
#              that a chance collision is not a real possibility: an email
#              address, a linkedin/github handle, the home-directory basename,
#              anything carrying punctuation or a digit, and the CONCATENATED
#              COMPOUNDS derived from the name parts.
#
# The compounds are what makes the boundary half safe. A boundary-only fix
# silently stops catching five real leak shapes the old rule caught —
# ``linkedin.com/in/jordanrivers``, ``github.com/JordanRivers``,
# ``jrivers@corp``, ``acme-jordanrivers/``, ``/Users/jordanrivers`` — because in
# every one of them the name is glued to something. Those five, and seventeen
# other shapes, are pinned by ``MUST_STILL_CATCH`` in the test module.
TOKEN_BOUNDARY = "boundary"
TOKEN_SUBSTRING = "substring"

# ── the English-word allowance (opt-in, loud, never automatic) ───────────────
# Boundaries fix a surname hiding INSIDE a word. They cannot fix a surname that
# IS a word. After the edge rule, "Green" still flags 210 files on this tree and
# "Long" still flags 107 — every one of them the honest English word — and
# nothing can distinguish ``Menlo Park`` from ``Alex Park``, because they are the
# same string in the same shape.
#
# So the owner may DECLARE such a token an ordinary word, and the guard stops
# raising that one bare word as a violation. Four properties make that a
# trade rather than a hole, and each is tested:
#
#   OPT-IN       never inferred, never derived from a word list. The owner writes
#                it in the git-ignored config.yaml (or the env var below). No
#                agent adds one, and no tracked file can carry one — a public
#                list of "words that are also my surname" would itself be the
#                disclosure.
#   LOUD         every declared word and the COUNT of occurrences it suppressed
#                is printed on EVERY run, clean or failing.
#   NARROW       it reaches BOUNDARY tokens only. The email address, the
#                linkedin/github handles, the home-directory basename and every
#                name compound (``alexgreen``, ``agreen``, ``alex-green``,
#                ``alex green``) keep full containment, so the full name written
#                any way at all is still caught — including when BOTH parts of
#                the name are allowed words.
#   STILL ARMED  an allowed token is still an identity token. It counts towards
#                arming, so declaring one can never push the guard into the
#                unarmed exit-2 state where everything is "safe to publish".
#
# The owner-facing question about whether this trade should exist at all is
# filed at message-queue/needs-human/decisions/leak-guard-homonym-surname-allowance.md.
#
# Env channel, mirroring ``TOKENS_ENV_VAR``: CI and the exporter arm the guard
# through the environment rather than a config.yaml, so an allowance that lived
# only in config.yaml would leave the same owner blocked in the one place they
# cannot edit.
WORD_ALLOWANCE_ENV_VAR = "JOBHUNT_LEAK_GUARD_WORD_TOKENS"


class TokenSpec(NamedTuple):
    """One active token plus HOW it is allowed to match."""

    token: str
    mode: str
    # Compiled for BOUNDARY tokens, None for SUBSTRING ones.
    pattern: re.Pattern | None
    # True when the OWNER declared this token an ordinary English word. Its
    # matches are counted and reported, never raised as violations. Only ever
    # set on a BOUNDARY token (see ``classify_tokens``).
    allowed: bool = False


def word_token_allowances() -> set[str]:
    """Tokens the OWNER declared to be ordinary English words (normalized).

    Two declaration channels, both git-ignored and both explicit:
    ``leak_guard.english_word_tokens`` in ``config.yaml``, and
    ``$JOBHUNT_LEAK_GUARD_WORD_TOKENS`` for CI / the exporter. Absent is the
    normal state and yields an empty set.

    The config channel is gated on the config being REAL, exactly like the
    identity derivation: the fictional example persona declares nothing, so a
    public clone can never inherit an allowance it did not choose.

    Comparison is by ``_normalize_safe_word`` — case-folded, separators unified —
    so ``Green`` and ``green`` are the same declaration. A failure to read the
    config degrades to NO allowance, which widens the scan rather than narrowing
    it; that is the safe direction and needs no gate of its own.
    """
    out: set[str] = set()
    for line in os.environ.get(WORD_ALLOWANCE_ENV_VAR, "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for raw in line.split(","):
            normalized = _normalize_safe_word(raw)
            if normalized:
                out.add(normalized)
    config = _load_shared_config()
    declared: list = []
    if config is not None:
        try:
            if not is_example_config(Path(config.config_path()),
                                     Path(config.EXAMPLE_CONFIG)):
                reader = getattr(config, "leak_guard_english_word_tokens", None)
                declared = list(reader() or ()) if reader else []
        except Exception:  # noqa: BLE001 — a broken config widens the scan
            declared = []
    for raw in declared:
        normalized = _normalize_safe_word(str(raw))
        if normalized:
            out.add(normalized)
    return out


def _boundary_pattern(token: str) -> re.Pattern:
    """Case-insensitive finder for every OVERLAPPING occurrence of ``token``.

    The capture-inside-lookahead shape is deliberate. A plain ``finditer``
    consumes each match, so an occurrence whose edges FAIL would swallow the
    text of an overlapping one whose edges pass, and the guard would miss it.
    Zero-width matching sees every start position.
    """
    return re.compile(f"(?=({re.escape(token)}))", re.IGNORECASE)


def _left_edge(text: str, start: int) -> bool:
    """Is ``start`` the beginning of a word, an identifier part, or a hump?"""
    if start <= 0:
        return True
    prev = text[start - 1]
    # Punctuation, whitespace, '/', '_', '-', a quote, a digit. A DIGIT counts:
    # ``jordan2026_resume`` is a leak, and ordinary English words do not carry
    # digits mid-word, so this direction costs nothing and catches more.
    if not prev.isalpha():
        return True
    cur = text[start]
    if prev.islower() and cur.isupper():
        return True                     # camelCase seam: myJordan
    if (prev.isupper() and cur.isupper()
            and start + 1 < len(text) and text[start + 1].islower()):
        return True                     # acronym seam: JORDANRivers
    return False


def _right_edge(text: str, end: int) -> bool:
    """Is ``end`` the end of a word, an identifier part, or a hump?"""
    if end >= len(text):
        return True
    nxt = text[end]
    if not nxt.isalpha():
        return True
    last = text[end - 1]
    if last.islower() and nxt.isupper():
        return True                     # JordanRivers
    if (last.isupper() and nxt.isupper()
            and end + 1 < len(text) and text[end + 1].islower()):
        return True                     # JORDANRivers
    return False


def _is_boundary_hit(text: str, start: int, end: int) -> bool:
    return _left_edge(text, start) and _right_edge(text, end)


def classify_tokens(tokens, force_substring=None, allowances=None) -> list[TokenSpec]:
    """Decide each token's matching mode. The ONE place that decision is made.

    ``force_substring`` names the tokens whose PROVENANCE makes them
    high-specificity (see ``high_specificity_tokens``). Everything else is
    judged by SHAPE, which is what keeps the mode correct for a token set that
    arrived flat through ``$JOBHUNT_PERSONAL_TOKENS`` or ``leak_tokens.txt``:

      * not a bare alphabetic word (an email, ``jordan.rivers``, ``field-notes``,
        a handle with a digit) -> SUBSTRING. Specific by construction.
      * contains another active token (``jordanrivers`` over ``jordan``)
        -> SUBSTRING. A concatenation is specific by construction too, and this
        is what recovers the compounds' mode after a flat round trip.
      * otherwise -> BOUNDARY.

    ``allowances`` are the owner's declared English words (normalized). The flag
    is set ONLY on a token that came out BOUNDARY, so an allowance can never
    reach an email, a handle, the home basename or a name compound however it is
    spelled — the ``mode`` decision above happens first and is not consulted for
    permission.

    Ordering is preserved so the reported token is deterministic.
    """
    forced = {t.lower() for t in (force_substring or ())}
    allowed_words = set(allowances or ())
    lowered = sorted({t.lower() for t in tokens if t and t.strip()})
    specs: list[TokenSpec] = []
    for token in tokens:
        if not token or not token.strip():
            # An empty token would match everywhere; it is a malformed input,
            # never a secret.
            continue
        low = token.lower()
        boundary = (
            low not in forced
            and low.isalpha()
            and not any(other != low and len(other) >= 3 and other in low
                        for other in lowered)
        )
        specs.append(TokenSpec(
            token=token,
            mode=TOKEN_BOUNDARY if boundary else TOKEN_SUBSTRING,
            pattern=_boundary_pattern(token) if boundary else None,
            allowed=boundary and _normalize_safe_word(token) in allowed_words,
        ))
    return specs


def _spec_match_count(spec: TokenSpec, text: str, text_lower: str) -> int:
    """How many times ``spec`` matches ``text`` under its own mode."""
    low = spec.token.lower()
    if low not in text_lower:
        # Containment is a necessary condition for BOTH modes, and it is the
        # cheap C-level test, so it stays the first thing every scan does. For a
        # SUBSTRING token it is also the whole rule — byte-identical to the
        # behaviour this guard has always had.
        return 0
    if spec.mode == TOKEN_SUBSTRING:
        return text_lower.count(low)
    return sum(1 for m in spec.pattern.finditer(text)
               if _is_boundary_hit(text, m.start(1), m.end(1)))


def _spec_hits(spec: TokenSpec, text: str, text_lower: str) -> bool:
    """Does ``spec`` match ``text`` at all? (Short-circuits; never counts.)"""
    low = spec.token.lower()
    if low not in text_lower:
        return False
    if spec.mode == TOKEN_SUBSTRING:
        return True
    return any(_is_boundary_hit(text, m.start(1), m.end(1))
               for m in spec.pattern.finditer(text))


def first_token_hit(specs, text: str, text_lower: str | None = None) -> str | None:
    """The first NON-ALLOWED token in ``specs`` that matches ``text``, or None.

    Shared by the guard and the exporter's allowlist screen so the two can never
    disagree about what counts as a hit — including about an allowance, which
    must reach both or the export drops files the guard would pass.
    """
    text_lower = text.lower() if text_lower is None else text_lower
    for spec in specs:
        if spec.allowed:
            continue
        if _spec_hits(spec, text, text_lower):
            return spec.token
    return None


def allowed_specs(specs) -> list[TokenSpec]:
    """The subset carrying an English-word allowance (usually empty)."""
    return [spec for spec in specs if spec.allowed]


def count_allowance_hits(specs, text: str, counts: dict,
                         text_lower: str | None = None) -> None:
    """Tally what the allowance suppressed, so it is never silently in effect.

    ``specs`` here is expected to be the ``allowed_specs`` subset: the caller
    checks it is non-empty before paying for a second pass over the text, which
    keeps the ordinary no-allowance run exactly as cheap as before.
    """
    if not specs:
        return
    text_lower = text.lower() if text_lower is None else text_lower
    for spec in specs:
        hits = _spec_match_count(spec, text, text_lower)
        if hits:
            counts[spec.token] = counts.get(spec.token, 0) + hits


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
            active = Path(config.config_path())
            is_example = is_example_config(active, Path(config.EXAMPLE_CONFIG))
        except Exception:
            active = None
            is_example = False
        if active is None:
            lines.append("  active config:  <could not be resolved>")
        elif is_example:
            lines.append(f"  active config:  {active}")
            lines.append("                  ^ the TRACKED example fallback — the fictional "
                         "persona contributes zero tokens by design")
        else:
            lines.append(f"  active config:  {active} (no identity fields resolved from it)")
    lines.append(f"  ${TOKENS_ENV_VAR}: "
                 f"{'set but empty' if TOKENS_ENV_VAR in os.environ else 'unset'}")
    supplementary = supplementary_tokens()
    for leak_file in LEAK_TOKENS_FILES:
        error = _read_token_source(leak_file)[1]
        if error is not None:
            # Never let "unreadable" read as "absent" here either: absent is the
            # normal state of a public clone, unreadable is a broken maintainer one.
            state = f"UNREADABLE ({error})"
        else:
            state = "present" if leak_file.exists() else "absent"
        lines.append(f"  {_display_path(leak_file)}: {state} "
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
#              raw binary blob, an image or archive it has no extractor for.
#              Expected, counted, named — never fatal. Failing here would fail on
#              every ordinary binary in the tree, and a guard that cries wolf on
#              `examples/screenshots/*.jpg` is a guard someone switches off.
#              A file that is not valid UTF-8 does NOT belong here: it used to,
#              and that was a hole — a NUL-free latin-1 `.md` carrying a real name
#              was counted, never searched, and the tree still certified. It is
#              decoded by `_decode_lossless` and READ like anything else now.
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
SKIP_NO_EXTRACTOR = "no-text-extractor"  # image/archive: nothing to extract
SKIP_EXTRACT_FAILED = "extract-failed"  # extractor ran; container malformed/lib missing
UNREADABLE_BROKEN_SYMLINK = "broken-symlink"
UNREADABLE_OPEN_FAILED = "open-failed"

# Read statuses. Both mean "the bytes were searched"; the second says the file
# needed the mixed decoder, which the report names so a lossy-looking input is
# never invisible.
READ_UTF8 = "read"
READ_FALLBACK_DECODE = "utf8+latin-1"


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


def _decode_lossless(data: bytes) -> str:
    """Decode UTF-8, falling back to latin-1 for exactly the bytes UTF-8 rejects.

    Neither single codec is sufficient, and the gap between them is a leak:

      * ``data.decode("utf-8", errors="replace")`` keeps UTF-8-encoded text but
        turns each rejected byte into U+FFFD, which SPLITS a latin-1-encoded token
        (``Bj\\xf8rnholm`` -> ``Bj?rnholm``) and defeats the substring match;
      * ``data.decode("latin-1")`` never fails, but mojibakes every UTF-8-encoded
        non-ASCII token (``Z\\xc3\\xbcrich`` -> ``ZÃ¼rich``).

    Splicing them keeps both properties: a valid UTF-8 sequence decodes to its
    real characters, and every byte UTF-8 rejects becomes its latin-1 character (a
    1:1 map over 0x00-0xFF). No byte is dropped and no token is split, which is
    what lets an undecodable text file be SCANNED instead of merely counted.

    Only reached when strict UTF-8 has already failed, so the ordinary path pays
    nothing. NUL-bearing blobs are sniffed out before this — decoding a compressed
    payload would just hand the scanner megabytes of noise.
    """
    chunks: list[str] = []
    pos = 0
    while True:
        try:
            chunks.append(data[pos:].decode("utf-8"))
            return "".join(chunks)
        except UnicodeDecodeError as exc:
            # ``exc.start``/``exc.end`` are relative to the slice handed to
            # decode(); ``end > start`` always, so ``pos`` strictly advances.
            chunks.append(data[pos:pos + exc.start].decode("utf-8"))
            chunks.append(data[pos + exc.start:pos + exc.end].decode("latin-1"))
            pos += exc.end


def _read_text_classified(path: Path) -> tuple[list[str] | None, str, str]:
    """Read ``path`` as text lines AND say why, when that did not happen.

    Returns ``(lines, status, detail)``. ``status`` is ``READ_UTF8`` with the
    lines, ``READ_FALLBACK_DECODE`` with the lines when strict UTF-8 rejected a
    byte and ``_decode_lossless`` recovered it, ``SKIP_BINARY_SNIFF`` (opened, no
    text to scan) or ``UNREADABLE_OPEN_FAILED`` (never opened — a check-8
    finding). Line NUMBERS stay true to the file in every case: the mixed decode
    is byte-preserving, so it never adds or removes a line break.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, UNREADABLE_OPEN_FAILED, _oserror_detail(exc)
    if b"\x00" in data:
        return None, SKIP_BINARY_SNIFF, ""
    try:
        return data.decode("utf-8").splitlines(), READ_UTF8, ""
    except UnicodeDecodeError as exc:
        return (_decode_lossless(data).splitlines(), READ_FALLBACK_DECODE,
                f"undecodable byte at offset {exc.start}; read with a latin-1 fallback")


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
               specs: list[TokenSpec],
               token_viols: list[dict], pii_viols: list[dict],
               allowed: list[TokenSpec] = (), allowance_counts: dict | None = None
               ) -> None:
    """Scan one whole-file string for tokens (first hit) + structural PII (per kind)."""
    blob_lower = blob.lower()
    if allowed and allowance_counts is not None:
        count_allowance_hits(allowed, blob, allowance_counts, blob_lower)
    hit = first_token_hit(specs, blob, blob_lower)
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
    root: Path, tracked: list[str], tokens: list[str],
    force_substring: set[str] | None = None,
    allowances: set[str] | None = None,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Scan file PATHs and CONTENT for personal tokens AND structural PII.

    Path token matches apply to every file. Text-file content is scanned line by
    line; document binaries have their extracted text + metadata scanned; a
    symlink's stored TARGET PATH is its content; images and other unextractable
    fail-closed binaries are reported for manual review. The guard file itself is
    content-exempt (it embeds the detection patterns).

    ``force_substring`` and ``allowances`` are passed straight to
    ``classify_tokens`` — the tokens whose provenance makes containment the right
    rule regardless of shape, and the owner's declared English words.

    Returns ``(token_violations, structural_pii_violations, unscanned_binaries,
    inspection)``, where ``inspection`` accounts for every tracked path exactly
    once — ``files_read`` + ``files_skipped`` + ``unreadable`` — so a caller can
    tell "clean" from "inspected nothing" (see the INSPECTION notes above). It
    also carries ``allowance_skipped`` / ``allowance_tokens``: what the English-
    word allowance actually cost, which the report prints on every run.
    """
    root = Path(root)
    specs = classify_tokens(tokens, force_substring=force_substring,
                            allowances=allowances)
    allowed = allowed_specs(specs)
    # Tokens matched by the BOUNDARY rule and not already allowed: exactly the
    # set an English-word allowance can reach. Carried through so the report can
    # name the escape hatch AT the moment a bare name part blocks someone, which
    # is the only moment they will go looking for it.
    boundary_tokens = [spec.token for spec in specs
                       if spec.mode == TOKEN_BOUNDARY and not spec.allowed]
    allowance_counts: dict[str, int] = {}
    token_viols: list[dict] = []
    pii_viols: list[dict] = []
    unscanned: list[dict] = []
    skipped: list[dict] = []
    unreadable: list[dict] = []
    fallback: list[dict] = []
    files_read = 0

    for rel in tracked:
        rel_lower = rel.lower()
        count_allowance_hits(allowed, rel, allowance_counts, rel_lower)
        path_tok = first_token_hit(specs, rel, rel_lower)
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
                       specs, token_viols, pii_viols, allowed, allowance_counts)
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
                       specs, token_viols, pii_viols, allowed, allowance_counts)
            continue

        lines, status, detail = _read_text_classified(src)
        if lines is None:
            if status == UNREADABLE_OPEN_FAILED:
                unreadable.append({"path": rel, "reason": status, "detail": detail})
            else:
                skipped.append({"path": rel, "reason": status})
            continue
        files_read += 1
        if status == READ_FALLBACK_DECODE:
            # Read and scanned — but say so out loud. A file that needed the
            # mixed decoder is worth an operator's eye even when it is clean.
            fallback.append({"path": rel, "detail": detail})
        token_found = False
        seen_kinds: set[str] = set()
        for lineno, line in enumerate(lines, start=1):
            if allowed or not token_found:
                line_lower = line.lower()
                # Counted on EVERY line, including after a violation was already
                # found in this file: the printed count is the honest size of the
                # protection given up, not "however much fitted before we
                # stopped looking".
                count_allowance_hits(allowed, line, allowance_counts, line_lower)
            if not token_found:
                hit = first_token_hit(specs, line, line_lower)
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
        # What the English-word allowance cost: the tokens it covers (even at
        # zero occurrences — an allowance in effect is reported whether or not
        # it fired) and how many matches it suppressed.
        "allowance_tokens": [spec.token for spec in allowed],
        "allowance_skipped": allowance_counts,
        # Tokens an allowance COULD reach (see above). Never a violation itself.
        "boundary_tokens": boundary_tokens,
        # A SUBSET of files_read (informational, never fatal), so the
        # read + skipped + unreadable == tracked accounting still holds.
        "fallback_decoded": fallback,
    }
    return token_viols, pii_viols, unscanned, inspection


def scan(root: Path = REPO_ROOT, tracked: list[str] | None = None,
         tokens: list[str] | None = None,
         visibility_root: Path | None = None,
         force_substring: set[str] | None = None,
         allowances: set[str] | None = None) -> dict:
    """Run every check and return a structured result.

    ``root`` may be a git work tree (default: this repo) or any plain directory
    tree (used by the tests / an export scratch). ``tracked`` / ``tokens`` can be
    supplied to make a scan fully deterministic (the tests do this).
    ``visibility_root`` is where ``skills/*/SKILL.md`` frontmatter is READ from; it
    defaults to ``root`` and differs only in ``--staged`` mode, where the scanned
    tree holds just the staged blobs while the visibility declarations live in the
    work tree.

    ``force_substring`` and ``allowances`` are only consulted when the caller
    SUPPLIED ``tokens``. When the guard resolves its own token set it also
    resolves the provenance and the owner's declarations that go with it
    (``high_specificity_tokens``, ``word_token_allowances``), and a
    caller-supplied override there would silently describe a different scan than
    the one that ran.

    NOTE: this function never gates on the token set being armed — it is pure
    detection, so a fixture scan can pass ``tokens=[]`` deliberately. The
    fail-closed arming gate lives in ``main()``.
    """
    root = Path(root).resolve()
    if tracked is None:
        tracked = _list_files(root)
    identity_count: int | None = None
    supplementary_count: int | None = None
    token_source_errs: list[dict] = []
    safe_words_info: dict | None = None
    if tokens is None:
        identity = identity_tokens()
        supplementary = supplementary_tokens()
        # Reported, never gating: giving up protection on a skill name is a
        # maintainer decision, and this is the line that keeps it visible.
        #
        # Deliberately NOT ``safe_word_report(root)``. The filter above ran inside
        # ``supplementary_tokens()`` against the real checkout, so the report has
        # to read the same tree or it describes a scan that did not happen. In
        # ``--staged`` mode ``root`` is a temp tree of staged blobs with no
        # ``private/`` at all, which would report "0 exempted" for a run whose
        # tokens were in fact filtered.
        safe_words_info = safe_word_report()
        identity_count = len(identity)
        supplementary_count = len(supplementary - identity)
        tokens = sorted(identity | supplementary)
        force_substring = high_specificity_tokens()
        allowances = word_token_allowances()
        # The guard resolved its OWN token set, so a token file that exists but
        # could not be read makes the scan below silently NARROWER than it should
        # be — the exact fail-open shape check 9 exists to stop. When the caller
        # supplied ``tokens`` the files were never consulted and there is nothing
        # to narrow, which is what keeps fixture scans deterministic.
        token_source_errs = token_source_errors()

    private_skill = find_private_skill_violations(
        Path(visibility_root).resolve() if visibility_root else root, tracked)
    overlay = find_personal_overlay_violations(tracked)
    skill_notes = find_skill_notes_violations(tracked)
    path_denylist = find_path_denylist_violations(tracked)
    token_viols, pii_viols, unscanned, inspection = find_token_and_pii_violations(
        root, tracked, tokens, force_substring=force_substring,
        allowances=allowances)
    unreadable = inspection["unreadable"]

    # What the English-word allowance actually DID, so it is never silently in
    # effect. ``reduced`` names every token whose protection was narrowed (with
    # its suppressed count, zero included); ``ineffective`` names a declaration
    # that reached nothing — most importantly one aimed at a high-specificity
    # token, which is never weakened however it is declared.
    word_allowances = None
    if allowances:
        reduced_tokens = inspection.get("allowance_tokens") or []
        skipped_counts = inspection.get("allowance_skipped") or {}
        word_allowances = {
            "declared": sorted(allowances),
            "reduced": {tok: skipped_counts.get(tok, 0) for tok in reduced_tokens},
            "ineffective": sorted(
                allowances - {_normalize_safe_word(t) for t in reduced_tokens}),
        }

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
        "token_source_unreadable": [
            {"category": "token_source_unreadable", **item} for item in token_source_errs],
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
        # None when the caller injected tokens (the files were never consulted).
        "safe_words": safe_words_info,
        # None when the owner declared no English-word allowance (the norm).
        "word_allowances": word_allowances,
        # Active tokens matched at a word/identifier EDGE and not already
        # allowed — the only ones ``leak_guard.english_word_tokens`` can reach.
        # The report turns this into the fix hint printed under check 6.
        "boundary_tokens": inspection["boundary_tokens"],
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
        # Files that were READ (they count in files_read) but only after the
        # UTF-8 + latin-1 mixed decode. Named so a lossy-looking input is never
        # invisible; never a violation, because its bytes WERE searched.
        "fallback_decoded": inspection["fallback_decoded"],
        "ok": total == 0,
        "total_violations": total,
        "violations": violations,
    }


# ── staged-index mode (pre-commit) ───────────────────────────────────────────
# The empty tree, so the very first commit in a repo (no HEAD) still diffs.
_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(args: list[str], repo_root: Path, binary: bool = False,
         env: dict[str, str] | None = None):
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True,
        text=not binary, env=env,
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


def _rewrite_materialized_symlinks(paths: list[str], dest: Path) -> None:
    """Replace checked-out symlinks with the target text stored in their blobs."""
    for rel in paths:
        p = dest / rel
        if p.is_symlink():
            target = os.readlink(p)
            p.unlink()
            p.write_text(target + "\n", encoding="utf-8")


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
    _rewrite_materialized_symlinks(paths, dest)


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


# ── immutable git-object mode (pre-push) ────────────────────────────────────
def _git_tree(repo_root: Path, object_name: str) -> str:
    """Resolve ``object_name`` to a tree object, or fail closed."""
    return _git(
        ["rev-parse", "--verify", f"{object_name}^{{tree}}"], repo_root
    ).stdout.strip()


def git_tree_paths(repo_root: Path, tree: str) -> list[str]:
    """Return every path stored in ``tree``, independent of index/worktree state."""
    out = _git(
        ["ls-tree", "-r", "--full-tree", "--name-only", "-z", tree], repo_root
    ).stdout
    return [path for path in out.split("\0") if path]


def _materialize_tree(repo_root: Path, tree: str, paths: list[str], dest: Path,
                      index_path: Path) -> None:
    """Check out ``tree`` through an isolated temporary index under ``dest``.

    ``GIT_INDEX_FILE`` is the crucial isolation boundary: ``read-tree`` never
    changes the caller's shared index, branch, HEAD, or files, including when the
    caller is one of several linked worktrees.
    """
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(index_path)
    _git(["read-tree", tree], repo_root, env=env)
    subprocess.run(
        ["git", "checkout-index", "--all", "--force",
         f"--prefix={dest.as_posix()}/"],
        cwd=repo_root, check=True, capture_output=True, env=env,
    )
    _rewrite_materialized_symlinks(paths, dest)


def scan_git_object(repo_root: Path, object_name: str,
                    tokens: list[str] | None = None) -> dict:
    """Run the full guard on the immutable tree named by ``object_name``.

    Pre-push supplies the exact local object ID for every ref update. Scanning
    that tree prevents another worktree, a non-HEAD push, or unstaged edits from
    hiding bytes that are actually about to leave the repository.
    """
    repo_root = Path(repo_root).resolve()
    tree = _git_tree(repo_root, object_name)
    paths = git_tree_paths(repo_root, tree)
    with tempfile.TemporaryDirectory(prefix="leak-guard-object-") as td:
        scratch = Path(td)
        dest = scratch / "tree"
        dest.mkdir()
        _materialize_tree(repo_root, tree, paths, dest, scratch / "index")
        result = scan(root=dest, tracked=paths, tokens=tokens)
    result["repo_root"] = f"{repo_root} (git object {object_name})"
    result["mode"] = "git-object"
    result["git_object"] = object_name
    result["git_tree"] = tree
    return result


def word_allowance_hint(result: dict) -> list[str]:
    """Lines telling a blocked operator that the English-word allowance exists.

    THE FAILURE OUTPUT IS THE ONLY PLACE THIS GETS READ. An owner surnamed for a
    colour, a length or a place is blocked by this guard on tracked prose they
    never wrote, in a hook, mid-commit; they will not go and read a handbook to
    find out that ``leak_guard.english_word_tokens`` exists. Undiscoverable, the
    mechanism's real-world substitute is deleting the identity out of
    ``config.yaml`` — which disarms check 6 completely and permanently, and is
    the one state in which a tree full of the owner's real name reports "Safe to
    publish". So the hint is printed exactly where the wall is.

    It is printed for BOUNDARY tokens only, because those are the only ones an
    allowance can reach: an email address, a linkedin/github handle, the
    home-directory basename and every compound of the full name keep plain
    containment whatever is declared, and offering the hint for one of those
    would be advertising a fix that does not work.

    Returns lines rather than printing them so the caller owns the layout, and
    an empty list when there is nothing eligible — a leak that is genuinely a
    leak must not come with a suggestion for making it go away.
    """
    eligible = {t.lower() for t in (result.get("boundary_tokens") or ())}
    if not eligible:
        return []
    hits = result["violations"]["personal_token"]
    blocked = sorted({item["token"] for item in hits
                      if str(item.get("token", "")).lower() in eligible},
                     key=str.lower)
    if not blocked:
        return []
    named = ", ".join(repr(t) for t in blocked)
    return [
        "  Blocked by a name part sitting in this repository's OWN prose?",
        f"  {named} matched at a word/identifier edge — all a bare name can be",
        "  matched on. A name that is ALSO an ordinary word or a place name will",
        "  therefore hit timeless public text, and NO rule can tell that from a real",
        "  leak: the strings are identical. If that is what the hits above are, you",
        "  may declare the word. Opt-in, one token at a time:",
        "",
        "      # config.yaml (git-ignored; the owner types this, never an agent)",
        "      leak_guard:",
        f"        english_word_tokens: [{blocked[0]!r}]",
        "",
        "      # CI / the exporter, which have no config.yaml of their own:",
        f"      export {WORD_ALLOWANCE_ENV_VAR}='<word>[,<word>...]'",
        "",
        "  What it costs: that BARE word stops being reported anywhere in the tree.",
        "  What it never touches: your email address, your linkedin/github handles,",
        "  your home-directory basename, and every compound of your full name — they",
        "  keep full containment matching, so the name written any way at all is",
        "  still caught. Every run afterwards prints what the allowance skipped.",
        "  What NOT to do instead: emptying your identity out of config.yaml leaves",
        "  the guard UNARMED, and an unarmed guard prints 'Safe to publish' over a",
        "  tree that contains your real name.",
        "",
    ]


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
    token_sources = v.get("token_source_unreadable") or []

    print("Public-repo leak guard")
    print(f"  repo root:      {result['repo_root']}")
    labels = {
        "staged": "staged files: ",
        "git-object": "object files: ",
    }
    label = labels.get(result.get("mode"), "tracked files:")
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
        for item in result.get("fallback_decoded") or []:
            print(f"  mixed encoding: {item['path']} — {item['detail']} "
                  "(SCANNED, not skipped)")
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
    safe = result.get("safe_words")
    if safe and (safe["exempted"] or safe["ineffective"] or safe["unreadable"]):
        # Only printed when the list DID something (or failed to). A maintainer
        # with no collisions never sees this block.
        if safe["exempted"]:
            print(f"  safe words:           {safe['declared']} declared; "
                  f"{len(safe['exempted'])} overlay skill name(s) NOT protected "
                  f"({', '.join(safe['exempted'])})")
        for path_detail in safe["unreadable"]:
            print(f"  safe words:           IGNORED — {path_detail['path']} exists "
                  f"but could not be read ({path_detail['detail']}); no exemption "
                  "applied, so the scan is WIDER, not narrower")
        for word in safe["ineffective"]:
            print(f"  safe words:           '{word}' has NO effect — it also names a "
                  "declared token (config identity / leak_tokens.txt), which safe "
                  "words never remove")
    allow = result.get("word_allowances")
    if allow:
        # Printed on EVERY run, clean or failing. An allowance that is not
        # reported is an allowance nobody remembers granting.
        for token, count in sorted(allow["reduced"].items()):
            print(f"  word allowance:       '{token}' — identity protection REDUCED "
                  f"(you declared it an ordinary English word); {count} "
                  "occurrence(s) SKIPPED, not reported below")
        for word in allow["ineffective"]:
            print(f"  word allowance:       '{word}' has NO effect — it names no "
                  "boundary-matched token here; an email, handle, home-directory "
                  "basename or name compound is never weakened by an allowance")
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
        for line in word_allowance_hint(result):
            print(line)

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

    if token_sources:
        print(f"[9] Unreadable personal-token source ({len(token_sources)}) — the file "
              f"EXISTS but could not be read, so the token scan above ran on a "
              f"SILENTLY NARROWER token set:")
        for item in token_sources:
            print(f"  - {item['path']}  ({item['detail']})")
        print("  A missing token file is fine (a public clone has none); an unreadable "
              "one is not.\n  Fix: restore read permission, repoint the dangling link, "
              "or remove the file.\n")


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--staged",
        action="store_true",
        help="scan the STAGED INDEX content of the pending commit instead of the "
             "tracked work tree (used by the pre-commit hook)",
    )
    mode.add_argument(
        "--git-object",
        metavar="OID",
        help="scan the complete immutable tree named by OID instead of the index "
             "or work tree (used by the pre-push hook)",
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

    try:
        if args.staged:
            result = scan_staged()
        elif args.git_object:
            result = scan_git_object(REPO_ROOT, args.git_object)
        else:
            result = scan()
    except subprocess.CalledProcessError as exc:
        detail = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else exc.stderr
        )
        print("FAIL: leak guard could not resolve or materialize the requested Git "
              f"object {args.git_object!r}.", file=sys.stderr)
        if detail:
            print(detail.strip(), file=sys.stderr)
        return EXIT_VIOLATIONS
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_report(result)
    return EXIT_OK if result["ok"] else EXIT_VIOLATIONS


if __name__ == "__main__":
    raise SystemExit(main())
