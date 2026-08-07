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

A ROW'S OWN BASE
----------------
``base_index`` derives a row's range from its POSITION in the list, so a row's
meaning depends on the rows around it rather than on the commit it names. Two
branches cut from one base each append their rows at the END of that list;
merging both CONCATENATES them, which silently re-parents the second branch's
first row onto the first branch's last commit. Its recorded digest then covers a
range that never existed, and the gate fails on the trunk — green at pre-commit
time on each branch, red only once the merge commit exists, and unclearable by
appending anything.

A row therefore records its own range start in an optional ``base:`` key, and the
range is ``<base>..<commit>`` verbatim. The key is ADDITIVE: a row without it
falls back to ``base_index`` and verifies exactly as it always has. New rows are
emitted with it, so a re-parented range cannot happen to them.

The decision is on the FILE LIST, not the commit list. A commit that touches only
the ledger still shows up in ``git log``, so gating on "is the commit range empty"
would never converge: acknowledging a change would itself be an unacknowledged
change. Excluding the ledger from the pathspec is what makes the loop terminate,
and the digest uses the SAME exclusion so a row can be recomputed by hand:

    git diff <a>..<b> -- . ':!automation/publish/review_ledger.yaml' | shasum -a 256

THE ONE-COMMIT LAG, AND THE PENDING ROW THAT REMOVES IT
-------------------------------------------------------
A row records the commit it reviewed, so it can only be written once that commit
has a SHA. At ``pre-commit`` time HEAD is still the PREVIOUS commit, so the gate
reports on already-committed work and every content commit needs a SECOND,
ledger-only commit behind it to acknowledge the tip. That second commit is the
lag, and it is expensive: every branch then edits the one file every other branch
also edits, and a tip merged by GitHub's button (which cannot append anything)
lands on the trunk unsigned.

``commit:`` is therefore OPTIONAL. A row that omits it is a PENDING row: it pins
its range with ``base:`` and ``digest:`` alone, and its END is resolved from
history as *the commit that introduced this row into the ledger* — which the row
never has to name, so it does not have to exist yet.

That is what makes a single commit able to carry its own review row. Under
``--staged`` (what the pre-commit hook runs) the endpoint is not HEAD but the
STAGED INDEX, reached with ``git diff --cached <base>`` — byte-for-byte the diff
the commit about to be made will have against ``<base>``. So:

    git add <your paths> && review_gate.py --staged   # prints a PENDING row for
    <read the diff, append the row>                   # the index. The ledger is
    git add <ledger> && git commit                    # EXCLUDED from the pathspec,
                                                      # so the row cannot move the
                                                      # digest it records.

``git add -A`` is NOT the way to reach that index. This repo's ``.gitignore``
excludes ``.venv`` as a DIRECTORY, and a git worktree is handed its interpreter as
a SYMLINK — which that rule does not match, so ``-A`` stages a link whose blob is
an absolute path under the owner's home directory. The leak guard scans file
CONTENT and cannot see it. Name your paths.

One commit, its own row, no follow-up. After it lands, the row seals: the gate
finds the commit that introduced it and recomputes ``<base>..<that commit>``,
which is the same range and therefore the same digest.

The classic ``commit:``-carrying row is unchanged and still verifies — a row for
history that ALREADY landed (a merge commit, an orphan reconciliation) can only be
written that way, and a default (non-``--staged``) run still prints that shape.
A ledger-only commit changes no watched file, so it still acknowledges a tip
without creating new work.

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
    .venv/bin/python automation/publish/review_gate.py               # on demand, vs HEAD
    .venv/bin/python automation/publish/review_gate.py --staged      # pre-commit: vs the index
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
#     applications_root -> <repo>/examples/me/applications
#     companies_root    -> <repo>/examples/me/interviews/companies
#     overlay_mounted   -> True
#
# So the accessor resolves INTO the public example interview-prep tree, not to the
# owner-only market index this detector must inspect. That example tree exists in a
# public clone by design; using it as the source would replace the loud NOT INSPECTED
# banner with a false clean bill of health for private data the gate never read. The
# literal is correct and is single-sourced as
# ``automation/shared/company_index.DEFAULT_REL``; a test pins the restatement rather
# than adding an import a gate could fail on.
COMPANY_INDEX_REL = "private/market/company-index.yaml"
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

REQUIRED_KEYS = ("reviewed_by", "date", "files", "digest", "finding")
# ``base`` is OPTIONAL and additive: a row without it is read exactly as before
# (its range starts at ``RowChain.base_index``). See A ROW'S OWN BASE above.
# ``commit`` is OPTIONAL too — a row without it is a PENDING row whose endpoint is
# resolved from history (see THE PENDING ROW above). A row must carry at least one
# of the two, which ``validate_row`` enforces: a row with neither pins nothing.
OPTIONAL_KEYS = ("commit", "base")
ALLOWED_KEYS = OPTIONAL_KEYS + REQUIRED_KEYS
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


class GateError(Exception):
    """A ledger or repository problem: the gate cannot decide, so it stops (exit 2)."""


def _row_first_line(node: yaml.MappingNode) -> str:
    """How the ledger's TEXT names a row: its opening ``- <key>: <value>`` line.

    A damaged row has no index a reader can trust and may have no valid anchor at
    all, so it is named the way it appears in the file.
    """
    if not node.value:
        return "- (an empty row)"
    key_node, value_node = node.value[0]
    value = str(getattr(value_node, "value", ""))
    if len(value) > 48:
        value = value[:48] + "..."
    return f"- {getattr(key_node, 'value', '?')}: {value}".rstrip()


class _LedgerLoader(yaml.SafeLoader):
    """SafeLoader with implicit typing of PLAIN scalars switched off, and a
    REPEATED key rejected.

    A short sha is 7-12 hex characters, which YAML is happy to mis-type three
    different ways: ``commit: 65069829`` (all digits) becomes an int,
    ``commit: 07123456`` becomes OCTAL under YAML 1.1 — a different number
    entirely — and ``commit: 12e45678`` becomes a float. Each one turns a correct
    row into a rejected or, worse, a silently wrong one. Every scalar in the ledger
    is therefore read as text, and ``validate_row`` does the typing.

    THE REPEATED KEY, AND WHY THE CHECK IS HERE AND NOT IN ``validate_row``
    ----------------------------------------------------------------------
    YAML keeps the LAST of a repeated key and says nothing, so by the time
    ``yaml.load`` returns there is nothing left to detect: the damaged row arrives
    as an ordinary dict that passes every per-row rule the gate has. The check has
    to run during CONSTRUCTION, against the raw node's key list — which is what this
    override does, before ``SafeConstructor`` collapses the pairs into a dict.

    That is the hole a real corruption went through on 2026-08-02: a line-based
    ``union`` merge driver, configured for this append-only file, interleaved two
    rows written for the SAME range with their keys in a different ORDER, and a
    ``finding:`` line landed inside a neighbouring row. No conflict was raised and
    ``--verify-all`` stayed exit 0, because a row's digest is computed from the
    RANGE it names, never from its own text. See ``.gitattributes``.
    """

    def construct_mapping(self, node, deep=False):
        seen: set[str] = set()
        repeated: list[str] = []
        for key_node, _value_node in node.value:
            key = getattr(key_node, "value", None)
            if not isinstance(key, str):
                continue                    # a non-scalar key is not a ledger row's
            if key in seen and key not in repeated:
                repeated.append(key)
            seen.add(key)
        if repeated:
            raise GateError(
                f"review_ledger.yaml row `{_row_first_line(node)}` carries "
                + ", ".join(sorted(repeated)) + " more than once. Each key appears "
                "at most once in a row; YAML keeps the LAST one, so this row now "
                "reports a review its author never wrote. The ledger TEXT is damaged "
                "— nothing is wrong with the commit you are making. A line-based "
                "merge of this append-only file interleaves rows exactly this way. "
                "Recover the authored rows from git history and re-append them whole, "
                "at ROW granularity; never rewrite a digest to clear this."
            )
        return super().construct_mapping(node, deep=deep)


_LedgerLoader.yaml_implicit_resolvers = {}


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


def _range_args(a: str, b: str | None) -> list[str]:
    """git-diff selector for ``a..b``, or for ``a``-vs-the-INDEX when ``b`` is None.

    The index endpoint is what makes a commit able to carry its own row: at
    pre-commit time the content being reviewed is the staged tree and the commit
    has no SHA yet. ``git diff --cached <a>`` and ``git diff <a>..<the commit that
    index becomes>`` are the same tree-to-tree diff and emit the SAME BYTES, so a
    digest recorded against the index verifies unchanged against the commit —
    which is the whole basis of the pending row.
    """
    return ["--cached", a] if b is None else [f"{a}..{b}"]


def _range_label(repo: Path, a: str, b: str | None) -> str:
    return f"{short(repo, a)}..{'<staged index>' if b is None else short(repo, b)}"


def changed_files(repo: Path, a: str, b: str | None) -> list[str]:
    """Watched files that differ between ``a`` and ``b`` (ledger excluded).

    ``b=None`` compares ``a`` against the STAGED INDEX (see ``_range_args``).
    """
    out = _git_out(["diff", "--name-only", "-z", *_range_args(a, b), "--",
                    *WATCHED_PATHSPEC], repo)
    return [p for p in out.split("\0") if p]


def range_digest(repo: Path, a: str, b: str | None) -> str:
    """sha256 of the watched diff between ``a`` and ``b`` (ledger excluded).

    Hashes RAW BYTES so a binary file in the diff cannot change the answer by way
    of a decoding error. ``b=None`` hashes ``a``-vs-the-INDEX instead.
    """
    proc = _git(["diff", *_range_args(a, b), "--", *WATCHED_PATHSPEC], repo, binary=True)
    if proc.returncode != 0:
        raise GateError(f"git diff {_range_label(repo, a, b)} failed: "
                        f"{proc.stderr.decode('utf-8', 'replace').strip()}")
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
    unknown = sorted(set(raw) - set(ALLOWED_KEYS))
    if unknown:
        raise _row_error(index, "unknown key(s): " + ", ".join(unknown)
                         + f" (allowed: {', '.join(ALLOWED_KEYS)})")

    # Both anchors are optional INDIVIDUALLY and validated only when present — a row
    # written before either key existed must keep parsing to the identical dict it
    # always did — but a row carrying NEITHER pins no range at all and is rejected.
    if "commit" not in raw and "base" not in raw:
        raise _row_error(index, "a row must carry `commit:` (the commit it reviewed) "
                                "or `base:` (a PENDING row, whose commit is resolved "
                                "as the commit that introduced it into the ledger); "
                                "a row with neither pins no range")

    commit = raw.get("commit")
    if "commit" in raw and (not isinstance(commit, str)
                            or not HEX_RE.match(str(commit).lower())
                            or len(str(commit)) < 7):
        raise _row_error(index, f"commit must be >= 7 hex characters, got {commit!r}")

    base = raw.get("base")
    if "base" in raw and (not isinstance(base, str) or not HEX_RE.match(str(base).lower())
                          or len(str(base)) < 7):
        raise _row_error(index, f"base must be >= 7 hex characters, got {base!r}")

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

    row = {
        "index": index,
        "reviewed_by": reviewer,
        "date": day,
        "files": files,
        "digest": hexpart.lower(),
        "finding": finding_text,
    }
    # Each anchor is added only when the row carries it, so `row.get("commit")` /
    # `row.get("base")` are exactly the "did the author record one?" questions and a
    # legacy row's dict is unchanged apart from key order (which nothing reads).
    if "commit" in raw:
        row["commit"] = commit
    if "base" in raw:
        row["base"] = base
    return row


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
# A PENDING row names no commit and no commit has introduced it yet: it is the row
# staged for the commit being made right now. Not an error and not an orphan — it is
# the normal state of a row for exactly as long as its commit does not exist.
PENDING = "pending"


def row_ref(row: dict) -> str:
    """How a row names itself in a message: its commit, or its pending anchor.

    A pending row has no commit to print, and printing an empty string where a sha
    belongs is how a reader is told the wrong thing about which row failed.
    """
    commit = row.get("commit")
    return commit if commit else f"pending row based on {row.get('base')}"


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
        self._pending: dict[int, dict] = {}
        self._blobs: dict[str, str] = {}

    def classify(self, index: int) -> tuple[str, str | None]:
        """(status, full sha or None) for row ``index``; memoised."""
        if index not in self._seen:
            row = self._by_index[index]
            status, rev = (self._classify_named(row) if "commit" in row
                           else self._classify_pending(row))
            self._seen[index] = (status, rev)
            if status == PENDING:
                self._pending[index] = row
            elif status != ANCESTOR:
                self._skipped[index] = status
        return self._seen[index]

    def _classify_named(self, row: dict) -> tuple[str, str | None]:
        rev = resolve(self.repo, row["commit"])
        if rev is None:
            return (UNKNOWN, None)
        if is_ancestor(self.repo, rev, self.head_rev):
            return (ANCESTOR, rev)
        return (NOT_ANCESTOR, rev)

    def _classify_pending(self, row: dict) -> tuple[str, str | None]:
        """A row with no ``commit:``: find the commit that INTRODUCED it, if any.

        The search is bounded by the row's own ``base:``, which a pending row always
        carries (``validate_row``): a row cannot have been introduced before the
        commit its range starts at, so ``<base>..<head>`` is the whole search space
        and it is the SHORT one — a row's base is the review point immediately
        before it. The walk stops at the first hit, so the common cases cost one
        ``git log`` and zero-to-one ``git show``: nothing since the base has touched
        the ledger (the row is genuinely pending), or exactly the commit that just
        landed did.

        Resolution is SELF-VALIDATING, which is why a cheap containment test is
        enough: whatever commit comes back, ``verify_rows`` then recomputes
        ``<base>..<that commit>`` and compares it to the row's digest. A resolution
        that is too early or too late does not match and fails loudly (exit 2); it
        can never quietly certify a range the row did not record.

        A base that is not an ancestor of HEAD is the ORPHAN case, and it is
        reported exactly as an orphaned ``commit:`` row is: the row's range starts
        outside this history, so its digest cannot be recomputed here.
        """
        base_rev = resolve(self.repo, row["base"])
        if base_rev is None:
            return (UNKNOWN, None)
        if not is_ancestor(self.repo, base_rev, self.head_rev):
            return (NOT_ANCESTOR, None)

        needles = (f"{DIGEST_SCHEME}{row['digest']}", f"base: {row['base']}")
        proc = _git(["log", "--format=%H", "--reverse", "--topo-order", "--full-history",
                     f"{base_rev}..{self.head_rev}", "--", LEDGER_REL], self.repo)
        if proc.returncode != 0:
            return (PENDING, None)
        for rev in proc.stdout.split():
            text = self._ledger_at(rev)
            if all(needle in text for needle in needles):
                return (ANCESTOR, rev)
        return (PENDING, None)

    def _ledger_at(self, rev: str) -> str:
        """The ledger's text at ``rev``; cached, because rows share candidates."""
        if rev not in self._blobs:
            proc = _git(["show", f"{rev}:{LEDGER_REL}"], self.repo)
            self._blobs[rev] = proc.stdout if proc.returncode == 0 else ""
        return self._blobs[rev]

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
        """(row, status) for every row EXAMINED this run and found off-chain.

        PENDING rows are deliberately NOT here. Off-chain means "records a change
        this history does not have"; pending means "records the change about to be
        committed". Reporting the second as the first turns the normal shape of
        every commit into a standing warning, which is how a real warning stops
        being read.
        """
        return [(self._by_index[i], self._skipped[i]) for i in sorted(self._skipped)]

    def pending(self) -> list[dict]:
        """Rows EXAMINED this run that no commit has introduced yet."""
        return [self._pending[i] for i in sorted(self._pending)]

    def unsealed(self) -> dict | None:
        """The trailing pending row — the one written for the commit being made.

        Only the LAST row can be one. A pending row is authored for the very next
        commit, so the moment another row follows it in the ledger it has either
        been sealed by history or fallen off-chain like any other row, and either
        way it is no longer a claim about an uncommitted tree. Restricting the
        lookup to the last row also keeps it cheap: it classifies ONE row rather
        than the whole ledger.
        """
        if not self.rows:
            return None
        row = self.rows[-1]
        if "commit" in row:
            return None
        return row if self.status(row["index"]) == PENDING else None


# ── the advisory detector ────────────────────────────────────────────────────

def company_display_names(repo: Path) -> list[str] | None:
    """Display names + aliases from ``private/market/company-index.yaml``.

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


def company_hints(repo: Path, a: str, b: str | None) -> tuple[bool, list[str]]:
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

    proc = _git(["diff", *_range_args(a, b), "--", ".", LEDGER_EXCLUDE, *HINT_EXCLUDE],
                repo)
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


def _range_headline(repo: Path, base: str, head: str | None, n_files: int) -> list[str]:
    base_s = short(repo, base)
    n_files_s = f"{n_files} file{'' if n_files == 1 else 's'}"
    if head is None:
        return [f"The STAGED tree changed the published tree since the last recorded "
                f"review",
                f"({base_s} → the commit you are about to make), touching {n_files_s}:"]
    n_commits = commit_count(repo, base, head)
    return [f"{n_commits} commit{'' if n_commits == 1 else 's'} changed the published "
            f"tree since the last recorded review",
            f"({base_s} → {short(repo, head)}), touching {n_files_s}:"]


def _row_to_append(base_s: str, head_s: str | None, reviewer_note: str, today: str,
                   n_files: int, digest: str) -> list[str]:
    """The row the gate hands the reviewer — pending when there is no commit yet.

    The list-item dash sits on whichever anchor comes first, so the row is
    copy-pasteable as printed in both shapes.
    """
    anchor = ([f"    - commit: {head_s}", f"      base: {base_s}"] if head_s
              else [f"    - base: {base_s}"])
    return [
        *anchor,
        f"      reviewed_by: {reviewer_note}",
        f"      date: {today}",
        f"      files: {n_files}",
        f"      digest: {DIGEST_SCHEME}{digest[:DIGEST_MIN_HEX]}",
        "      finding: none               # or a description of what you found and fixed",
    ]


def _how_to_land(staged: bool) -> list[str]:
    if staged:
        return [
            "That row carries NO `commit:` — it cannot, the commit does not exist yet.",
            "It is a PENDING row: `base:` and `digest:` pin the range, and the gate",
            "resolves its commit later as the commit that introduced it into the ledger.",
            "",
            "Append it, `git add` the ledger, and commit ONCE. The ledger is excluded",
            "from the watched pathspec, so staging the row cannot change the digest the",
            "row records — the commit carries its own review and needs no follow-up.",
            "",
            "A row naming an already-landed commit (`commit:` + `base:`) still works and",
            "is the only shape for history that is already in — a merge commit you did",
            "not make, or a reconciliation row after a rebase orphaned one.",
        ]
    return [
        "Stage that row ALONGSIDE your next change and commit once. The gate reads the",
        "ledger from your WORKING TREE, so the row you just added acknowledges HEAD and",
        "the commit goes through — one row per commit, always one behind.",
        "",
        "Nothing else to commit? A ledger-only commit is the way to close a branch: it",
        "changes no watched file, so it acknowledges the tip without creating new work.",
        "Do that before you push — CI runs this same gate on the tip.",
        "",
        "To skip the follow-up commit entirely, stage your change and run the gate with",
        "--staged: it prints a PENDING row (no `commit:`) that the same commit carries.",
    ]


def review_required_message(repo: Path, base: str, head: str | None, files: list[str],
                            digest: str, inspected: bool, hints: list[str],
                            today: str, staged: bool = False,
                            preamble: list[str] | None = None) -> str:
    base_s = short(repo, base)
    head_s = None if head is None else short(repo, head)
    listed = files[:MAX_LISTED_FILES]
    file_lines = [f"    {f}" for f in listed]
    if len(files) > len(listed):
        file_lines.append(f"    ... and {len(files) - len(listed)} more")
    reviewer = "human" if hints else "agent          # or: human"
    reviewer_note = ("human          # REQUIRED — the advisory detector fired"
                     if hints else reviewer)
    diff_cmd = (f"git diff --cached {base_s}" if head_s is None
                else f"git diff {base_s}..{head_s}")

    lines = [
        "PUBLIC REVIEW GATE — not a test failure. Action required.",
        "",
        *(preamble + [""] if preamble else []),
        *_range_headline(repo, base, head, len(files)),
        "",
        *file_lines,
        "",
        "These files ship to a public repository. Read the diff and confirm none of it",
        "contains a real name, employer, school, date, salary, or anything about the",
        "owner's actual job hunt.",
        "",
        f"    {diff_cmd} -- . ':!{LEDGER_REL}'",
        "",
        *_hint_block(inspected, hints),
        "",
        f"Then append to {LEDGER_REL}:",
        "",
        *_row_to_append(base_s, head_s, reviewer_note, today, len(files), digest),
        "",
        "Keep `base:` as printed — it pins this row to the range you just read, so a",
        "later merge that appends other rows around it cannot re-point it at a diff you",
        "never saw. Do not guess it; it is the left side of the git diff above.",
        "",
        *_how_to_land(staged),
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
        # A pending row's sha IS its `base:` — say so, rather than let a reader go
        # looking for a commit the row never named. The wording for a `commit:` row is
        # unchanged, so an existing ledger's report is byte-for-byte what it always was.
        tail = "" if "commit" in row else " (this row's base)"
        if status == UNKNOWN:
            note = f"UNKNOWN OBJECT — not in this checkout at all{tail}"
        else:
            note = f"EXISTS here but is NOT an ancestor of HEAD{tail}"
        sha = row.get("commit") or row.get("base")
        lines.append(f"    row {str(row['index']).rjust(width)}  {sha}  {note}")
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


def _pending_rows_note(chain: RowChain) -> str:
    """Informational: rows written for a commit that does not exist yet.

    Normal at pre-commit and normal in a dirty working tree; NOT normal in CI, where
    every row in the ledger came out of a commit. Saying which rows they are is what
    tells those two apart, so it is printed rather than swallowed. Never an exit code:
    a pending row contributes nothing to the chain, so nothing rests on it.
    """
    pending = chain.pending()
    return "\n".join([
        f"public review gate: {len(pending)} ledger row(s) are PENDING — no commit has "
        f"introduced them yet",
        "(they review the commit you are about to make, so they cannot be verified "
        "against history):",
        "",
        *[f"    row {row['index']}  base {row['base']}  digest "
          f"{DIGEST_SCHEME}{row['digest']}" for row in pending],
        "",
        "A pending row seals itself the moment its commit lands: the gate then resolves",
        "it to the commit that introduced it and recomputes <base>..<that commit>.",
        "Run the gate with --staged to have this row checked against the STAGED tree.",
    ])


def _pending_row_covers(repo: Path, base_rev: str, row: dict,
                        files: list[str]) -> str | None:
    """None when ``row`` reviews exactly ``base_rev``..INDEX; else why it does not.

    Three independent claims, each checked against the repository rather than
    trusted: the row starts where the unreviewed range starts, it counts the files
    the range touches, and its digest is the sha256 of that range's diff. The digest
    is the one that cannot be produced without running ``git diff`` over the range —
    the same standard every landed row is held to.
    """
    declared = resolve(repo, row["base"])
    if declared is None:
        return (f"The last ledger row is a PENDING row whose base ({row['base']}) is not "
                f"a commit in this checkout.")
    if declared != base_rev:
        return (f"The last ledger row is a PENDING row based on {row['base']}, but the "
                f"unreviewed range starts at {short(repo, base_rev)}. A pending row must "
                f"start where the last recorded review ended, or it certifies a range "
                f"nobody read.")
    if len(files) != row["files"]:
        return (f"The last ledger row is a PENDING row recording files: {row['files']}, "
                f"but the staged range touches {len(files)}.")
    if not range_digest(repo, base_rev, None).startswith(row["digest"]):
        return ("The last ledger row is a PENDING row whose digest does not match the "
                "staged range. Read the diff below and record the digest it prints.")
    return None


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
    declared = row.get("base")
    lines = [
        f"PUBLIC REVIEW GATE — ledger row {row['index']} does not match the repository.",
        "",
        f"Row {row['index']} (commit {row_ref(row)}, reviewed_by: {row['reviewed_by']}) records",
        f"    digest: {DIGEST_SCHEME}{row['digest']}",
        "but the diff it claims to cover hashes to",
        f"    digest: {DIGEST_SCHEME}{recomputed[:len(row['digest'])]}",
        "",
        f"    git diff {base_s}..{head_s} -- . ':!{LEDGER_REL}' | shasum -a 256",
        "",
    ]

    if declared is not None:
        lines += [
            f"This row names its own base ({declared}), so the range above is the one its",
            "author wrote down — it cannot have been re-parented by later rows. The row was",
            "written without fetching the real diff, or it was rewritten afterwards.",
        ]
    else:
        lines += [
            "This row records no `base:`, so the range above was DERIVED from its position",
            "in the list: it starts at the nearest preceding row that is an ancestor of HEAD.",
            "That derivation is not stable across a merge. Two branches cut from one base",
            "each append rows at the END of the list; merging both concatenates them and",
            "re-points the second branch's first row at the first branch's last commit — a",
            "range that never existed. Tell the two causes apart before you touch anything:",
            "",
            f"    git merge-base {row_ref(row)} {base_s}      # the branch point B",
            f"    git diff B..{row_ref(row)} -- . ':!{LEDGER_REL}' | shasum -a 256",
            "",
            "  * The digest matches over B..this row  ->  RE-PARENTED RANGE. The review was",
            "    real and the diff was read; only the derived start is wrong. Recover by",
            "    redoing the convergence, not the ledger: with the merge still unpushed,",
            "",
            "        git worktree list --porcelain       # map branches to worktrees first",
            "        git -C <trunk-worktree> status --short",
            "        git -C <second-worktree> status --short",
            "        git -C <trunk-worktree> reset --merge ORIG_HEAD  # drop merge safely",
            "        # In <second-worktree>, add `base:` to ITS OWN rows, which are",
            "        # not yet on trunk, commit, then:",
            "        git -C <trunk-worktree> merge --no-ff <second branch>",
            "",
            "    Stop if either status is dirty. Never check out or move a branch from a",
            "    different worktree; local refs are shared while indexes/files are not.",
            "",
            "    A row that names its own base cannot be re-parented, so the merge lands",
            "    green. If the merge is already pushed, the row stays and is unverifiable:",
            "    append a row for HEAD carrying `base:` whose `finding:` names this row and",
            "    the re-parenting, and raise it — a permanently red trunk is a finding, not",
            "    a formatting problem.",
            "",
            "  * The digest matches over NO base  ->  the row was written without fetching",
            "    the real diff, or a historical row was rewritten.",
        ]

    lines += [
        "",
        "Never restate a row's evidence to make this pass. The ledger is append-only and a",
        "changed row is itself the finding; `digest:`, `commit:`, `files:` and `finding:`",
        "on a landed row are not editable. Recover the original text with",
        "",
        f"    git log -p -- {LEDGER_REL}",
    ]
    return "\n".join(lines)


def _unknown_base_message(repo: Path, row: dict, this_rev: str) -> str:
    return "\n".join([
        f"PUBLIC REVIEW GATE — ledger row {row['index']} names a base this checkout does "
        f"not have.",
        "",
        f"Row {row['index']} (commit {row_ref(row)}) records base: {row['base']}, which is not a",
        f"known commit here — yet {short(repo, this_rev)} IS an ancestor of HEAD, so the row "
        f"describes",
        "this history and its base should be reachable too.",
        "",
        "    git cat-file -t " + str(row["base"]) + "        # does the object exist at all?",
        "",
        "Usual cause: the base was copied from another branch, or the row was written by",
        "hand rather than from the range the gate printed. The gate refuses to guess a",
        "different base — that is exactly the re-parenting `base:` exists to prevent.",
    ])


def _files_mismatch_message(repo: Path, row: dict, base: str, head: str,
                            recomputed: int) -> str:
    base_s, head_s = short(repo, base), short(repo, head)
    return "\n".join([
        f"PUBLIC REVIEW GATE — ledger row {row['index']} does not match the repository.",
        "",
        f"Row {row['index']} (commit {row_ref(row)}) records files: {row['files']}, but",
        f"{base_s}..{head_s} touches {recomputed} watched file(s).",
        "",
        f"    git diff --name-only {base_s}..{head_s} -- . ':!{LEDGER_REL}'",
    ])


# ── the check ────────────────────────────────────────────────────────────────

def row_base_rev(repo: Path, chain: RowChain, row: dict, this_rev: str) -> str:
    """The commit a row's digest range STARTS from.

    ``base:`` when the row records one — a row that names its own base cannot be
    re-parented by rows appended around it (see A ROW'S OWN BASE). Otherwise the
    positional fallback every row written before that key relies on: the most
    recent preceding ANCESTOR row, or the row's own commit when it opens the chain
    (the seed's zero-width range).
    """
    declared = row.get("base")
    if declared is None:
        base_index = chain.base_index(row["index"])
        return this_rev if base_index is None else chain.rev(base_index)

    base_rev = resolve(repo, declared)
    if base_rev is None:
        raise GateError(_unknown_base_message(repo, row, this_rev))
    return base_rev


def verify_rows(repo: Path, chain: RowChain, to_verify: list[dict],
                check_files: set[int]) -> None:
    """Recompute each row's digest from the range it claims. Raises ``GateError``.

    A row's range is ``<base>..<this row's commit>``, where ``base`` is the row's
    own ``base:`` key when it has one and the most recent preceding ANCESTOR row's
    commit when it does not (``row_base_rev``); a row with neither opens the chain
    and gets a zero-width range (the seed), so its digest is the sha256 of an empty
    diff. Off-chain rows are skipped here and reported by the caller (``RowChain``).
    ``check_files`` names the row indices whose ``files:`` count is also cross-checked
    — that costs a second git call per row, so a default run only pays it for the
    boundary row and ``--verify-all`` pays it for all of them.
    """
    for row in to_verify:
        status, this_rev = chain.classify(row["index"])
        if status != ANCESTOR:
            continue                      # not in this history; the caller reports it
        base_rev = row_base_rev(repo, chain, row, this_rev)

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
          allow_not_applicable: bool = False, staged: bool = False) -> int:
    """Run the gate. Returns an exit code.

    Prints nothing on a clean pass, except the off-chain row report when the ledger
    carries rows that are not part of this history — those are never dropped silently.

    ``staged`` moves the endpoint from HEAD to the STAGED INDEX, which is what the
    pre-commit hook runs: the tree being judged is then the one the commit will have,
    and a PENDING row staged alongside it satisfies the gate in the SAME commit. The
    default (HEAD) behaviour is untouched, so CI and any manual run decide exactly as
    they always did.
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

        # The endpoint. None means the STAGED INDEX — the tree the commit about to be
        # made will have, which is the only thing a row can review before its commit
        # exists. Everything downstream reads it through ``_range_args``.
        endpoint = None if staged else head_rev

        files = changed_files(repo, base_rev, endpoint)
        if not files:
            if chain.pending():
                print(_pending_rows_note(chain), file=out)
            return EXIT_OK

        # A pending row staged alongside the change is what removes the follow-up
        # commit. It is accepted only when it reviews EXACTLY the unreviewed range:
        # same start, same file count, same digest.
        preamble = None
        if staged:
            unsealed = chain.unsealed()
            if unsealed is not None:
                preamble_line = _pending_row_covers(repo, base_rev, unsealed, files)
                if preamble_line is None:
                    return EXIT_OK
                preamble = [preamble_line]

        # In --staged mode a pending row that did not cover the range is explained by
        # the preamble below; anywhere else it is unexplained, so it is named here.
        if chain.pending() and not staged:
            print(_pending_rows_note(chain), file=out)

        digest = range_digest(repo, base_rev, endpoint)
        inspected, hints = company_hints(repo, base_rev, endpoint)
        print(review_required_message(repo, base_rev, endpoint, files, digest,
                                      inspected, hints, today, staged=staged,
                                      preamble=preamble), file=err)
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
    parser.add_argument("--staged", action="store_true",
                        help="judge the STAGED INDEX instead of HEAD — the tree the "
                             "commit about to be made will have. A PENDING row (no "
                             "`commit:`) staged alongside it satisfies the gate in "
                             "that same commit, so no follow-up ledger commit is "
                             "needed. What the pre-commit hook runs")
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
                 allow_not_applicable=args.allow_not_applicable, staged=args.staged)


if __name__ == "__main__":
    sys.exit(main())
