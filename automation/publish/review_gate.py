#!/usr/bin/env python3
"""The public-change review gate — fail whenever the published tree changed
without a recorded review.

Spec: ``docs/designs/workspace-restructure/review-gate.md``. This is the MECHANICAL half
of the defense: it does not prove anyone read anything and it does not detect
personal data on its own (that is ``check_public.py``). Its job is to make an
unreviewed public change *impossible to miss* and to leave a tracked trace of who
reviewed what, in ``automation/publish/review_ledger.yaml``.

HOW IT DECIDES
--------------
1. Read the last acknowledged commit from the ledger — the last row whose commit
   is an ANCESTOR of HEAD (see THE REBASE CASE below).
2. ``git diff --name-only <last-ack>..HEAD -- . ':!<ledger>'``.
3. Empty file list -> pass.  Non-empty -> fail with the instruction.

THE REBASE CASE
---------------
A row is written against a branch tip, and updating a stacked PR REBASES that
branch: every commit gets a new SHA, so a row acknowledged before the merge names
a commit that never lands. Such a row describes a change that is not in this
history, so it cannot contribute to the chain — a diff from it would describe a
change nobody made. The gate therefore builds the chain from the ANCESTOR rows
alone: a row's range runs from the most recent PRECEDING ANCESTOR row's commit to
its own. Off-chain rows are skipped for digest verification and reported by name
(``RowChain``); they are never dropped, because the ledger is append-only and an
orphaned row records a review that did happen.

The decision is on the FILE LIST, not the commit list. A commit that touches only
the ledger still shows up in ``git log``, so gating on "is the commit range empty"
would never converge: acknowledging a change would itself be an unacknowledged
change. Excluding the ledger from the pathspec is what makes the loop terminate,
and the digest uses the SAME exclusion so a row can be recomputed by hand:

    git diff <a>..<b> -- . ':!automation/publish/review_ledger.yaml' | shasum -a 256

THE ONE-COMMIT LAG
------------------
At ``pre-commit`` time HEAD is still the PREVIOUS commit, so the gate always
reports on already-committed work. That is usable because the ledger is read from
the WORKING TREE: you satisfy the gate by staging the acknowledgment row for HEAD
*alongside* your next change and committing once. One row per commit, always one
behind. A ledger-only commit changes no watched file, so it acknowledges the tip
without creating new work — that is how you land a branch green before pushing.

NOT APPLICABLE IS NOT A FREE PASS
---------------------------------
A checkout where NO ledger row names a commit it has is either the published
export mirror (expected) or a ledger that was rewritten out from under the gate
(a silent disarm). It used to be exit 0 either way. The mirror is now recognised
on its SHAPE — it ships none of ``EXPORT_ABSENT_ROOTS`` — because it runs this
repo's own tracked pre-commit hook and CI workflow, so any flag those files
passed would disarm the maintainer checkout too. ``--allow-not-applicable`` is
the explicit override for a tree you know is a mirror and that carries those
roots anyway.

EXIT CODES
----------
    0  pass, or "not applicable" (this checkout is the published export mirror,
       or --allow-not-applicable was passed)
    1  unreviewed public changes — action required
    2  ledger or repository problem (bad digest, malformed row, stale ack, shallow,
       or no row resolving in a tree that should be the ledger's own repository)

Run:
    .venv/bin/python automation/publish/review_gate.py             # pre-commit / on demand
    .venv/bin/python automation/publish/review_gate.py --verify-all  # CI: full ledger integrity
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import yaml

# automation/publish/review_gate.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

LEDGER_REL = "automation/publish/review_ledger.yaml"
# Excluding the ledger from the watched pathspec is load-bearing (see module docstring).
LEDGER_EXCLUDE = f":!{LEDGER_REL}"
WATCHED_PATHSPEC = [".", LEDGER_EXCLUDE]

# The advisory detector's source of company display names. Created by phase 7 of the
# workspace restructure; absent today, and absent for any contributor without the
# overlay. Absent means "NOT INSPECTED", never "no matches" — see ``company_hints``.
#
# DO NOT route this through ``config.companies_root()``. It looks like an obvious
# cleanup and it silently disarms the detector. Measured with ``config.example.yaml``
# active — the fallback in any clone without a real ``config.yaml``::
#
#     applications_root -> <repo>/examples/applications
#     companies_root    -> <repo>/examples/companies
#     overlay_mounted   -> True
#
# So the accessor resolves INTO the public example tree. The moment a phase-8-style
# ``examples/companies/`` exists, every public clone would read the EXAMPLE index and
# report "inspected, (none)" — replacing the loud NOT INSPECTED banner with a false
# clean bill of health, which is precisely the failure ``company_display_names``'
# ``None`` return exists to prevent. The literal is correct; this comment is what was
# missing. It is single-sourced as ``automation/shared/company_index.DEFAULT_REL`` and
# the two are pinned by ``test_review_gate.test_index_path_matches_the_shared_constant``
# — pinned by a TEST rather than by an import, because a gate must not gain an import
# it can fail on.
COMPANY_INDEX_REL = "private/companies/_index.yaml"
# Paths that are SUPPOSED to name companies, so a match there is not news.
# ``private/`` is git-ignored in this repo and can never be in a diff here; it is
# listed so the detector cannot flag the index against itself in any checkout that
# does track it (the throwaway repos the tests build, for one).
HINT_EXCLUDE = [":!examples", ":!skills/job-search/companies.yaml", ":!private"]

# Roots the maintainer tree has and ``export_public.py`` never ships — its
# ALLOWLIST_DIRS names none of them. Their ABSENCE is how this repo already
# recognises the published mirror: ``reconcile.CHECK_ROOTS`` no-ops on exactly
# this signal and ``verify_links._present_strict_prefixes`` does too. It is the
# discriminator the gate needs, because the export runs the SAME tracked
# ``automation/hooks/pre-commit`` and ``.github/workflows/ci.yml`` this repo does —
# a flag those files pass would disarm the gate here as well as there.
#
# Pinned against ``export_public.ALLOWLIST_DIRS`` by a TEST rather than by an
# import: a gate must not gain an import it can fail on (same rule as
# COMPANY_INDEX_REL above).
EXPORT_ABSENT_ROOTS = ("tasks", "memory", "message-queue", "history", "docs/roadmap")

REQUIRED_KEYS = ("commit", "reviewed_by", "date", "files", "digest", "finding")
REVIEWERS = ("agent", "human")
DIGEST_SCHEME = "sha256:"
DIGEST_MIN_HEX = 16          # 64 bits of the sha256; the spec's rows print 16 hex chars
SHORT_SHA = 8
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX_RE = re.compile(r"^[0-9a-f]+$")
MAX_LISTED_FILES = 40

# How many trailing rows have their digest recomputed on a DEFAULT run. Measured on
# this repo: ~11 ms per `git diff --name-only` and ~10-35 ms per full `git diff`
# (35 ms was a 360 KB, 5-commit range), so a bounded tail keeps the pre-commit cost
# in the tens of milliseconds while the ledger grows without bound. CI runs
# --verify-all, which recomputes every row and is the real append-only check.
# Counted in ROWS, not in verifiable rows: a tail made entirely of rows that are not
# part of this history verifies nothing until --verify-all reaches back past them.
DEFAULT_VERIFY_TAIL = 5

EXIT_OK = 0
EXIT_REVIEW_REQUIRED = 1
EXIT_LEDGER_PROBLEM = 2


class _LedgerLoader(yaml.SafeLoader):
    """SafeLoader with implicit typing of PLAIN scalars switched off.

    A short sha is 7-12 hex characters, which YAML is happy to mis-type three
    different ways: ``commit: 65069829`` (all digits) becomes an int,
    ``commit: 07123456`` becomes OCTAL under YAML 1.1 — a different number
    entirely — and ``commit: 12e45678`` becomes a float. Each one turns a correct
    row into a rejected or, worse, a silently wrong one. Every scalar in the ledger
    is therefore read as text, and ``validate_row`` does the typing.
    """


_LedgerLoader.yaml_implicit_resolvers = {}


class GateError(Exception):
    """A ledger or repository problem: the gate cannot decide, so it stops (exit 2)."""


class NotApplicable(Exception):
    """This checkout is not the repository the ledger records (exit 0, loudly)."""


# ── git plumbing ─────────────────────────────────────────────────────────────

def _git(args: list[str], repo: Path, binary: bool = False) -> subprocess.CompletedProcess:
    kwargs: dict = {"cwd": str(repo), "capture_output": True}
    if not binary:
        kwargs["text"] = True
        kwargs["errors"] = "replace"
    return subprocess.run(["git", *args], **kwargs)


def _git_ok(args: list[str], repo: Path) -> bool:
    return _git(args, repo).returncode == 0


def _git_out(args: list[str], repo: Path) -> str:
    proc = _git(args, repo)
    if proc.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def is_git_repo(repo: Path) -> bool:
    return _git_ok(["rev-parse", "--git-dir"], repo)


def is_shallow(repo: Path) -> bool:
    proc = _git(["rev-parse", "--is-shallow-repository"], repo)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def resolve(repo: Path, rev: str) -> str | None:
    """Full sha for ``rev``, or None when it does not exist in this checkout."""
    proc = _git(["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], repo)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def short(repo: Path, sha: str) -> str:
    proc = _git(["rev-parse", f"--short={SHORT_SHA}", sha], repo)
    if proc.returncode != 0:
        return sha[:SHORT_SHA]
    return proc.stdout.strip()


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return _git_ok(["merge-base", "--is-ancestor", older, newer], repo)


def changed_files(repo: Path, a: str, b: str) -> list[str]:
    """Watched files that differ between ``a`` and ``b`` (ledger excluded)."""
    out = _git_out(["diff", "--name-only", "-z", f"{a}..{b}", "--", *WATCHED_PATHSPEC], repo)
    return [p for p in out.split("\0") if p]


def range_digest(repo: Path, a: str, b: str) -> str:
    """sha256 of the watched diff between ``a`` and ``b`` (ledger excluded).

    Hashes RAW BYTES so a binary file in the diff cannot change the answer by way
    of a decoding error.
    """
    proc = _git(["diff", f"{a}..{b}", "--", *WATCHED_PATHSPEC], repo, binary=True)
    if proc.returncode != 0:
        raise GateError(f"git diff {a}..{b} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return hashlib.sha256(proc.stdout).hexdigest()


def commit_count(repo: Path, a: str, b: str) -> int:
    out = _git_out(["rev-list", "--count", f"{a}..{b}", "--", *WATCHED_PATHSPEC], repo)
    try:
        return int(out.strip())
    except ValueError:
        return 0


# ── the ledger ───────────────────────────────────────────────────────────────

def _row_error(index: int, message: str) -> GateError:
    return GateError(f"review_ledger.yaml row {index}: {message}")


def validate_row(raw: object, index: int) -> dict:
    """Structural validation of one row. Raises ``GateError`` on anything off-schema."""
    if not isinstance(raw, dict):
        raise _row_error(index, f"expected a mapping, got {type(raw).__name__}")

    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise _row_error(index, "missing required key(s): " + ", ".join(missing))
    unknown = sorted(set(raw) - set(REQUIRED_KEYS))
    if unknown:
        raise _row_error(index, "unknown key(s): " + ", ".join(unknown)
                         + f" (allowed: {', '.join(REQUIRED_KEYS)})")

    commit = raw["commit"]
    if not isinstance(commit, str) or not HEX_RE.match(commit.lower()) or len(commit) < 7:
        raise _row_error(index, f"commit must be >= 7 hex characters, got {commit!r}")

    reviewer = raw["reviewed_by"]
    if reviewer not in REVIEWERS:
        raise _row_error(index, f"reviewed_by must be one of {REVIEWERS}, got {reviewer!r}")

    day = raw["date"]
    if isinstance(day, datetime.date) and not isinstance(day, datetime.datetime):
        day = day.isoformat()
    if not isinstance(day, str) or not DATE_RE.match(day):
        raise _row_error(index, f"date must be YYYY-MM-DD, got {raw['date']!r}")

    files = raw["files"]
    if isinstance(files, str) and files.strip().isdigit():
        files = int(files.strip())      # plain scalars arrive as text (see _LedgerLoader)
    if isinstance(files, bool) or not isinstance(files, int) or files < 0:
        raise _row_error(index, f"files must be a non-negative integer, got {raw['files']!r}")

    digest = raw["digest"]
    if not isinstance(digest, str) or not digest.startswith(DIGEST_SCHEME):
        raise _row_error(index, f"digest must start with {DIGEST_SCHEME!r}, got {digest!r}")
    hexpart = digest[len(DIGEST_SCHEME):]
    if not HEX_RE.match(hexpart.lower()) or len(hexpart) < DIGEST_MIN_HEX:
        raise _row_error(index, f"digest must carry >= {DIGEST_MIN_HEX} hex characters, "
                                f"got {digest!r}")
    if len(hexpart) > 64:
        raise _row_error(index, f"digest is longer than a sha256, got {digest!r}")

    finding = raw["finding"]
    if isinstance(finding, str):
        finding_text = finding.strip()
    else:
        finding_text = str(finding).strip()
    if not finding_text:
        raise _row_error(index, "finding is required and must not be empty "
                                "(use `none` when the diff was clean)")

    return {
        "index": index,
        "commit": commit,
        "reviewed_by": reviewer,
        "date": day,
        "files": files,
        "digest": hexpart.lower(),
        "finding": finding_text,
    }


def parse_ledger(text: str) -> list[dict]:
    try:
        data = yaml.load(text, Loader=_LedgerLoader)
    except yaml.YAMLError as exc:  # noqa: PERF203
        raise GateError(f"review_ledger.yaml is not valid YAML: {exc}") from exc
    if data is None:
        raise GateError("review_ledger.yaml is empty; it must carry at least the seed row")
    if not isinstance(data, list):
        raise GateError("review_ledger.yaml must be a YAML list of rows, "
                        f"got {type(data).__name__}")
    if not data:
        raise GateError("review_ledger.yaml has no rows; it must carry at least the seed row")
    return [validate_row(raw, i) for i, raw in enumerate(data, start=1)]


def load_ledger(repo: Path, ledger_rev: str | None = None) -> list[dict]:
    """Rows from the working tree, or from ``ledger_rev`` when given.

    ``--head <rev>`` reads the ledger from that rev so CI can evaluate a PR's own
    branch tip rather than the merge commit's merged ledger. Everything else reads
    the WORKING TREE, which is what makes the one-commit-lag loop converge: the row
    you just staged counts immediately.
    """
    if ledger_rev is not None:
        proc = _git(["show", f"{ledger_rev}:{LEDGER_REL}"], repo)
        if proc.returncode != 0:
            raise GateError(f"{LEDGER_REL} does not exist at {ledger_rev}: "
                            f"{proc.stderr.strip()}")
        return parse_ledger(proc.stdout)

    path = repo / LEDGER_REL
    if not path.is_file():
        raise GateError(
            f"{LEDGER_REL} is missing. Every commit touching the published tree is "
            "reviewed through that ledger; without it the gate cannot decide anything. "
            "Restore it from git (git checkout -- " + LEDGER_REL + ")."
        )
    return parse_ledger(path.read_text(encoding="utf-8"))


# ── the chain: which rows describe THIS history ──────────────────────────────

ANCESTOR = "ancestor"
NOT_ANCESTOR = "not-an-ancestor"
UNKNOWN = "unknown-object"


class RowChain:
    """Maps the ledger onto this checkout's history: which rows count, and from where.

    Only an ANCESTOR row can contribute to the chain. A row naming a commit that is
    not an ancestor of HEAD describes a change that is not in this history, so its
    digest cannot be recomputed here — the diff would cover a change nobody made.
    Such a row is SKIPPED for verification and reported by name, never dropped: the
    ledger is append-only, and an orphaned row records a review that did happen.

    Two ways a row falls off the chain, and the difference matters to whoever reads
    the report:

      * ``NOT_ANCESTOR`` — the commit EXISTS here, on another line of history. It
        can still be inspected (``git show``, ``git diff``), so the reviewer can see
        exactly what that row acknowledged.
      * ``UNKNOWN`` — the commit is not a known object in this checkout at all. A
        fresh clone carries only REACHABLE objects, so once the branch is deleted
        the commit is gone in CI even though the author's repo still has it. Nothing
        local can inspect it.

    Classification is lazy and memoised: a default run pays one ``rev-parse`` and one
    ``merge-base`` per row it actually looks at (the verified tail plus the walk back
    to each base), so the pre-commit cost does not grow with the ledger.
    """

    def __init__(self, repo: Path, rows: list[dict], head_rev: str):
        self.repo = repo
        self.rows = rows
        self.head_rev = head_rev
        self._by_index = {row["index"]: row for row in rows}
        self._seen: dict[int, tuple[str, str | None]] = {}
        self._skipped: dict[int, str] = {}

    def classify(self, index: int) -> tuple[str, str | None]:
        """(status, full sha or None) for row ``index``; memoised."""
        if index not in self._seen:
            row = self._by_index[index]
            rev = resolve(self.repo, row["commit"])
            if rev is None:
                status = UNKNOWN
            elif is_ancestor(self.repo, rev, self.head_rev):
                status = ANCESTOR
            else:
                status = NOT_ANCESTOR
            self._seen[index] = (status, rev)
            if status != ANCESTOR:
                self._skipped[index] = status
        return self._seen[index]

    def status(self, index: int) -> str:
        return self.classify(index)[0]

    def rev(self, index: int) -> str | None:
        return self.classify(index)[1]

    def base_index(self, index: int) -> int | None:
        """The most recent PRECEDING ancestor row, or None when there is none.

        None means "this row opens the chain", which is the seed row's zero-width
        range: there is nothing in this history to diff from.
        """
        for candidate in range(index - 1, 0, -1):
            if self.status(candidate) == ANCESTOR:
                return candidate
        return None

    def last_ancestor(self) -> dict | None:
        """The closest surviving ancestor row — the base every unreviewed diff uses."""
        for row in reversed(self.rows):
            if self.status(row["index"]) == ANCESTOR:
                return row
        return None

    def any_resolved(self) -> bool:
        """True when at least one row names a commit this checkout has at all."""
        return any(self.rev(row["index"]) is not None for row in self.rows)

    def skipped(self) -> list[tuple[dict, str]]:
        """(row, status) for every row EXAMINED this run and found off-chain."""
        return [(self._by_index[i], self._skipped[i]) for i in sorted(self._skipped)]


# ── the advisory detector ────────────────────────────────────────────────────

def company_display_names(repo: Path) -> list[str] | None:
    """Display names + aliases from ``private/companies/_index.yaml``.

    Returns None when there was NOTHING TO INSPECT — the caller MUST report that as
    "not inspected". Silence from a detector that never ran is indistinguishable
    from a clean diff, which is the failure mode this return value exists to
    prevent. There is deliberately NO fallback that scans the private tree
    directly: measured, that matches 51 of 177 private company tokens across the
    current public tree (``canonical`` 114 files, ``writer`` 103, ``render`` 85,
    ``lambda`` 59), which is unusable even as a hint.

    "Nothing to inspect" is every way the file fails to yield a name, not only the
    three structural ones. An index that is an EMPTY mapping, one whose entries are
    not mappings, and one whose entries all lack ``display`` each used to return
    ``[]`` — reported by ``company_hints`` as *inspected, (none)*, a clean bill of
    health from a detector that found nothing to look at. ``company_index.lint``
    names the last two, but only on the maintainer's machine via the reconciler;
    this gate never consults the linter, so it draws its own conclusion here. An
    empty result IS the tell, so it is the test: zero names -> None.
    """
    path = repo / COMPANY_INDEX_REL
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    names: set[str] = set()
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        display = entry.get("display")
        if isinstance(display, str) and display.strip():
            names.add(display.strip())
        aliases = entry.get("aliases")
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias.strip():
                    names.add(alias.strip())
    if not names:
        return None
    return sorted(names)


def company_hints(repo: Path, a: str, b: str) -> tuple[bool, list[str]]:
    """(inspected, hints) — company display names NEWLY introduced by ``a..b``.

    Narrowed on four axes, and advisory: it never fails the gate by itself.
      1. Runs on the DIFF, not the tree.
      2. Subtracts every name already present in the public tree at ``a``.
      3. Matches DISPLAY NAMES, so ``lambda`` only fires as ``Lambda Systems Inc.``.
      4. Skips ``examples/`` and the ATS registry, which are supposed to name companies.
    """
    names = company_display_names(repo)
    if names is None:
        # Absent, unreadable, or structurally yielding no name at all. There is no
        # "inspected and empty" branch on purpose: a name set of zero is the shape
        # of a detector that found nothing to look at, never of a clean index.
        return (False, [])

    proc = _git(["diff", f"{a}..{b}", "--", ".", LEDGER_EXCLUDE, *HINT_EXCLUDE], repo)
    if proc.returncode != 0:
        return (True, [])
    added = "\n".join(
        line for line in proc.stdout.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ).lower()
    if not added:
        return (True, [])

    candidates = [n for n in names if n.lower() in added]
    # Subtract the pre-change baseline: a name already in the public tree is not news.
    hints = [n for n in candidates
             if not _git_ok(["grep", "-q", "-i", "-I", "-F", "-e", n, a], repo)]
    return (True, hints)


# ── messages ─────────────────────────────────────────────────────────────────

def _hint_block(inspected: bool, hints: list[str]) -> list[str]:
    if not inspected:
        return [
            "Hint — private-company cross-reference: NOT INSPECTED.",
            f"  {COMPANY_INDEX_REL} yielded no company names — it is absent (no",
            "  overlay mounted, or the index has not been built yet), unreadable, or",
            "  structurally broken (empty, or no entry carries a `display`). This is",
            "  NOT the same as 'no matches' — the detector did not run against",
            "  anything. Read the diff yourself.",
        ]
    if not hints:
        return ["Hint — names newly introduced by this diff that match a company in the",
                "private tree (advisory only):  (none)"]
    return (["Hint — names newly introduced by this diff that match a company in the",
             "private tree (advisory only):"]
            + [f"    {n}" for n in hints]
            + ["  A hint is not a verdict, but a row covering this range must be signed",
               "  `reviewed_by: human`."])


def review_required_message(repo: Path, base: str, head: str, files: list[str],
                            digest: str, inspected: bool, hints: list[str],
                            today: str) -> str:
    base_s, head_s = short(repo, base), short(repo, head)
    n_commits = commit_count(repo, base, head)
    listed = files[:MAX_LISTED_FILES]
    file_lines = [f"    {f}" for f in listed]
    if len(files) > len(listed):
        file_lines.append(f"    ... and {len(files) - len(listed)} more")
    reviewer = "human" if hints else "agent          # or: human"
    reviewer_note = ("human          # REQUIRED — the advisory detector fired"
                     if hints else reviewer)

    lines = [
        "PUBLIC REVIEW GATE — not a test failure. Action required.",
        "",
        f"{n_commits} commit{'' if n_commits == 1 else 's'} changed the published tree "
        f"since the last recorded review",
        f"({base_s} → {head_s}), touching {len(files)} "
        f"file{'' if len(files) == 1 else 's'}:",
        "",
        *file_lines,
        "",
        "These files ship to a public repository. Read the diff and confirm none of it",
        "contains a real name, employer, school, date, salary, or anything about the",
        "owner's actual job hunt.",
        "",
        f"    git diff {base_s}..{head_s} -- . ':!{LEDGER_REL}'",
        "",
        *_hint_block(inspected, hints),
        "",
        f"Then append to {LEDGER_REL}:",
        "",
        f"    - commit: {head_s}",
        f"      reviewed_by: {reviewer_note}",
        f"      date: {today}",
        f"      files: {len(files)}",
        f"      digest: {DIGEST_SCHEME}{digest[:DIGEST_MIN_HEX]}",
        "      finding: none               # or a description of what you found and fixed",
        "",
        "Stage that row ALONGSIDE your next change and commit once. The gate reads the",
        "ledger from your WORKING TREE, so the row you just added acknowledges HEAD and",
        "the commit goes through — one row per commit, always one behind.",
        "",
        "Nothing else to commit? A ledger-only commit is the way to close a branch: it",
        "changes no watched file, so it acknowledges the tip without creating new work.",
        "Do that before you push — CI runs this same gate on the tip.",
    ]
    return "\n".join(lines)


def _off_chain_lines(skipped: list[tuple[dict, str]]) -> list[str]:
    """One line per off-chain row, naming it and saying WHICH kind of off-chain.

    The two statuses mean different things to a reader: a NOT_ANCESTOR commit is
    still here to inspect, an UNKNOWN one is not in this checkout at all.
    """
    width = max((len(str(row["index"])) for row, _ in skipped), default=1)
    lines = []
    for row, status in skipped:
        if status == UNKNOWN:
            note = "UNKNOWN OBJECT — not in this checkout at all"
        else:
            note = "EXISTS here but is NOT an ancestor of HEAD"
        lines.append(f"    row {str(row['index']).rjust(width)}  {row['commit']}  {note}")
    return lines


def _skipped_rows_note(chain: RowChain) -> str:
    """Informational: the off-chain rows this run examined. Never changes the exit code."""
    skipped = chain.skipped()
    return "\n".join([
        f"public review gate: {len(skipped)} of {len(chain.rows)} ledger row(s) are not "
        f"part of this history",
        "(skipped for verification, not dropped):",
        "",
        *_off_chain_lines(skipped),
        "",
        "A row naming a commit outside this history cannot be verified — the diff it",
        "claims would cover a change nobody made here. The chain is built from the",
        "ancestor rows alone, so the next ancestor row covers the range. The rows stay:",
        "the ledger is append-only and an orphaned row records a review that did happen.",
        "",
        "Usual cause: the branch was rebased after its row was written — updating a",
        "stacked PR replays every commit under a new SHA. UNKNOWN OBJECT additionally",
        "means the commit is unreachable in this clone (a fresh CI clone carries only",
        "reachable objects, so a deleted branch's commits are simply gone).",
    ])


def _stale_ack_message(repo: Path, chain: RowChain, head: str) -> str:
    head_s = short(repo, head)
    return "\n".join([
        "PUBLIC REVIEW GATE — the ledger is out of sync with this branch.",
        "",
        f"NONE of the {len(chain.rows)} ledger rows names a commit that is an ancestor of "
        f"{head_s},",
        "so no row describes this history and there is no base to diff from:",
        "",
        *_off_chain_lines(chain.skipped()),
        "",
        "That happens after a rebase, an amend, a force-push, or when every row was",
        "written on a branch this one never merged.",
        "",
        "The gate refuses to guess: a diff from a commit that is not in this history",
        "would describe a change nobody made.",
        "",
        "Recover with ONE of:",
        f"    git merge-base --is-ancestor <row commit> {head_s}   # confirm (exits 1)",
        "    git log --oneline -5 <row commit>                     # where did it go?",
        "",
        "  * If you rebased your own unpushed work, reset the branch back onto the",
        "    acknowledged commit, or",
        "  * review `git diff <closest surviving base>..HEAD` and APPEND a new row for",
        "    HEAD whose `finding:` records the rewrite.",
        "",
        "Never edit or delete an existing row — the ledger is append-only, and a",
        "rewritten row is itself a finding.",
    ])


def _shallow_message() -> str:
    return "\n".join([
        "PUBLIC REVIEW GATE — cannot run in a shallow clone.",
        "",
        "The last acknowledged commit is not in this checkout's object database because",
        "the history is truncated. The gate needs the full history to compute the diff",
        "since the last review.",
        "",
        "  * CI: set `fetch-depth: 0` on actions/checkout.",
        "  * Locally: git fetch --unshallow",
    ])


def is_published_export(repo: Path) -> bool:
    """True when this tree has NONE of the roots only the maintainer repo ships.

    The published mirror is the one place where "no ledger row resolves" is
    expected rather than alarming, so tolerating it has to be conditional on
    actually being that mirror — see ``EXPORT_ABSENT_ROOTS``.
    """
    return not any((repo / root).is_dir() for root in EXPORT_ABSENT_ROOTS)


def _not_applicable_message(n_rows: int, reason: str = "") -> str:
    return "\n".join([
        "public review gate: NOT APPLICABLE in this checkout.",
        "",
        f"None of the {n_rows} ledger row(s) names a commit that exists here, so this is",
        "not the repository whose review history the ledger records — an exported public",
        "mirror (export_public.py --git-init) or a re-initialised tree. There is nothing",
        "to review against. The gate is a no-op here and exits 0.",
        *([f"", f"Tolerated because: {reason}"] if reason else []),
    ])


def _no_resolvable_row_message(n_rows: int) -> str:
    roots = ", ".join(f"{r}/" for r in EXPORT_ABSENT_ROOTS)
    return "\n".join([
        "PUBLIC REVIEW GATE — the ledger describes a history this checkout does not have.",
        "",
        f"None of the {n_rows} ledger row(s) names a commit that exists here, and yet this",
        f"tree carries the maintainer-only roots ({roots}), so it IS the",
        "repository whose review history the ledger records. Every recorded review has",
        "become unverifiable in one step: the ledger was rewritten or truncated, or this",
        "branch's history was replaced.",
        "",
        "This exit used to be 0. It is the documented exported-mirror case, and the same",
        "path swallowed a wholesale ledger rewrite in pre-commit and in CI.",
        "",
        "The ledger is APPEND-ONLY — recover the rows rather than writing new ones:",
        "",
        "    git log -p -- automation/publish/review_ledger.yaml",
        "",
        "If this genuinely is a mirror that ships the process roots, say so explicitly:",
        "",
        "    review_gate.py --allow-not-applicable",
    ])


def _digest_mismatch_message(repo: Path, row: dict, base: str, head: str,
                             recomputed: str) -> str:
    base_s, head_s = short(repo, base), short(repo, head)
    return "\n".join([
        f"PUBLIC REVIEW GATE — ledger row {row['index']} does not match the repository.",
        "",
        f"Row {row['index']} (commit {row['commit']}, reviewed_by: {row['reviewed_by']}) records",
        f"    digest: {DIGEST_SCHEME}{row['digest']}",
        "but the diff it claims to cover hashes to",
        f"    digest: {DIGEST_SCHEME}{recomputed[:len(row['digest'])]}",
        "",
        f"    git diff {base_s}..{head_s} -- . ':!{LEDGER_REL}' | shasum -a 256",
        "",
        "Either the row was written without fetching the real diff, or a historical row",
        "was rewritten. The ledger is append-only: a changed row is itself a finding.",
        "Correct the digest ONLY if you have actually reviewed that diff; otherwise",
        "append a new row recording what happened.",
    ])


def _files_mismatch_message(repo: Path, row: dict, base: str, head: str,
                            recomputed: int) -> str:
    base_s, head_s = short(repo, base), short(repo, head)
    return "\n".join([
        f"PUBLIC REVIEW GATE — ledger row {row['index']} does not match the repository.",
        "",
        f"Row {row['index']} (commit {row['commit']}) records files: {row['files']}, but",
        f"{base_s}..{head_s} touches {recomputed} watched file(s).",
        "",
        f"    git diff --name-only {base_s}..{head_s} -- . ':!{LEDGER_REL}'",
    ])


# ── the check ────────────────────────────────────────────────────────────────

def verify_rows(repo: Path, chain: RowChain, to_verify: list[dict],
                check_files: set[int]) -> None:
    """Recompute each row's digest from the range it claims. Raises ``GateError``.

    A row's range is ``<most recent preceding ANCESTOR row's commit>..<this row's
    commit>``; a row with no preceding ancestor row opens the chain and gets a
    zero-width range (the seed), so its digest is the sha256 of an empty diff.
    Off-chain rows are skipped here and reported by the caller (``RowChain``).
    ``check_files`` names the row indices whose ``files:`` count is also cross-checked
    — that costs a second git call per row, so a default run only pays it for the
    boundary row and ``--verify-all`` pays it for all of them.
    """
    for row in to_verify:
        status, this_rev = chain.classify(row["index"])
        if status != ANCESTOR:
            continue                      # not in this history; the caller reports it
        base_index = chain.base_index(row["index"])
        base_rev = this_rev if base_index is None else chain.rev(base_index)

        recomputed = range_digest(repo, base_rev, this_rev)
        if not recomputed.startswith(row["digest"]):
            raise GateError(_digest_mismatch_message(repo, row, base_rev, this_rev,
                                                     recomputed))
        if row["index"] in check_files:
            n = len(changed_files(repo, base_rev, this_rev))
            if n != row["files"]:
                raise GateError(_files_mismatch_message(repo, row, base_rev, this_rev, n))


def check(repo: Path = REPO_ROOT, head: str = "HEAD", ledger_rev: str | None = None,
          verify_tail: int = DEFAULT_VERIFY_TAIL, verify_all: bool = False,
          today: str | None = None, out=None, err=None,
          allow_not_applicable: bool = False) -> int:
    """Run the gate. Returns an exit code.

    Prints nothing on a clean pass, except the off-chain row report when the ledger
    carries rows that are not part of this history — those are never dropped silently.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    today = today or datetime.date.today().isoformat()

    try:
        if not is_git_repo(repo):
            print(_not_applicable_message(0), file=out)
            return EXIT_OK

        rows = load_ledger(repo, ledger_rev)

        head_rev = resolve(repo, head)
        if head_rev is None:
            if head == "HEAD":
                raise NotApplicable(_not_applicable_message(len(rows)))
            raise GateError(f"--head {head!r} does not resolve to a commit in this checkout.")

        # The chain is the ANCESTOR rows only (see THE REBASE CASE in the module
        # docstring). The base for everything below is the CLOSEST SURVIVING ancestor
        # row, so the printed `git diff` and digest are copy-pasteable in the checkout
        # the reader is actually in.
        chain = RowChain(repo, rows, head_rev)
        last = chain.last_ancestor()
        if last is None:
            if is_shallow(repo):
                raise GateError(_shallow_message())
            if not chain.any_resolved():
                # NOT unconditionally exit 0 any more. "No row resolves" is the
                # published mirror's normal state and a wholesale ledger rewrite's
                # normal state, and the second was passing on the first's licence.
                if allow_not_applicable:
                    raise NotApplicable(_not_applicable_message(
                        len(rows), "--allow-not-applicable was passed"))
                if is_published_export(repo):
                    raise NotApplicable(_not_applicable_message(
                        len(rows), "this tree ships none of "
                        + ", ".join(f"{r}/" for r in EXPORT_ABSENT_ROOTS)
                        + " — the published-export shape"))
                raise GateError(_no_resolvable_row_message(len(rows)))
            raise GateError(_stale_ack_message(repo, chain, head_rev))
        base_rev = chain.rev(last["index"])

        # Ledger integrity first: a gate that decides from a rewritten ledger is worse
        # than no gate. --verify-all (CI) recomputes every row; a default run recomputes
        # a bounded tail, so the pre-commit cost does not grow with the ledger.
        to_verify = rows if verify_all else rows[-max(verify_tail, 1):]
        check_files = {row["index"] for row in rows} if verify_all else {last["index"]}
        try:
            verify_rows(repo, chain, to_verify, check_files)
        finally:
            # Reported even when verification fails: an orphaned row is never dropped
            # silently, and knowing one is there is what explains the base the gate used.
            if chain.skipped():
                print(_skipped_rows_note(chain), file=out)

        files = changed_files(repo, base_rev, head_rev)
        if not files:
            return EXIT_OK

        digest = range_digest(repo, base_rev, head_rev)
        inspected, hints = company_hints(repo, base_rev, head_rev)
        print(review_required_message(repo, base_rev, head_rev, files, digest,
                                      inspected, hints, today), file=err)
        return EXIT_REVIEW_REQUIRED

    except NotApplicable as exc:
        print(str(exc), file=out)
        return EXIT_OK
    except GateError as exc:
        print(str(exc), file=err)
        return EXIT_LEDGER_PROBLEM


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when the published tree changed without a recorded review.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit 0 pass / not applicable · 1 review required · 2 ledger problem",
    )
    parser.add_argument("--repo", default=str(REPO_ROOT),
                        help="repository root to check (default: this checkout)")
    parser.add_argument("--head", default=None, metavar="REV",
                        help="evaluate through REV instead of HEAD, and read the ledger "
                             "from REV too (CI uses this for a PR's own branch tip, so "
                             "the merge commit's merged ledger is never consulted)")
    parser.add_argument("--verify-all", action="store_true",
                        help="recompute EVERY historical row's digest and file count "
                             "(the full append-only check; CI runs this)")
    parser.add_argument("--verify-tail", type=int, default=DEFAULT_VERIFY_TAIL,
                        metavar="N",
                        help=f"how many trailing rows a default run recomputes "
                             f"(default: {DEFAULT_VERIFY_TAIL})")
    parser.add_argument("--allow-not-applicable", action="store_true",
                        help="exit 0 when NO ledger row names a commit this checkout "
                             "has. Only for a tree you know is a mirror: it is also "
                             "what a wholesale ledger rewrite looks like. The "
                             "published export is detected on its own shape and does "
                             "not need this flag")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    head = args.head or "HEAD"
    return check(repo=repo, head=head, ledger_rev=args.head,
                 verify_tail=args.verify_tail, verify_all=args.verify_all,
                 allow_not_applicable=args.allow_not_applicable)


if __name__ == "__main__":
    sys.exit(main())
