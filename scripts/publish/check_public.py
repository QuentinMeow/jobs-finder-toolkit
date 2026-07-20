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

  1. Private skill leak. A skill whose ``.agents/skills/<skill>/SKILL.md``
     frontmatter declares ``visibility: private`` MUST have zero tracked files.
  2. Personal overlay leak. Any tracked path under the private overlay prefix
     (``private/``) must never ship.
  3. references_private leak. Any tracked file under a per-skill
     ``references_private/`` folder — candidate-specific skill content.
  4. Path/filename denylist (defense in depth). Any tracked path under a private
     product tree (``applications/``, ``interviews/``, ``.agents/inputs/``, the
     private ``coding-interview`` skill), any non-example file under
     ``templates/``, any ``meta.yaml`` outside ``examples/``, or any ``.docx`` /
     ``.pdf`` outside ``examples/``. This catches private trees even when zero
     identity tokens are active.
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

This guard is designed to go GREEN on a properly genericized public checkout. Run
it in a maintainer checkout (where ``config.yaml`` supplies the real tokens)
before publishing, and the exporter (``export_public.py``) runs it against the
freshly copied tree as the final gate.

Usage:
    .venv/bin/python scripts/publish/check_public.py
    .venv/bin/python scripts/publish/check_public.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# scripts/publish/check_public.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# This guard's own path (relative to the repo root). Its CONTENT is exempt from the
# token/structural-PII scans because it deliberately embeds the detection regexes
# and example patterns (e.g. ``/Users/alex/...``, ``linkedin.com/in/...``); its
# PATH is still screened. The file carries no real identity, so it is safe to
# publish verbatim.
GUARD_REL_PATH = "scripts/publish/check_public.py"

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
SKILLS_DIR = ".agents/skills"

# Per-skill folder that holds candidate-specific ("private") skill content. It is
# git-ignored and must never be tracked/shipped; any tracked file under it is a
# leak. (The sibling ``references_public/`` folder IS public and ships.)
REFERENCES_PRIVATE_DIRNAME = "references_private"
_REFERENCES_PRIVATE_RE = re.compile(r"(^|/)references_private(/|$)")

# The genericized, publicly-shippable example dataset. Files under it carry the
# fictional "Jordan Rivers" persona by design and are the ONLY place a tracked
# ``meta.yaml`` / ``.docx`` / ``.pdf`` is tolerated.
EXAMPLES_PREFIX = "examples/"


# ── path/filename denylist (defense in depth, token-independent) ──────────────
# Root-anchored private product trees that must never appear in a public tree.
# Anchored (``^``) so the tracked ``examples/applications/**`` dataset is NOT hit.
_DENY_TREES = [
    (re.compile(r"^applications/"), "applications/"),
    (re.compile(r"^interviews/"), "interviews/"),
    (re.compile(r"^\.agents/inputs/"), ".agents/inputs/"),
    (re.compile(r"^\.agents/skills/coding-interview/"), ".agents/skills/coding-interview/"),
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
            # ``templates/`` is terminal: it ships nothing but example-named
            # assets (mirrors the exporter, which copies example templates only
            # under examples/). An example-named template is fully allowed here —
            # do NOT fall through to the stray-binary check below.
            if ".example." not in Path(rel).name:
                reason = "templates-nonexample"
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
BINARY_ALLOWLIST = frozenset({
    "examples/templates/reference.example.docx",
})


def _binary_allowed(rel: str) -> bool:
    """True if ``rel`` is an intentionally-shipped binary (fail-closed exempt)."""
    return rel in BINARY_ALLOWLIST or rel.startswith(EXAMPLES_PREFIX)


def _load_shared_config():
    """Import the shared config loader (scripts/shared/config.py), or None.

    Repo-root tooling may import ``scripts/shared`` directly (see AGENTS.md). The
    guard uses it only to DERIVE tokens; a failure to import simply yields no
    identity tokens (the env var / overlay file still apply).
    """
    shared = REPO_ROOT / "scripts" / "shared"
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    try:
        import config  # type: ignore  # noqa: E402
        return config
    except Exception:
        return None


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


def personal_tokens() -> list[str]:
    """Resolve the active personal-identity token set (see the module comment).

    Union of: the ``JOBHUNT_PERSONAL_TOKENS`` env var, the real config identity
    (skipped for the fictional example), the git-ignored
    ``private/leak_tokens.txt``, and the (empty) shipped ``PERSONAL_TOKENS`` base.
    """
    toks: set[str] = set(PERSONAL_TOKENS)

    # Same comment/blank handling as the leak-token files, so the env var can be
    # populated verbatim from private/leak_tokens.txt (e.g. as a CI secret).
    # Comment LINES are dropped before comma-splitting, so a comma inside a
    # comment can never shed token fragments.
    for line in os.environ.get(TOKENS_ENV_VAR, "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for raw in line.split(","):
            raw = raw.strip()
            if raw:
                toks.add(raw)

    config = _load_shared_config()
    if config is not None:
        toks |= _identity_tokens(config)

    for leak_file in LEAK_TOKENS_FILES:
        toks |= _tokens_from_file(leak_file)
    return sorted(toks)


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
    """
    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() == "visibility":
            return value.strip().strip("'\"").lower() or None
    return None


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


def find_references_private_violations(tracked: list[str]) -> list[dict]:
    """Any tracked file under a per-skill ``references_private/`` folder is a leak."""
    return [
        {"category": "references_private", "path": p}
        for p in tracked
        if _REFERENCES_PRIVATE_RE.search(p)
    ]


def _read_text(path: Path) -> list[str] | None:
    """Return the file's lines as text, or ``None`` if it looks binary/unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


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


def _binary_text(path: Path, suffix: str) -> str | None:
    """Best-effort text extraction for a shipped binary, or None if unscannable."""
    if suffix in (".docx", ".doc", ".xlsx", ".pptx"):
        return _docx_text(path)
    if suffix == ".pdf":
        return _pdf_text(path)
    return None


def find_token_and_pii_violations(
    root: Path, tracked: list[str], tokens: list[str]
) -> tuple[list[dict], list[dict], list[str]]:
    """Scan file PATHs and CONTENT for personal tokens AND structural PII.

    Path token matches apply to every file. Text-file content is scanned line by
    line; document binaries have their extracted text + metadata scanned; images
    and other unextractable fail-closed binaries are reported for manual review.
    The guard file itself is content-exempt (it embeds the detection patterns).
    Returns ``(token_violations, structural_pii_violations, unscanned_binaries)``.
    """
    root = Path(root)
    lowered = [(tok, tok.lower()) for tok in tokens]
    token_viols: list[dict] = []
    pii_viols: list[dict] = []
    unscanned: list[str] = []

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
            continue

        suffix = Path(rel).suffix.lower()
        if suffix in BINARY_EXTENSIONS:
            blob = _binary_text(root / rel, suffix)
            if blob is None:
                # A binary we could not read as text (image, unextractable doc, or
                # missing PDF lib). Fail closed unless it is an intentionally-
                # shipped example asset.
                if suffix in FAIL_CLOSED_EXTENSIONS and not _binary_allowed(rel):
                    unscanned.append(rel)
                continue
            blob_lower = blob.lower()
            hit = next((tok for tok, low in lowered if low in blob_lower), None)
            if hit is not None:
                token_viols.append({
                    "category": "personal_token",
                    "where": "binary-content",
                    "path": rel,
                    "line": None,
                    "token": hit,
                    "text": f"(inside {suffix} text/metadata)",
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
            continue

        lines = _read_text(root / rel)
        if lines is None:
            continue
        token_found = False
        seen_kinds = set()
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
    return token_viols, pii_viols, unscanned


def scan(root: Path = REPO_ROOT, tracked: list[str] | None = None,
         tokens: list[str] | None = None) -> dict:
    """Run every check and return a structured result.

    ``root`` may be a git work tree (default: this repo) or any plain directory
    tree (used by the tests / an export scratch). ``tracked`` / ``tokens`` can be
    supplied to make a scan fully deterministic (the tests do this).
    """
    root = Path(root).resolve()
    if tracked is None:
        tracked = _list_files(root)
    if tokens is None:
        tokens = personal_tokens()

    private_skill = find_private_skill_violations(root, tracked)
    overlay = find_personal_overlay_violations(tracked)
    references_private = find_references_private_violations(tracked)
    path_denylist = find_path_denylist_violations(tracked)
    token_viols, pii_viols, unscanned = find_token_and_pii_violations(root, tracked, tokens)

    violations = {
        "private_skill_tracked": private_skill,
        "personal_overlay": overlay,
        "references_private": references_private,
        "path_denylist": path_denylist,
        "structural_pii": pii_viols,
        "personal_token": token_viols,
        "unscanned_binary": [{"category": "unscanned_binary", "path": r} for r in unscanned],
    }
    total = sum(len(v) for v in violations.values())
    return {
        "repo_root": str(root),
        "tracked_file_count": len(tracked),
        "personal_token_count": len(tokens),
        "unscanned_binaries": unscanned,
        "ok": total == 0,
        "total_violations": total,
        "violations": violations,
    }


def print_report(result: dict) -> None:
    """Print a human-readable report of the scan result."""
    v = result["violations"]

    private_skill = v["private_skill_tracked"]
    overlay = v["personal_overlay"]
    references_private = v["references_private"]
    path_denylist = v["path_denylist"]
    structural = v["structural_pii"]
    tokens = v["personal_token"]
    unscanned = result.get("unscanned_binaries") or []

    print("Public-repo leak guard")
    print(f"  repo root:      {result['repo_root']}")
    print(f"  tracked files:  {result['tracked_file_count']}")
    print(f"  active tokens:  {result.get('personal_token_count', 0)}")
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

    if references_private:
        print(f"[3] Tracked files under a per-skill '{REFERENCES_PRIVATE_DIRNAME}/' "
              f"folder ({len(references_private)}):")
        for item in references_private:
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
        for rel in unscanned:
            print(f"  - {rel}")
        print()


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
    args = parser.parse_args(argv)

    result = scan()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_report(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
