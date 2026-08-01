"""gardener routine: verify referenced paths, skill symlinks, and vendor drift.

EVERY TRACKED ``.md`` in the repo — and in the private overlay when it is mounted —
references paths, in two forms this routine reads as one universe:

  * **backticked tokens** (`` `automation/x.py` ``), prose shorthand. They resolve
    against several bases (repo root, the file's own directory, and, under
    ``skills/``, the skill root) because a backtick is a name, not a hyperlink.
  * **markdown links** (``[text](path)``, ``![alt](img)``, ``[t][label]`` +
    ``[label]: path``). These resolve against **the containing file's directory
    only** — that is what a reader clicks, and anything else would pass a link that
    404s on GitHub. The same string can therefore be fine in backticks and broken as
    a link; that is deliberate, and the failure message says so.

Code is never a reference: fenced blocks and inline code spans are masked first, and
a code span MAY span two lines (``docs/handbook/doc-style.md`` has two), so the mask
runs over the whole document rather than line by line. Destinations that are
placeholders (``[x](<relative path>)``), external URLs, or under a runtime/data tree
are counted, never resolved.

**A break's fate is decided by what its SOURCE document is for, never by its target:**

  * **reference** — states where something is NOW (``AGENTS.md``, the READMEs,
    ``docs/handbook/``, ``docs/roadmap/current-state.md``, ``templates/``,
    ``skills/``, ``examples/``, ``evals/`` protocols, ``memory/{facts,lessons,
    known-issues}``). A break is a FAILURE to repair. This is the default: a
    directory nobody has classified fails closed.
  * **plan** — names paths that are supposed not to exist yet (``docs/designs/``,
    a task in a live status folder, ``message-queue/``,
    ``docs/roadmap/desired-state.md``). ADVISORY.
  * **record** — dated testimony whose rewriting would falsify it (``history/``,
    ``memory/decisions/`` (ADRs are immutable by contract), ``evals/results/``,
    ``tasks/4_done/``). PERMITTED: counted and listed every run, never repaired,
    never fatal. The one thing a permitted break may not do is vanish from the report.

Every skipped class is COUNTED, never silently dropped — including the one that used
to have no counter at all: a backticked token whose first segment is not a recognised
root ("unrecognised-root"). Renaming a root moves references into that bucket one at a
time, so the bucket is compared against a baseline rather than thresholded.

A root THIS repo renamed is the one thing that bucket got wrong. ``design/`` and
``handbook/`` are not prose shorthand — they are former roots of this repo — and 83
references to four of them sat unread, because ``--compare`` (the bucket's only
detector) is wired into no gate. ``RETIRED_ROOTS`` names them, so a retired root
FOLLOWED BY A PATH is tiered as the broken pointer it is and prints where the target
moved. A BARE retired root stays in the bucket: it is normally the subject of a
sentence about the rename ("``handbook/`` became ``docs/handbook/``"), and failing it
would force a maintainer to falsify a true sentence.

Also checked: heading anchors (``#section``) with GitHub's slug rules; the Codex,
Claude Code, and Cursor compatibility symlinks resolve — and that there was
something to resolve; and vendored copies are in sync.

**The summary never says "all resolve".** It reports how many references were
VERIFIED against this tree next to how many were not, because the old line was a
clean bill of health issued over everything the skip buckets had swallowed. And
verifying NOTHING is a finding rather than a pass — the same rule
``check_symlinks`` already applies to the compatibility symlink roots.

Exit 1 on any broken reference / unresolved symlink / vendor drift / zero
coverage; else 0. Report-only otherwise (it fixes nothing).

Usage:
    .venv/bin/python automation/gardener/verify_links.py
    .venv/bin/python automation/gardener/verify_links.py --require-roots
    .venv/bin/python automation/gardener/verify_links.py --list-unrecognised
    .venv/bin/python automation/gardener/verify_links.py --baseline local/links.json
    .venv/bin/python automation/gardener/verify_links.py --compare  local/links.json

WARNING: with the overlay mounted this report names ``private/`` paths. It is not a
tracked file, so the leak guard never sees it — never paste a run into a public PR
description or commit message.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

BACKTICK_RE = re.compile(r"`([^`]+)`")

# Repo-root-anchored TOOLKIT prefixes: a backticked path starting with one of these
# MUST exist from the repo root. A break here (e.g. AGENTS.md naming a renamed
# script) is genuine. Bare relative fragments (`scripts/x.py`, `source/…`,
# `profiles/…`, `_vendor/…`) are NOT in this set — they resolve against a skill base
# (below) or are documented optional/ephemeral references, and never hard-fail.
#
# A prefix is strict ONLY IN A TREE THAT HAS THAT ROOT (``_present_strict_prefixes``).
# The published export ships none of message-queue/, tasks/, memory/, docs/roadmap/,
# history/ while AGENTS.md and the handbook necessarily name them, so making them
# strict everywhere would turn the PUBLISHED repo's gardener red — the same trap
# the reconciler's documented missing-root no-op exists to avoid. In the maintainer
# checkout every root is present, so every one of those refs IS verified.
STRICT_ROOT_PREFIXES = (
    "skills/", "automation/", ".claude-plugin/", "examples/",
    "docs/handbook/", "docs/designs/", "docs/roadmap/", "evals/", "templates/",
    "memory/", "tasks/", "message-queue/", "history/",
)
# Runtime data / scratch trees — never verified (illustrative or absent in a public
# checkout). The overlay's DATA/product trees are illustrative too, so their
# ``private/`` forms are skipped exactly like the bare ones. ``private/`` is NOT
# blanket-skipped: genuine overlay TOOLKIT paths fall through to OVERLAY_PREFIX and
# are verified whenever the overlay is mounted (otherwise counted "overlay").
# ``interviews/`` and ``job-search/`` are gone: workspace phase 5 dissolved both
# into ``companies/``, ``me/interviews/`` and ``market/``, and none of those is
# skipped. So every link inside what used to be the interview tree is now VERIFIED
# whenever the overlay is mounted — which is the whole point of removing them, and
# it means the overlay's docs have to be right the first time rather than the
# second. ``applications/`` and ``local/`` stay: they are runtime data and scratch.
SKIP_PREFIXES = ("applications/", "local/",
                 ".agents/inputs/", ".git/", ".venv/",
                 "private/applications/", "private/local/")
SKILLS_ROOT = "skills"

# Backticked refs into the private overlay (maintainer-only design docs, real
# products). Present only when the overlay is mounted at ``private/``.
OVERLAY_PREFIX = "private/"

# --- Retired roots --------------------------------------------------------------
# Directories THIS repo used to have at the path on the left, renamed by the commit
# on the right without every inbound reference following. Each was read out of
# ``git log --diff-filter=D``, so they are recorded facts rather than guesses.
#
# Why they need naming at all: the tier machinery keys on STRICT_ROOT_PREFIXES, so a
# token under a root that no longer exists matches no prefix and falls into
# "unrecognised-root" — the 792-entry bucket of branch names, Graph endpoints and
# skill-relative shorthand that nobody reads. That is exactly the hole this module's
# own docstring predicted ("renaming a root migrates references here one at a time,
# silently"), and the mitigation it shipped — a counter plus ``--compare`` against a
# baseline — never fired, because nothing in pre-commit or CI passes ``--compare``.
# 83 references across these four roots accumulated unseen.
#
# Adding them to STRICT_ROOT_PREFIXES instead does NOT work: ``_present_strict_prefixes``
# drops any prefix whose directory is absent, so they would land in "absent-root" —
# equally silent — and ``--require-roots`` would then fail on all four by design.
#
# This is deliberately a DENYLIST of four, not the allowlist of ~600 innocent tokens
# that ``test_a_branch_name_is_counted_not_broken`` rightly refuses to grow. It is
# bounded (one entry per root rename, ever), and ``check_required_roots`` asserts each
# key is still ABSENT, so a resurrected root is loud rather than quietly wrong.
RETIRED_ROOTS = {
    "design/": "docs/designs/",                 # 422377d
    "handbook/": "docs/handbook/",              # 422377d
    "roadmap/": "docs/roadmap/",                # 422377d
    "automation/maintenance/": "automation/",   # 031e05d
}


def _retired_root(token: str) -> str | None:
    """The retired root ``token`` names or sits under, or None. Longest match wins."""
    t = token.rstrip("/")
    return max((r for r in RETIRED_ROOTS
                if t == r.rstrip("/") or token.startswith(r)),
               key=len, default=None)


def _retired_successor(token: str) -> str | None:
    """Where ``token`` moved to, or None when it names no retired root."""
    r = _retired_root(token)
    return None if r is None else RETIRED_ROOTS[r] + token[len(r):]


# --- The three tiers ------------------------------------------------------------
# Dated testimony. The text records what was true when it was written; rewriting it
# would falsify the record. Counted, listed, NEVER fatal, never repaired.
RECORD_SOURCES = (
    "history/", "memory/decisions/", "evals/results/", "tasks/4_done/",
)
# Record trees that exist ONLY inside the overlay. A versioned fixture manifest is
# testimony too — it records what a frozen fixture set contained and why, on a date,
# and one live manifest names a directory three times in the sentences explaining
# that it deliberately does not exist.
#
# Separate from RECORD_SOURCES because ``--require-roots`` asserts that every prefix
# it is given names a real directory, and an overlay-only prefix is absent by
# construction whenever the overlay is not being read. Folding these into the main
# tuple made the flag report a false MISSING ROOT on any branch run with
# ``--no-overlay``, which is exactly how the pre-commit hook runs.
OVERLAY_RECORD_SOURCES = ("benchmark/fixtures/", "evals/fixtures/")
# Proposals. They name targets on purpose ("create `automation/publish/x.py`" is a
# plan, and requiring it to exist inverts the doc's meaning). Advisory.
#
# The five task status folders are enumerated rather than covered by a bare
# ``tasks/`` prefix so that a status folder nobody has taught this checker about
# defaults to REFERENCE and fails closed.
#
# ``message-queue/`` gets the same treatment, and for the same reason: it used to sit
# here as one blanket prefix, which made EVERY queue item advisory. But the five
# queues do not do the same job, and only three of them are proposals.
#
#   * ``decisions/`` and ``clarifications/`` ask the owner about work not yet done, and
#     ``requests/`` is the owner's free-form "please build X" drop box. Naming a path
#     that does not exist is the POINT of all three — requiring it inverts the meaning,
#     exactly as with ``docs/designs/``. They stay PLAN.
#   * ``reviews/`` and ``retries/`` point AT work that already exists — a review item
#     asks a human to look at a real artifact, and a retry is the reconciler naming a
#     real file that failed a check. A dead link in either is a rotted pointer in a
#     LIVE working document, not a proposal, so both fall through to REFERENCE and fail
#     closed. That is not a hypothetical: the one live review item linked twice at
#     ``migration.md``, a file that never existed under any name, and pointed at a task
#     that had since moved to ``tasks/4_done/``. Advisory hid all three for weeks.
#
# Note the deliberate second effect: ``message-queue/README.md`` is no longer swept
# into the plan tier either. It is a README — it states where things are NOW — so it
# belongs in reference like every other README in the repo.
#
# None of these folders is archival. Every queue item is deleted when it resolves
# (AGENTS.md: fold a decision then delete it; delete a request in the same commit;
# sweep reviews at 30 days), so "live vs archival" is not the axis that separates them
# — "proposal vs pointer" is, and that is what the plan tier was always defined on.
#
# ``memory/known-issues/`` is here rather than in the reference tier, which is where
# the other memory zones sit, and the reason is structural: a known-issue's JOB is to
# name the gap between the tree and what should be there, so at least one path in it
# is expected not to resolve. Two live entries name a benchmark directory in the
# sentence that says it does not exist. Their unresolved refs are still printed —
# advisory is not silence — and a genuinely stale path in one still shows up with its
# "did you mean" suggestion. It just does not fail a gate for saying something true.
PLAN_SOURCES = (
    "docs/designs/", "docs/roadmap/desired-state.md",
    "tasks/0_backlog/", "tasks/1_in-progress/", "tasks/2_blocked/",
    "tasks/3_in-review/", "memory/known-issues/",
    "message-queue/needs-human/decisions/",
    "message-queue/needs-human/clarifications/",
    "message-queue/needs-agent/requests/",
)
# Everything else asserts CURRENT state and fails hard. There is no list for it:
# the default IS the strict case.

# Destinations that are instructions to a human, not paths. ``templates/`` is full
# of them (``[<descriptive source>](<relative path to …>)``); ``_is_checkable``
# already rejects the same shapes for backticks.
_PLACEHOLDER_CHARS = "<>{}*|?$… \t"
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "ftp://", "data:",
                     "//")
_FILEY_SUFFIXES = (".md", ".py", ".yaml", ".yml", ".json", ".jsonl", ".txt",
                   ".docx", ".pdf", ".html", ".sh", ".toml", ".cfg", ".mdc")


# --- Masking --------------------------------------------------------------------
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
# CommonMark code span: a run of N backticks closes on the next run of N, and the
# span may contain a newline. DOTALL is required — a per-line strip misses the two
# wrapped spans in docs/handbook/doc-style.md and reports the illustrative links
# inside them as broken, in a hard-fail tier.
_SPAN_RE = re.compile(r"(?P<f>`+).*?(?P=f)", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _blank(match: re.Match) -> str:
    """Replace a match with spaces, keeping every newline so lines still line up."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _mask_fences(text: str) -> str:
    """Blank fenced code blocks and HTML comments, preserving line numbering.

    CommonMark's OTHER code block — four leading spaces — is deliberately NOT masked.
    Recognising it correctly needs list-context tracking, because an indented
    continuation line inside a list is not a code block, and this repo's docs are
    full of those. A heuristic that over-masks would stop reading real links and
    fail OPEN, which is strictly worse than the false positive it prevents. There
    are none in the tree today; ``test_link_inside_an_indented_code_block_is_not_a_link``
    is marked expectedFailure so that adding one is loud rather than silent.
    """
    out, fence = [], None
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)[:3]
            out.append("")
            continue
        if fence is not None:
            if m and m.group(1).startswith(fence):
                fence = None
            out.append("")
            continue
        out.append(line)
    return _HTML_COMMENT_RE.sub(_blank, "\n".join(out))


def _mask_code(text: str) -> str:
    """Fences, HTML comments AND inline code spans — the link-extraction view."""
    return _SPAN_RE.sub(_blank, _mask_fences(text))


# --- Markdown links -------------------------------------------------------------
# [text](dest "title") / ![alt](dest) / <dest>. Dest may not contain whitespace or
# parens unless angle-bracketed, which is CommonMark's own restriction.
_LINK_RE = re.compile(
    r"(?P<img>!)?(?<!\\)\[(?P<text>[^\]]*)\]\(\s*"
    r"(?P<dest><[^>]*>|[^()\s]*)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
# [text][label] — a reference-style use. Collapsed ([text][]) uses text as label.
_REFUSE_RE = re.compile(r"(?<!\\)\[(?P<text>[^\]]*)\]\[(?P<label>[^\]]*)\]")
# [label]: dest "title" — a definition, at the start of a line.
_REFDEF_RE = re.compile(r"^\s{0,3}\[(?P<label>[^\]]+)\]:\s*(?P<dest><[^>]*>|\S+)",
                        re.MULTILINE)
_HTML_ATTR_RE = re.compile(r"<(?:a[^>]+href|img[^>]+src)=[\"'](?P<dest>[^\"']+)[\"']",
                           re.IGNORECASE)


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _unwrap(dest: str) -> str:
    dest = dest.strip()
    if dest.startswith("<") and dest.endswith(">") and len(dest) >= 2:
        dest = dest[1:-1].strip()
    return dest


def _iter_links(masked: str):
    """Yield ``(lineno, kind, dest)`` for every link-ish destination in ``masked``."""
    defs: dict[str, tuple[int, str]] = {}
    for m in _REFDEF_RE.finditer(masked):
        defs[m.group("label").strip().lower()] = (_lineno(masked, m.start()),
                                                  _unwrap(m.group("dest")))
    for m in _LINK_RE.finditer(masked):
        yield (_lineno(masked, m.start()),
               "image" if m.group("img") else "inline",
               _unwrap(m.group("dest")))
    for m in _REFUSE_RE.finditer(masked):
        label = (m.group("label").strip() or m.group("text").strip()).lower()
        if label in defs:
            lineno, dest = defs[label]
            yield lineno, "reference", dest          # reported at the DEFINITION
        # An UNDEFINED label is not a broken link — CommonMark says `[a][b]` with no
        # `[b]:` definition renders as literal text. Reporting it looks principled
        # and is wrong: `dp[i][j]` in algorithm notes matches this shape, and doing
        # so produced 31 phantom findings inside the overlay's coding notes alone —
        # dead centre in the tree phase 5 has to prove clean.
    for m in _HTML_ATTR_RE.finditer(masked):
        yield _lineno(masked, m.start()), "html", _unwrap(m.group("dest"))


# --- Heading anchors ------------------------------------------------------------
_HEADING_RE = re.compile(
    r"^[ \t]{0,3}(#{1,6})[ \t]+(?P<text>.+?)[ \t]*#*[ \t]*$",
    re.MULTILINE,
)
_EXPLICIT_ANCHOR_RE = re.compile(r"<a[^>]+\bid=[\"'](?P<id>[^\"']+)[\"']",
                                 re.IGNORECASE)
_SPAN_TEXT_RE = re.compile(r"`+([^`]*)`+")
_LINKTEXT_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]+>")


def _slug(text: str) -> str:
    """GitHub's heading slug.

    Each whitespace CHARACTER becomes one hyphen — runs are NOT collapsed. That is
    why ``## Merged: phase 2 — public-side cleanup`` is
    ``merged-phase-2--public-side-cleanup``: dropping the em dash leaves two spaces.
    A ``re.sub(r"\\s+", "-")`` reports healthy links as broken.
    """
    text = _LINKTEXT_RE.sub(r"\1", text)
    text = _SPAN_TEXT_RE.sub(r"\1", text)
    text = _TAG_RE.sub("", text)
    text = text.replace("*", "").replace("_", "").replace("~", "")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"[ \t]", "-", text)


def _anchors(text: str) -> set[str]:
    """Every fragment a reader can target in this document.

    Headings are read from text with FENCES masked but code spans INTACT — masking
    spans blanks the backticks inside a heading and silently changes its slug.
    """
    fenced_only = _mask_fences(text)
    seen: dict[str, int] = {}
    out: set[str] = set()
    for m in _HEADING_RE.finditer(fenced_only):
        base = _slug(m.group("text"))
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    out.update(m.group("id") for m in _EXPLICIT_ANCHOR_RE.finditer(fenced_only))
    return out


# --- Source enumeration ---------------------------------------------------------
_NO_OVERLAY = False   # set by --no-overlay; reproduces a contributor checkout


def _overlay_root() -> Path | None:
    """The mounted overlay's root, or None (a contributor checkout has none)."""
    if _NO_OVERLAY:
        return None
    p = C.REPO_ROOT / "private"
    return p if (p / ".git").exists() else None


def _overlay_mounted() -> bool:
    """Whether overlay TARGETS can be resolved at all.

    Must honour ``--no-overlay`` too, or the flag reproduces neither CI nor a
    contributor checkout: it would stop READING overlay files while still claiming
    their targets are resolvable, and the two ``evals/`` docs that link into
    ``private/docs/`` would report as broken instead of skipped.
    """
    return not _NO_OVERLAY and (C.REPO_ROOT / "private").is_dir()


def _git_md(root: Path) -> list[str] | None:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "*.md"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.split("\0") if p]


def _git_all(root: Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                       capture_output=True, text=True)
    return [] if r.returncode != 0 else [p for p in r.stdout.split("\0") if p]


_FALLBACK_SKIP_DIRS = {".git", ".venv", "node_modules", "private", "local",
                       "applications", "interviews", "__pycache__"}


def _instruction_files() -> list[Path]:
    """Every TRACKED ``.md`` in the repo, plus the overlay's when it is mounted.

    ``git ls-files`` (not ``rglob``) defines the public set: it is exactly the
    publishable surface and it excludes the ignored trees (``private/``, ``local/``,
    ``.venv/``) for free. The overlay is a SEPARATE git repository, so its files are
    invisible to that command — they need their own ``git -C private ls-files``, and
    without it no link INSIDE the overlay has ever been read by this routine. The
    rglob fallback keeps the routine usable in an exported tarball.
    """
    names = _git_md(C.REPO_ROOT)
    if names is None:  # not a git checkout (exported tree): walk, minus data trees
        files = [p for p in C.REPO_ROOT.rglob("*.md")
                 if not (_FALLBACK_SKIP_DIRS & set(
                     p.relative_to(C.REPO_ROOT).parts[:-1]))]
        return sorted(f for f in files if f.is_file() and not f.is_symlink())
    files = [C.REPO_ROOT / p for p in names]
    overlay = _overlay_root()
    if overlay is not None:
        files += [overlay / p for p in (_git_md(overlay) or [])]
    return sorted(f for f in files if f.is_file() and not f.is_symlink())


def _rel(f: Path) -> str:
    """Repo-root-relative posix path, WITHOUT resolving symlinks.

    ``C.rel()`` resolves, which would rewrite an overlay path through whatever the
    ``private`` entry points at and lose the ``private/`` prefix the tier logic keys
    on.
    """
    try:
        return f.relative_to(C.REPO_ROOT).as_posix()
    except ValueError:
        return f.as_posix()


def _exists_case_exact(p: Path) -> bool:
    """``p.exists()``, but case-exact on a case-insensitive filesystem.

    The tracked set is the primary answer (see ``_tracked_set``). This is the
    fallback for a file that exists but is not staged yet — writing a document and
    linking a sibling you have not ``git add``ed is ordinary, and reporting it broken
    would train people to ignore the gate. ``Path.exists()`` alone will not do:
    macOS resolves ``architecture.md`` to ``ARCHITECTURE.md`` and this repo has
    already shipped a link that passed locally and failed on Linux CI. So each
    component is matched verbatim against its parent's listing.
    """
    try:
        rel = p.relative_to(C.REPO_ROOT) if p.is_absolute() else p
    except ValueError:
        return False
    cur = C.REPO_ROOT
    for part in rel.parts:
        try:
            if part not in {e.name for e in cur.iterdir()}:
                return False
        except (OSError, NotADirectoryError):
            return False
        cur = cur / part
    return True


def _tracked_set() -> tuple[set[str], set[str]]:
    """(public, overlay) tracked paths — files plus every directory they imply.

    Membership here, not ``Path.exists()``, is what "resolves" means. macOS is
    case-insensitive, so ``exists()`` accepts ``../ARCHITECTURE.md`` for
    ``architecture.md`` locally and fails on Linux CI — this repo has shipped that
    break once. The tracked set is case-exact and already computed.
    """
    def expand(names: list[str]) -> set[str]:
        out: set[str] = set()
        for n in names:
            out.add(n)
            parts = n.split("/")
            for i in range(1, len(parts)):
                out.add("/".join(parts[:i]))
        return out

    pub = expand(_git_all(C.REPO_ROOT))
    overlay = _overlay_root()
    ovl = expand(_git_all(overlay)) if overlay is not None else set()
    return pub, ovl


# --- Tiering --------------------------------------------------------------------
def _tier(rel: str) -> str:
    """record | plan | reference, from what the SOURCE document is for."""
    if rel.startswith(OVERLAY_PREFIX):        # the overlay mirrors the same layout
        rel = rel[len(OVERLAY_PREFIX):]
    if rel.startswith(RECORD_SOURCES) or rel.startswith(OVERLAY_RECORD_SOURCES):
        return "record"
    if rel.startswith(PLAN_SOURCES):
        return "plan"
    return "reference"


def _is_checkable(token: str) -> bool:
    """True for a concrete-looking repo path (not a placeholder / expression)."""
    if "/" not in token:
        return False
    if any(c in token for c in "<>(){}*|?`$ \t…"):
        return False
    if "config." in token or "layout." in token or "check." in token:
        return False
    # ``references_private/`` lives in the private overlay, is per-user and
    # optional by contract (the leak guard FAILS on any tracked file under it),
    # so a doc naming one — always as an example of the pattern — is not
    # asserting that it exists.
    if "references_private" in token:
        return False
    if not re.fullmatch(r"[A-Za-z0-9._/\-]+", token.rstrip("/")):
        return False
    if token.startswith(SKIP_PREFIXES):
        return False
    return True


def _bases_for(f: Path) -> list[Path]:
    """Resolution bases for BACKTICKED references inside file ``f``.

    Always the repo root and the file's own directory. When ``f`` lives under a
    skill, also the skill root, its ``scripts/`` subdir, and the skills root — so
    skill-relative refs (`scripts/x.py`, `_vendor/y.py`, `sibling-skill/…`) resolve.
    Markdown links deliberately do NOT get this list: see the module docstring.
    """
    bases = [C.REPO_ROOT, f.parent]
    try:
        parts = f.resolve().relative_to(C.REPO_ROOT).parts
    except ValueError:
        return bases
    if len(parts) >= 2 and parts[0] == "skills":
        skill_root = C.REPO_ROOT / parts[0] / parts[1]
        bases += [skill_root, skill_root / "scripts", C.REPO_ROOT / SKILLS_ROOT]
    return bases


def _resolves(token: str, bases: list[Path]) -> bool:
    rel = token.rstrip("/")
    return any((base / rel).exists() for base in bases)  # exists() follows symlinks


def _present_strict_prefixes() -> tuple[str, ...]:
    """The STRICT_ROOT_PREFIXES whose root actually exists in THIS checkout."""
    return tuple(p for p in STRICT_ROOT_PREFIXES
                 if (C.REPO_ROOT / p.rstrip("/")).exists())


def _git_ignored(tokens: list[str]) -> set[str]:
    """Which tokens git ignores. Empty when this is not a git checkout."""
    if not tokens:
        return set()
    r = subprocess.run(
        ["git", "-C", str(C.REPO_ROOT), "check-ignore", "--no-index", "--stdin"],
        input="\n".join(tokens), capture_output=True, text=True)
    if r.returncode not in (0, 1):  # 128 = not a git checkout / bad usage
        return set()
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


# --- Successor suggestion -------------------------------------------------------
def _suggest(target: str, tracked: set[str], renames: dict[str, str]) -> str | None:
    """"did you mean X?" — never used to resolve, only printed.

    Suggesting a successor is useful; RESOLVING through one is not. A reader
    clicking the link still gets a 404, and a gate that goes green because a
    different file claims to replace the target is asserting something false about
    the document under test.
    """
    if target in renames:
        return renames[target]
    base = posixpath.basename(target)
    if not base:
        return None
    same = [p for p in tracked if posixpath.basename(p) == base and p != target]
    if len(same) == 1:
        return same[0]
    tail = [p for p in tracked if p.endswith("/" + target)]
    if len(tail) == 1:
        return tail[0]
    return None


# --- The check ------------------------------------------------------------------
VERIFIED_KEY = "verified"


def _new_skipped() -> dict[str, int]:
    """Every counter the reference pass keeps.

    All keys but ``verified`` are SKIP classes and have a label in
    ``_SKIP_LABELS``. ``verified`` is the opposite number — how many references
    were actually resolved against this tree — and it exists because without it a
    run over zero refs is indistinguishable from a run where every ref resolved.
    Both used to print "references: all resolve".
    """
    return {"overlay": 0, "absent-root": 0, "git-ignored": 0,
            "unrecognised-root": 0, "external": 0, "placeholder": 0,
            "skip-tree": 0, "anchor-only": 0, VERIFIED_KEY: 0}


def check_references(check_anchors: bool = True):
    """Return ``(broken, advisory, permitted, skipped, unrecognised)``.

    ``broken`` fails the gate; ``advisory`` and ``permitted`` never do. Which bucket
    a finding lands in is decided ONLY by its source document's tier.
    """
    broken: list[dict] = []
    advisory: list[dict] = []
    permitted: list[dict] = []
    unrecognised: list[dict] = []
    skipped = _new_skipped()

    overlay_mounted = _overlay_mounted()
    strict = _present_strict_prefixes()
    absent = tuple(p for p in STRICT_ROOT_PREFIXES if p not in strict)
    tracked_pub, tracked_ovl = _tracked_set()
    files = _instruction_files()
    anchors_by_rel: dict[str, set[str]] = {}
    texts: dict[str, str] = {}

    def sink_for(tier: str) -> list[dict]:
        return {"record": permitted, "plan": advisory}.get(tier, broken)

    def target_resolves(norm: str) -> bool | None:
        """True/False, or None when the target is not resolvable in this checkout."""
        if norm.startswith(SKIP_PREFIXES):
            skipped["skip-tree"] += 1
            return None
        if norm.startswith(OVERLAY_PREFIX):
            if not overlay_mounted:
                skipped["overlay"] += 1
                return None
            rel = norm[len(OVERLAY_PREFIX):]
            overlay = _overlay_root()
            return rel in tracked_ovl or (overlay is not None
                                          and _exists_case_exact(overlay / rel))
        return norm in tracked_pub or _exists_case_exact(C.REPO_ROOT / norm)

    # Pass 1 — read every file once, keep its text and its anchor set.
    for f in files:
        rel = _rel(f)
        try:
            texts[rel] = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if check_anchors:
            anchors_by_rel[rel] = _anchors(texts[rel])

    # Pass 2 — backticked tokens (unchanged semantics, plus the missing tally).
    candidates: list[tuple[list[dict], dict]] = []
    for f in files:
        rel = _rel(f)
        if rel not in texts:
            continue
        bases = _bases_for(f)
        sink = sink_for(_tier(rel))
        seen: set[str] = set()
        for lineno, line in enumerate(texts[rel].splitlines(), 1):
            for token in BACKTICK_RE.findall(line):
                token = token.strip()
                if token in seen or not _is_checkable(token):
                    continue
                seen.add(token)
                hit = {"file": rel, "line": lineno, "ref": token, "kind": "backtick",
                       "tier": _tier(rel), "target": token}
                if token.startswith(OVERLAY_PREFIX):
                    if not overlay_mounted:
                        skipped["overlay"] += 1
                    else:
                        skipped[VERIFIED_KEY] += 1
                        if not _resolves(token, bases):
                            sink.append(hit)
                    continue
                if _resolves(token, bases):
                    skipped[VERIFIED_KEY] += 1
                    continue
                retired = _retired_root(token)
                if retired is not None and token.rstrip("/") != retired.rstrip("/"):
                    # A retired root WITH a path under it is a POINTER that a rename
                    # broke, so it is tiered like any other reference: permitted in a
                    # record, advisory in a plan, FATAL in a document that claims to
                    # state where things are now. Nothing in the tree is fatal today —
                    # this gates the NEXT stale handbook link, it does not punish the
                    # backlog.
                    #
                    # A BARE retired root (`handbook/`, `design/`) deliberately does
                    # NOT come here. It is almost always the SUBJECT of a sentence
                    # about the rename itself — current-state.md's "top-level
                    # `handbook/` + `design/` became `docs/{handbook,designs}`" is
                    # reference-tier and TRUE, and failing it would force a maintainer
                    # to falsify the sentence or disable the check. It keeps its
                    # existing unrecognised-root counter.
                    skipped[VERIFIED_KEY] += 1
                    sink.append({**hit, "successor": _retired_successor(token),
                                 "why": f"{retired} was renamed to "
                                        f"{RETIRED_ROOTS[retired]}"})
                elif token.startswith(absent):
                    skipped["absent-root"] += 1
                elif token.startswith(strict):
                    candidates.append((sink, hit))
                else:
                    # THE HOLE THIS ROUTINE USED TO HAVE: neither strict nor absent,
                    # so the loop fell through and no counter moved. Renaming a root
                    # migrates references here one at a time, silently. Not fatal —
                    # most of these are prose shorthand, branch names or API paths —
                    # but never invisible again.
                    skipped["unrecognised-root"] += 1
                    unrecognised.append(
                        {**hit,
                         "names_a_file": token.endswith(_FILEY_SUFFIXES)})

    ignored = _git_ignored(sorted({h["ref"].rstrip("/") for _, h in candidates}))
    for sink, hit in candidates:
        if hit["ref"].rstrip("/") in ignored:
            skipped["git-ignored"] += 1
        else:
            skipped[VERIFIED_KEY] += 1
            sink.append(hit)

    # Pass 3 — markdown links, images, reference links, HTML attributes, anchors.
    for f in files:
        rel = _rel(f)
        if rel not in texts:
            continue
        tier = _tier(rel)
        sink = sink_for(tier)
        masked = _mask_code(texts[rel])
        srcdir = posixpath.dirname(rel)
        for lineno, kind, dest in _iter_links(masked):
            hit = {"file": rel, "line": lineno, "kind": kind, "tier": tier}
            if not dest:
                continue
            if dest.lower().startswith(_EXTERNAL_SCHEMES):
                skipped["external"] += 1
                continue
            if any(c in dest for c in _PLACEHOLDER_CHARS):
                skipped["placeholder"] += 1
                continue
            path_part, _, frag = dest.partition("#")
            path_part = urllib.parse.unquote(path_part.split("?", 1)[0])
            if not path_part:                                   # bare "#anchor"
                skipped["anchor-only"] += 1
                if check_anchors and frag and frag not in anchors_by_rel.get(rel, ()):
                    sink.append({**hit, "kind": "anchor", "ref": dest, "target": rel,
                                 "why": "no heading with that slug in this file"})
                continue
            if path_part.startswith("/"):
                norm = posixpath.normpath(path_part.lstrip("/"))
            else:
                norm = posixpath.normpath(posixpath.join(srcdir, path_part))
            if norm.startswith(".."):
                skipped[VERIFIED_KEY] += 1
                sink.append({**hit, "ref": dest, "target": norm,
                             "why": "escapes the repository root"})
                continue
            ok = target_resolves(norm)
            if ok is None:
                continue
            skipped[VERIFIED_KEY] += 1
            if not ok:
                sink.append({**hit, "ref": dest, "target": norm,
                             "why": "markdown links resolve against their own "
                                    "directory only"})
                continue
            if check_anchors and frag and norm in anchors_by_rel:
                if frag not in anchors_by_rel[norm]:
                    sink.append({**hit, "kind": "anchor", "ref": dest, "target": norm,
                                 "why": "no heading with that slug in the target"})

    return broken, advisory, permitted, skipped, unrecognised


# Editor compatibility trees carrying the ``skills/*`` symlinks. At least one must
# exist: finding none used to mean "all resolve".
SYMLINK_ROOTS = (".agents/skills", ".claude/skills", ".cursor/skills")


def _tracked_symlink_roots() -> set[str] | None:
    """Which SYMLINK_ROOTS git tracks, or None when this is not a git checkout."""
    r = subprocess.run(["git", "-C", str(C.REPO_ROOT), "ls-files", "-z",
                        *SYMLINK_ROOTS], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    tracked = set()
    for path in r.stdout.split("\0"):
        for root in SYMLINK_ROOTS:
            if path.startswith(root + "/"):
                tracked.add(root)
    return tracked


def check_symlinks() -> list[dict]:
    """Unresolved skill compat symlinks — and a FINDING when nothing was verified.

    Was fail-open in three ways, all of which reported "skill symlinks: all
    resolve" after checking nothing: all roots absent (a restructure renames or
    drops them), a root present but empty, and a root tracked in git yet missing
    from the working tree. Each is now its own finding.
    """
    bad: list[dict] = []
    present = {r: C.REPO_ROOT / r for r in SYMLINK_ROOTS
               if (C.REPO_ROOT / r).is_dir()}
    tracked = _tracked_symlink_roots()

    if tracked is not None:
        for root in sorted(tracked - set(present)):
            bad.append({"link": root,
                        "target": "TRACKED in git but absent from the working tree"})
    if not present:
        bad.append({"link": " / ".join(SYMLINK_ROOTS),
                    "target": "NO skill link root exists — nothing was verified"})

    for root, skdir in sorted(present.items()):
        links = [p for p in sorted(skdir.iterdir()) if p.is_symlink()]
        if not links:
            bad.append({"link": root, "target": "contains no skill symlinks — "
                                                "nothing was verified"})
        for link in links:
            if not link.resolve().exists():
                # NOT C.rel(): it resolve()s, which would name the missing TARGET
                # instead of the broken link the reader has to repair.
                bad.append({"link": link.relative_to(C.REPO_ROOT).as_posix(),
                            "target": str(link.readlink())})
    return bad


def check_vendor() -> tuple[int, str]:
    script = C.REPO_ROOT / "automation" / "vendoring" / "sync_vendored.py"
    if not script.is_file():
        return 0, "sync_vendored.py not found (skipped)"
    r = subprocess.run([sys.executable, str(script), "--check"],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


# --- Root assertion -------------------------------------------------------------
def check_required_roots() -> list[str]:
    """Every prefix this module keys on must name something that exists.

    Renaming a root that a checker names in a constant DISARMS the checker instead
    of breaking it — ``_present_strict_prefixes`` no-ops on a missing root by design,
    and the tier lists simply stop matching. Phase 2 renamed ``handbook/`` to
    ``docs/handbook/`` and four constants went quietly stale. Same flag name and
    semantics as ``reconcile.py --require-roots``: a maintainer-checkout assertion,
    never passed in CI, so the published export keeps the tolerant behaviour.
    """
    overlay = _overlay_root()
    missing = []
    # dict.fromkeys, not set(): a prefix may appear in two tuples (``history/`` is
    # both a strict root and a record source) and a plain concatenation would report
    # one missing directory twice. Order is preserved so the report reads stably.
    for prefix in dict.fromkeys(STRICT_ROOT_PREFIXES + RECORD_SOURCES + PLAN_SOURCES):
        rel = prefix.rstrip("/")
        # A tier prefix may name an overlay-only tree (the benchmark fixtures), so
        # both roots count. Absent from both is the disarm this flag exists to catch.
        if (C.REPO_ROOT / rel).exists():
            continue
        if overlay is not None and (overlay / rel).exists():
            continue
        missing.append(prefix)
    return missing


def check_retired_roots() -> list[str]:
    """RETIRED_ROOTS keys that exist again — the map's own disarm condition.

    ``check_required_roots`` asserts the module's prefixes are PRESENT. This is its
    mirror: every retired root must stay ABSENT. If someone re-creates ``design/``,
    every reference under it starts resolving for real, this map silently rewrites
    live paths into "did you mean" noise, and the tiering it drives becomes wrong in
    the one direction nobody would look. Same flag, same maintainer-only semantics.
    """
    return [old for old in RETIRED_ROOTS
            if (C.REPO_ROOT / old.rstrip("/")).exists()]


# --- Baseline / compare ---------------------------------------------------------
def _head(root: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _rename_map(root: Path, old: str, prefix: str = "") -> dict[str, str]:
    """``{old_path: new_path}`` from git's own rename detection, ``old..HEAD``."""
    r = subprocess.run(["git", "-C", str(root), "diff", "--name-status", "-M", "-C",
                        old, "HEAD"], capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if parts[0][:1] in ("R", "C") and len(parts) == 3:
            out[prefix + parts[1]] = prefix + parts[2]
    return out


def _snapshot(broken, advisory, permitted, skipped, unrecognised) -> dict:
    def rows(items, bucket):
        return [{"source": h["file"], "line": h["line"], "kind": h["kind"],
                 "tier": h["tier"], "bucket": bucket,
                 "target_raw": h.get("ref", ""), "target_norm": h.get("target", "")}
                for h in items]
    counts = {"broken": len(broken), "advisory": len(advisory),
              "permitted": len(permitted)}
    counts.update(skipped)
    overlay = _overlay_root()
    return {"commit": _head(C.REPO_ROOT),
            "overlay_commit": _head(overlay) if overlay is not None else None,
            "counts": counts,
            "findings": rows(broken, "broken") + rows(advisory, "advisory")
            + rows(permitted, "permitted")
            + rows(unrecognised, "unrecognised-root")}


def _compare(baseline: dict, current: dict) -> tuple[dict, list[dict]]:
    """Diff two snapshots ACROSS renames. Returns (summary, new findings).

    Keying a finding on ``<source> -> <target>`` alone reports a repo-wide
    regression after any move: the phase-2 stack moved most source files, so every
    pre-existing break reappeared under a new name and a naive diff read "36
    repaired, 31 fresh". Both axes are mapped through git's rename map first, and
    the target is normalised to a repo-root-relative path so a subtree moving one
    level down does not change any key.
    """
    renames = _rename_map(C.REPO_ROOT, baseline.get("commit") or "HEAD")
    overlay = _overlay_root()
    if overlay is not None and baseline.get("overlay_commit"):
        renames.update(_rename_map(overlay, baseline["overlay_commit"], "private/"))

    # Known limit of the third key: two unrelated findings that share BOTH basenames
    # (say `README.md -> gone.md` in different subtrees) are indistinguishable to it,
    # so a real new break can be matched against a resolved old one and reported as
    # "unchanged". That is why the report prints ``matched-loosely`` — a run where
    # that number is not small is telling you the rename map is doing the work and
    # the totals need eyes, not that everything is fine.
    def keys(row: dict) -> tuple[tuple, tuple, tuple]:
        src = renames.get(row["source"], row["source"])
        tgt = renames.get(row["target_norm"], row["target_norm"])
        return ((src, tgt),
                (posixpath.basename(src), tgt),
                (posixpath.basename(src), posixpath.basename(tgt)))

    cur_by = [{}, {}, {}]
    for row in current["findings"]:
        for i, k in enumerate(keys(row)):
            cur_by[i].setdefault(k, []).append(row)

    matched_ids: set[int] = set()
    resolved, loose = [], 0
    for row in baseline["findings"]:
        hit = None
        for i, k in enumerate(keys(row)):
            for cand in cur_by[i].get(k, []):
                if id(cand) not in matched_ids:
                    hit, loose = cand, loose + (1 if i > 0 else 0)
                    break
            if hit:
                break
        if hit is None:
            resolved.append(row)
        else:
            matched_ids.add(id(hit))
    new = [r for r in current["findings"] if id(r) not in matched_ids]
    summary = {"resolved": len(resolved), "new": len(new),
               "unchanged": len(matched_ids), "matched_loosely": loose}
    return summary, new


# --- Reporting ------------------------------------------------------------------
_SKIP_LABELS = {
    "overlay": "private/ overlay not mounted",
    "absent-root": "root not shipped in this tree",
    "git-ignored": "git-ignored (overlay-only / per-user)",
    "unrecognised-root": ("no recognised root prefix (prose shorthand, branch "
                          "names, API paths: seen but not resolvable)"),
    "external": "external URL (never fetched)",
    "placeholder": "placeholder destination, not a path",
    "skip-tree": "runtime/data tree",
    "anchor-only": "same-document anchor",
}


# How many distinct unrecognised roots the default report names before it truncates.
_UNRECOGNISED_ROOTS_SHOWN = 8


def _print_findings(title: str, items: list[dict], tracked: set[str],
                    renames: dict[str, str]) -> None:
    print(f"  {title}: {len(items)}")
    for b in items:
        note = ""
        if b.get("target"):
            s = _suggest(b["target"], tracked, renames)
            if s:
                note = f"   -> did you mean {s}?"
        print(f"    {b['file']}:{b['line']}  [{b['kind']}]  ->  {b.get('ref','')}{note}")


def run(check_anchors: bool = True, require_roots: bool = False,
        list_unrecognised: bool = False, baseline: str | None = None,
        compare: str | None = None) -> int:
    C.print_header("verify-links (report-only)", apply=False)

    missing_roots = check_required_roots() if require_roots else []
    resurrected = check_retired_roots() if require_roots else []
    broken, advisory, permitted, skipped, unrecognised = check_references(check_anchors)
    bad_links = check_symlinks()
    vendor_rc, vendor_msg = check_vendor()
    tracked_pub, _ = _tracked_set()

    files = _instruction_files()
    overlay = _overlay_root()
    n_ovl = len([f for f in files if _rel(f).startswith(OVERLAY_PREFIX)])
    print(f"  refs + markdown links checked across {len(files)} tracked .md files"
          + (f" ({n_ovl} of them in the mounted overlay)" if n_ovl else ""))

    # The unrecognised bucket's only detector was ``--compare`` against a baseline, and
    # NOTHING passes it — not the pre-commit hook, not CI (ci.yml runs this module bare).
    # So "never invisible again" was true of the TOTAL and of nothing else, and a total
    # sliding from 792 to 794 does not say WHICH root arrived. Name the roots instead,
    # biggest first, restricted to refs that name a file — the subset that can actually
    # be a rotted path rather than prose shorthand — so a newly stale root is a line in
    # the DEFAULT report instead of a delta someone has to go looking for.
    #
    # It still does not gate, and that is deliberate: ``test_a_branch_name_is_counted_
    # not_broken`` is right that failing the whole class needs an unbounded allowlist of
    # innocent tokens (branch names, Graph endpoints, skill-relative ``scripts/``).
    # RETIRED_ROOTS carves out the part that can be decided on evidence; the rest is
    # made READABLE, which is the actual complaint about a bucket nobody reads.
    filey = [u for u in unrecognised if u["names_a_file"]]
    by_root: dict[str, list[dict]] = {}
    for u in filey:
        by_root.setdefault(u["ref"].split("/", 1)[0] + "/", []).append(u)
    ordered = sorted(by_root.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    for key, count in skipped.items():
        if count and key != VERIFIED_KEY:
            extra = f", of which {len(filey)} name a file" \
                if key == "unrecognised-root" else ""
            print(f"  skipped refs — {_SKIP_LABELS[key]}: {count}{extra}")
            if key != "unrecognised-root" or not ordered:
                continue
            print(f"    they sit under {len(ordered)} distinct roots; "
                  "biggest first:")
            for name, us in ordered[:_UNRECOGNISED_ROOTS_SHOWN]:
                print(f"      {name:26} {len(us):4}  e.g. "
                      f"{us[0]['file']}:{us[0]['line']}  -> {us[0]['ref']}")
            if len(ordered) > _UNRECOGNISED_ROOTS_SHOWN:
                print(f"      … and {len(ordered) - _UNRECOGNISED_ROOTS_SHOWN} more "
                      "(--list-unrecognised prints every one)")

    # Every bucket gets the "did you mean" hint, not just the fatal one. The whole
    # payoff of the permitted tier is that a folded queue item's five inbound
    # handover links stay listed AND carry a pointer to the ADR that replaced them —
    # a reader who wants the successor should not have to go looking for it.
    # Feed ``_suggest`` the retired-root map. Its ``renames`` branch had been dead
    # since it was written — all three call sites passed ``{}`` — so a reference to a
    # renamed root printed with no successor even though the successor is a fact.
    retired_renames = {h["target"]: h["successor"]
                       for h in broken + advisory + permitted if h.get("successor")}
    if advisory:
        _print_findings("advisory (plans name targets that do not exist yet)",
                        advisory, tracked_pub, retired_renames)
    if permitted:
        _print_findings("permitted (dated records — rewriting them would falsify "
                        "the record)", permitted, tracked_pub, retired_renames)
    # The summary says what was VERIFIED, never "all resolve". The old line was a
    # clean bill of health issued over a third of the corpus: on this repo it printed
    # after 729 refs had been counted as unresolvable-here and 89 findings had been
    # listed above it in the advisory and permitted tiers. Both numbers are now in
    # the sentence, so nobody has to know that "references" meant "the broken tier".
    verified = skipped[VERIFIED_KEY]
    unverified = sum(v for k, v in skipped.items() if k != VERIFIED_KEY)
    if broken:
        _print_findings("BROKEN references", broken, tracked_pub, retired_renames)
    no_coverage = verified == 0
    if no_coverage:
        # The check_symlinks rule, applied to references: verifying nothing is a
        # finding. Zero verified refs across N files means the source enumeration,
        # the checkable-token filter or the tracked set stopped working — each of
        # which used to leave the routine printing a pass over an unread tree.
        print(f"  references: NOTHING WAS VERIFIED — 0 refs resolved against this "
              f"tree across {len(files)} tracked .md files ({unverified} were "
              f"counted as unresolvable here). A run that checked nothing is a "
              f"finding, not a pass.")
    else:
        print(f"  references: {len(broken)} broken of {verified} verified · "
              f"{len(advisory)} advisory · {len(permitted)} permitted · "
              f"{unverified} refs NOT verified in this tree (classes above)")

    if list_unrecognised:
        print(f"  unrecognised-root refs ({len(unrecognised)}):")
        for u in unrecognised:
            print(f"    {u['file']}:{u['line']}  {u['ref']}")

    if bad_links:
        print(f"  BROKEN skill symlinks: {len(bad_links)}")
        for b in bad_links:
            print(f"    {b['link']} -> {b['target']}")
    else:
        print("  skill symlinks: all resolve")

    print(f"  vendor drift check: {'OK' if vendor_rc == 0 else 'FAIL'} — {vendor_msg}")

    snapshot = _snapshot(broken, advisory, permitted, skipped, unrecognised)
    if baseline:
        # A baseline taken with the overlay mounted contains private/ file paths.
        # It is a throwaway artifact, so it belongs in an ignored tree; writing one
        # into the tracked surface would put the owner's interview and application
        # filenames a single `git add -A` away from the public remote.
        # Resolve BEFORE asking git about it. Path(...).write_text() is relative to
        # the process cwd while the ignore check runs from REPO_ROOT, so a run
        # started anywhere else would have guarded a different path than it wrote.
        dest = Path(baseline).expanduser().resolve()
        try:
            safe = bool(_git_ignored([dest.relative_to(C.REPO_ROOT).as_posix()]))
        except ValueError:
            safe = True        # outside the repo entirely — it cannot be committed
        if n_ovl and not safe:
            print(f"\n  REFUSED to write {dest}: this baseline names "
                  f"{n_ovl} overlay files, and that path is not git-ignored. "
                  "Write it under local/ (or pass --no-overlay).")
            return 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
        print(f"  baseline written: {dest}")

    compare_failed = False
    if compare:
        old = json.loads(Path(compare).read_text(encoding="utf-8"))
        summary, new = _compare(old, snapshot)
        print(f"  compare vs {compare}: resolved {summary['resolved']} · "
              f"new {summary['new']} · unchanged {summary['unchanged']} · "
              f"matched-loosely {summary['matched_loosely']}")
        for key in ("broken", "advisory", "permitted", "unrecognised-root",
                    VERIFIED_KEY):
            before, after = old["counts"].get(key, 0), snapshot["counts"].get(key, 0)
            if before != after:
                print(f"    {key}: {before} -> {after} ({after - before:+d})")
        for row in new:
            print(f"    NEW  {row['source']}:{row['line']}  ->  {row['target_raw']}")
        compare_failed = any(r["bucket"] == "broken" for r in new)

    if missing_roots:
        print(f"  MISSING ROOTS ({len(missing_roots)}) — a constant in this module "
              "names a directory that does not exist, which disarms the check "
              "rather than breaking it:")
        for p in missing_roots:
            print(f"    {p}")

    if resurrected:
        print(f"  RESURRECTED ROOTS ({len(resurrected)}) — RETIRED_ROOTS says these "
              "were renamed away, but they exist again, so the map now rewrites live "
              "paths:")
        for p in resurrected:
            print(f"    {p} (mapped to {RETIRED_ROOTS[p]})")

    failed = (bool(broken) or bool(bad_links) or vendor_rc != 0
              or bool(missing_roots) or bool(resurrected) or compare_failed
              or no_coverage)
    print("\n  " + ("FAIL: broken references / symlinks / drift found."
                    if failed
                    else f"OK: {verified} references, the skill symlinks and the "
                         f"vendored copies verified."))
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-check-anchors", action="store_true",
                    help="skip heading-anchor (#section) verification")
    ap.add_argument("--require-roots", action="store_true",
                    help="fail when a prefix constant names a missing directory "
                         "(maintainer checkout only — never pass this in CI)")
    ap.add_argument("--list-unrecognised", action="store_true",
                    help="print every ref that matched no recognised root prefix")
    ap.add_argument("--baseline", metavar="PATH",
                    help="write a JSON snapshot of every finding (put it in local/)")
    ap.add_argument("--compare", metavar="PATH",
                    help="diff against a snapshot, following renames in both repos")
    ap.add_argument("--no-overlay", action="store_true",
                    help="ignore a mounted private/ overlay (reproduces what a "
                         "contributor checkout and CI see)")
    a = ap.parse_args(argv)
    global _NO_OVERLAY
    _NO_OVERLAY = a.no_overlay
    return run(check_anchors=not a.no_check_anchors, require_roots=a.require_roots,
               list_unrecognised=a.list_unrecognised, baseline=a.baseline,
               compare=a.compare)


if __name__ == "__main__":
    raise SystemExit(main())
