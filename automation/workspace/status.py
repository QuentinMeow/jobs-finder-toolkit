#!/usr/bin/env python3
"""Show all local Git work for the toolkit and its optional private overlay.

This command is deliberately local-only: it reads registered worktrees, refs,
and cached remote-tracking refs, but never fetches or writes Git state. The one
exception is opt-in and named: ``--pr`` asks GitHub, through ``gh``, for the
pull-request state no local ref can know.

Beyond the inventory it answers the two questions an agent picking up a
half-finished branch actually has — WHAT IS THIS FOR and IS ANYONE ON IT —
without asking anybody to maintain a record:

* ``intent`` comes from ``git branch --edit-description`` (Git's own idiom:
  multi-line, shared across linked worktrees, never pushed), falling back to the
  branch's first commit subject when there is no description;
* ``state`` is DERIVED on every run from the branch tip's commit date, the
  worktree's own files, the worktree lock, and a content-containment merge
  probe — ``active`` | ``idle`` | ``stale`` | ``merged`` | ``orphaned`` |
  ``wedged``. Nothing is stored, so nothing can go stale or lie.

``--json`` emits the same model for tools; ``--stale <days>`` narrows the branch
table to what nobody has touched.

Tests: ``.venv/bin/python -m unittest discover automation/workspace/tests``
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
RENAME_CODES = {"R", "C"}

JSON_SCHEMA = "workspace-status/v1"

# ── lifecycle derivation ─────────────────────────────────────────────────────
#
# DERIVE, NEVER DECLARE. Every lifecycle field below is read back out of
# something Git already enforces — a commit date, a worktree registration, a
# branch description — so none of it can drift the way a hand-written status
# record does. There is no state file, no claim, no lease, and no heartbeat.
#
# WALL CLOCK, NEVER ``time.monotonic()``. Measured on this machine, monotonic
# had lost 229,413 s (63.7 h) of laptop sleep against wall-since-boot: a lease
# or age computed from it reads FRESH forever after the lid closes, which is
# precisely the failure this dashboard has to survive. ``time.time()`` steps
# backwards on an NTP correction, so every age is clamped at zero.
ACTIVE_MAX_SECONDS = 30 * 60          # a 20-minute turn can write nothing
IDLE_MAX_SECONDS = 24 * 60 * 60       # close the laptop at 6pm, reopen at 9am

STATE_ACTIVE = "active"
STATE_IDLE = "idle"
STATE_STALE = "stale"
STATE_MERGED = "merged"
STATE_ORPHANED = "orphaned"
STATE_WEDGED = "wedged"
STATES = (STATE_ACTIVE, STATE_IDLE, STATE_STALE, STATE_MERGED, STATE_ORPHANED,
          STATE_WEDGED)

# Where a branch's stated intent came from. A description is the owner's own
# words; the first commit subject is the fallback, so an undescribed branch
# degrades to "still useful" instead of "confidently wrong".
INTENT_DESCRIPTION = "description"
INTENT_FIRST_COMMIT = "first-commit"
INTENT_TIP_COMMIT = "tip-commit"
INTENT_NONE = "none"
INTENT_WIDTH = 28

# ``git merge-tree --write-tree`` — the merge probe. See _merged_state.
MERGE_TREE_MIN_VERSION = (2, 38)
PROBE_MERGE_TREE = "merge-tree"
PROBE_ANCESTOR_ONLY = "ancestor-only"
PROBE_DEGRADED_NOTE = (
    "DEGRADED merge probe: this Git is older than 2.38, so `merge-tree "
    "--write-tree` is unavailable and merge state falls back to the ancestor "
    "test. That test MISSES squash-merges, so branches will read `unmerged` "
    "when their work is already in main. It never reads the other way."
)
_OID_RE = re.compile(r"^[0-9a-f]{40,64}$")
_MERGED_UNKNOWN = "unknown"


class GitError(RuntimeError):
    """A local Git query failed."""


@dataclass(frozen=True)
class Change:
    code: str
    path: str
    old_path: str | None = None


@dataclass
class Worktree:
    path: Path
    head: str = ""
    branch_ref: str | None = None
    detached: bool = False
    bare: bool = False
    locked: str | None = None
    prunable: str | None = None
    changes: list[Change] = field(default_factory=list)
    status_error: str | None = None
    mtime_epoch: int | None = None
    directory_missing: bool = False

    @property
    def gone(self) -> bool:
        """The registration outlives its directory — the V-G/V-H blind spot.

        A worktree whose directory the owner deleted keeps WEDGING its branch:
        ``git switch <branch>`` refuses with "already used by worktree at ..."
        until ``git worktree prune`` runs, and ``git gc`` only prunes worktree
        metadata after ``gc.worktreePruneExpire`` = three months. Git reports
        ``prunable`` for it — UNLESS the worktree is locked, in which case the
        lock suppresses the annotation and the entry is invisible to every
        porcelain answer. Hence both halves of this test.
        """
        return self.prunable is not None or self.directory_missing

    @property
    def branch(self) -> str:
        if self.branch_ref:
            return self.branch_ref.removeprefix("refs/heads/")
        if self.bare:
            return "(bare)"
        return f"(detached @{self.head[:8]})"

    @property
    def dirty(self) -> bool:
        return bool(self.changes)

    @property
    def staged(self) -> int:
        return sum(
            1 for item in self.changes
            if item.code not in CONFLICT_CODES and item.code[0] not in {" ", "?"}
        )

    @property
    def unstaged(self) -> int:
        return sum(
            1 for item in self.changes
            if item.code not in CONFLICT_CODES and item.code[1] not in {" ", "?"}
        )

    @property
    def untracked(self) -> int:
        return sum(1 for item in self.changes if item.code == "??")

    @property
    def conflicts(self) -> int:
        return sum(1 for item in self.changes if item.code in CONFLICT_CODES)


@dataclass(frozen=True)
class Ref:
    full_name: str
    short_name: str
    oid: str
    short_oid: str
    upstream_ref: str
    upstream_short: str
    relative_date: str
    subject: str
    symbolic_target: str
    committer_epoch: str = ""

    @property
    def committed_at(self) -> int | None:
        """The tip commit's committer date as a Unix timestamp (wall clock)."""
        try:
            return int(self.committer_epoch)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Branch:
    scope: str
    name: str
    ref: Ref
    upstream: Ref | None
    upstream_missing: bool
    ahead: int | None
    behind: int | None
    merged: str
    worktree_path: Path | None
    state: str = STATE_STALE
    intent: str = ""
    intent_source: str = INTENT_NONE
    next_action: str | None = None
    evidence_epoch: int | None = None
    evidence_source: str = "tip-commit"
    age_seconds: int | None = None
    wedged_at: Path | None = None
    locked: bool = False
    pr: str | None = None

    @property
    def sync(self) -> str:
        if self.scope == "R":
            return "cached only"
        if self.upstream_missing:
            return "upstream missing"
        if self.upstream is None:
            return "local only"
        assert self.ahead is not None and self.behind is not None
        if self.ahead == 0 and self.behind == 0:
            return "synced"
        if self.ahead and self.behind:
            return f"diverged +{self.ahead}/-{self.behind}"
        if self.ahead:
            return f"ahead {self.ahead}"
        return f"behind {self.behind}"


@dataclass(frozen=True)
class Remote:
    name: str
    url: str


@dataclass
class Repository:
    label: str
    root: Path
    worktrees: list[Worktree]
    branches: list[Branch]
    remotes: list[Remote]
    local_ref_count: int
    remote_ref_count: int
    base_ref: str | None
    merge_probe: str = PROBE_MERGE_TREE
    merge_probe_note: str | None = None
    pr_requested: bool = False
    pr_error: str | None = None


class Palette:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def paint(self, value: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return value
        return "".join(styles) + value + self.RESET


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
    acceptable: Iterable[int] = (),
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one local Git query. ``env`` overlays the caller's environment.

    The only caller that passes ``env`` is the merge probe, which redirects
    Git's object WRITES into a throwaway directory (see ``open_merge_probe``).
    """
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, **env} if env else None,
    )
    allowed = {0, *acceptable}
    if check and result.returncode not in allowed:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise GitError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return result


def _git_toplevel(path: Path) -> Path | None:
    if not path.exists():
        return None
    result = _git(path, "rev-parse", "--show-toplevel", check=False)
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def validate_toolkit_root(root: Path) -> None:
    """Refuse a copied command that is no longer inside this toolkit."""
    expected_markers = (
        root / "AGENTS.md",
        root / "config.example.yaml",
        root / "automation" / "shared" / "config.py",
        root / "skills" / "job-search" / "SKILL.md",
    )
    top = _git_toplevel(root)
    if top != root.resolve() or not all(marker.is_file() for marker in expected_markers):
        raise GitError(
            "refusing to run: this script is not inside the jobs-finder-toolkit "
            "repository it was shipped with"
        )


def _parse_changes(raw: str) -> list[Change]:
    tokens = raw.split("\0")
    changes: list[Change] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        code = token[:2]
        path = token[3:]
        old_path = None
        if code[0] in RENAME_CODES and index < len(tokens):
            old_path = tokens[index]
            index += 1
        changes.append(Change(code=code, path=path, old_path=old_path))
    return changes


def _parse_worktree_records(raw: str) -> list[Worktree]:
    worktrees: list[Worktree] = []
    for record in raw.split("\0\0"):
        fields = [field for field in record.split("\0") if field]
        if not fields:
            continue
        values: dict[str, str] = {}
        flags: set[str] = set()
        for item in fields:
            key, separator, value = item.partition(" ")
            if separator:
                values[key] = value
            else:
                flags.add(key)
        if "worktree" not in values:
            continue
        worktrees.append(
            Worktree(
                path=Path(values["worktree"]),
                head=values.get("HEAD", ""),
                branch_ref=values.get("branch"),
                detached="detached" in flags,
                bare="bare" in flags,
                locked=values.get("locked", "" if "locked" in flags else None),
                prunable=values.get("prunable", "" if "prunable" in flags else None),
            )
        )
    return worktrees


def _worktree_mtime(worktree: Worktree) -> int | None:
    """Newest modification time visible from this worktree, in wall-clock seconds.

    Deliberately NOT a full tree walk: the newest of the worktree root, its
    ``.git`` pointer (a FILE in a linked worktree, which Git rewrites as the
    worktree is used), and every path ``git status`` already reported as
    changed. That is the evidence of "somebody was editing here" without
    touching a file the caller did not ask about, and it costs one ``stat`` per
    already-known path. ``--no-optional-locks`` keeps the status query itself
    from refreshing the index, so reading the dashboard never makes a worktree
    look younger than it is.
    """
    stamps: list[int] = []
    for candidate in (worktree.path, worktree.path / ".git"):
        try:
            stamps.append(int(candidate.stat().st_mtime))
        except OSError:
            continue
    for change in worktree.changes:
        try:
            stamps.append(int((worktree.path / change.path).stat().st_mtime))
        except OSError:
            continue
    return max(stamps) if stamps else None


def _worktrees(repo: Path) -> list[Worktree]:
    raw = _git(repo, "worktree", "list", "--porcelain", "-z").stdout
    worktrees = _parse_worktree_records(raw)
    for worktree in worktrees:
        if worktree.bare:
            continue
        worktree.directory_missing = not worktree.path.is_dir()
        if worktree.directory_missing:
            worktree.status_error = "worktree directory is gone"
            continue
        result = _git(
            worktree.path,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            check=False,
        )
        if result.returncode:
            worktree.status_error = result.stderr.strip() or "status unavailable"
        else:
            worktree.changes = _parse_changes(result.stdout)
        worktree.mtime_epoch = _worktree_mtime(worktree)
    return worktrees


def _refs(repo: Path) -> list[Ref]:
    fields = (
        "%(refname)",
        "%(refname:short)",
        "%(objectname)",
        "%(objectname:short)",
        "%(upstream)",
        "%(upstream:short)",
        "%(committerdate:relative)",
        "%(subject)",
        "%(symref)",
        # Wall-clock seconds. The relative form above is for humans; every age
        # this module computes is arithmetic on this one.
        "%(committerdate:unix)",
    )
    result = _git(
        repo,
        "for-each-ref",
        "--sort=refname",
        "--format=" + "%00".join(fields),
        "refs/heads",
        "refs/remotes",
    )
    refs: list[Ref] = []
    for line in result.stdout.splitlines():
        parts = line.split("\0")
        if len(parts) != len(fields):
            raise GitError(f"could not parse a Git ref record in {repo}")
        refs.append(Ref(*parts))
    return refs


def _ref_exists(repo: Path, ref: str) -> bool:
    result = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return result.returncode == 0


def _base_ref(repo: Path) -> str | None:
    for ref in ("refs/heads/main", "refs/remotes/origin/main"):
        if _ref_exists(repo, ref):
            return ref
    return None


@dataclass
class MergeProbe:
    """How ``merged`` is decided for one repository, and where it writes.

    THE TEST IS CONTENT CONTAINMENT, not ancestry::

        merged(base, branch)  ==  (git merge-tree --write-tree base branch)
                                  == base^{tree}

    "merging this branch into main would change nothing." Two measured facts
    force it:

    * ``git branch --merged`` and ``git cherry`` MISS squash-merges — the
      dominant way work lands here — so an ancestry answer calls a finished
      branch unmerged and branches pile up. That is the accumulation this
      dashboard exists to surface.
    * ``git patch-id`` IGNORES WHITESPACE: an 8-space and a 2-space Python
      indent of the same line produce the IDENTICAL patch id. In a tree where
      Python and YAML indentation is semantic, any patch-id probe can declare
      genuinely unique work already merged. That is a data-loss answer, so no
      patch-id probe is used anywhere in this module.

    Two properties of the containment test are deliberate, not bugs:

    * a merged-then-REVERTED branch reads ``merged``. Its content is still
      reachable in main's history, so nothing is lost by treating it as done.
    * a branch whose only commit is EMPTY reads ``merged``. It contributes no
      content; only its commit message is unique, and the cleanup planner
      writes a backup ref before anything is proposed for deletion.

    ``--write-tree`` writes real tree objects into the object store. They are
    harmless and gc-able, but a read-only dashboard should not leave litter in
    the owner's repository, so writes are redirected into a throwaway directory
    with ``GIT_OBJECT_DIRECTORY`` while ``GIT_ALTERNATE_OBJECT_DIRECTORIES``
    (ABSOLUTE — a relative alternate resolves against the wrong directory)
    keeps every real object readable. Verified: the real object store gains 0
    files and ``git fsck`` stays clean.
    """

    mode: str
    note: str | None = None
    env: dict[str, str] | None = None
    sandbox: Path | None = None

    @property
    def degraded(self) -> bool:
        return self.mode != PROBE_MERGE_TREE

    def close(self) -> None:
        if self.sandbox is not None:
            shutil.rmtree(self.sandbox, ignore_errors=True)
            self.sandbox = None


def git_version(repo: Path) -> tuple[int, ...]:
    """``(major, minor, patch)`` for the Git that will answer our queries."""
    result = _git(repo, "--version", check=False)
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", result.stdout)
    if result.returncode or not match:
        return ()
    return tuple(int(part) for part in match.groups() if part is not None)


def open_merge_probe(repo: Path) -> MergeProbe:
    """Pick the merge probe for ``repo`` — and say so out loud when degrading.

    An older Git cannot run the containment test. The fallback is the ancestor
    test, which errs in exactly one direction: it under-reports ``merged``
    (squash-merges read ``unmerged``), so nothing is ever proposed for deletion
    on its say-so. It is never selected silently — the note it carries is
    printed by the dashboard and refuses the cleanup planner outright.
    """
    version = git_version(repo)
    if not version or version < MERGE_TREE_MIN_VERSION:
        return MergeProbe(mode=PROBE_ANCESTOR_ONLY, note=PROBE_DEGRADED_NOTE)
    objects = _git(repo, "rev-parse", "--git-path", "objects", check=False)
    if objects.returncode:
        return MergeProbe(mode=PROBE_ANCESTOR_ONLY, note=PROBE_DEGRADED_NOTE)
    real = Path(objects.stdout.strip())
    if not real.is_absolute():
        real = repo / real
    try:
        sandbox = Path(tempfile.mkdtemp(prefix="workspace-merge-probe-"))
    except OSError:
        return MergeProbe(mode=PROBE_ANCESTOR_ONLY, note=PROBE_DEGRADED_NOTE)
    return MergeProbe(
        mode=PROBE_MERGE_TREE,
        env={
            "GIT_OBJECT_DIRECTORY": str(sandbox),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(real.resolve()),
        },
        sandbox=sandbox,
    )


def _base_tree(repo: Path, base_ref: str | None) -> str | None:
    if base_ref is None:
        return None
    result = _git(repo, "rev-parse", f"{base_ref}^{{tree}}", check=False)
    if result.returncode:
        return None
    return result.stdout.strip() or None


def _merged_state(
    repo: Path,
    ref: str,
    base_ref: str | None,
    probe: MergeProbe | None = None,
    base_tree: str | None = None,
) -> str:
    if base_ref is None:
        return "main missing"
    if ref == base_ref:
        return "main"
    if probe is not None and not probe.degraded and base_tree:
        result = _git(
            repo,
            "merge-tree",
            "--write-tree",
            base_ref,
            ref,
            check=False,
            env=probe.env,
        )
        head = result.stdout.split("\n", 1)[0].strip()
        # Exit 1 with a tree on stdout is a CONFLICTING merge — a real answer
        # ("merging would change main"). Exit 1 with nothing on stdout is a ref
        # that does not resolve, and 128 is an unrelated history. Neither is
        # evidence of anything, so neither is allowed to read as merged.
        if result.returncode in (0, 1) and _OID_RE.match(head):
            return "merged" if head == base_tree else "unmerged"
        return _MERGED_UNKNOWN
    result = _git(
        repo,
        "merge-base",
        "--is-ancestor",
        ref,
        base_ref,
        check=False,
    )
    if result.returncode == 0:
        return "merged"
    if result.returncode == 1:
        return "unmerged"
    raise GitError(result.stderr.strip() or f"could not compare {ref} with main")


# ── intent (Component 1: git's own branch descriptions) ──────────────────────

def branch_descriptions(repo: Path) -> dict[str, str]:
    """``{branch: description}`` from ``branch.<name>.description``.

    Git already has an idiomatic place to say what a branch is for, and it has
    every property a lifecycle record needs and none of the costs: multi-line,
    stored in ``.git/config``, SHARED across every linked worktree, survives
    ``git clean -xfd`` and ``git gc --prune=now``, invisible to ``git status``
    and ``git log``, never pushed, enumerable in one command, and editable by
    the owner with ``git branch --edit-description``. No schema, no template,
    no gate, no new record type.

    ``-z`` is required: a description is multi-line, and without it a value's
    own newlines are indistinguishable from the line breaks between entries.
    The ``-z`` record is ``key\\nvalue\\0``.
    """
    result = _git(
        repo, "config", "-z", "--get-regexp", r"^branch\..*\.description$",
        check=False, acceptable=(1,),
    )
    descriptions: dict[str, str] = {}
    if result.returncode not in (0, 1):
        return descriptions
    for record in result.stdout.split("\0"):
        if not record:
            continue
        key, _, value = record.partition("\n")
        if not key.startswith("branch.") or not key.endswith(".description"):
            continue
        name = key[len("branch."):-len(".description")]
        if name:
            descriptions[name] = value
    return descriptions


def _first_commit_subject(repo: Path, ref: str, base_ref: str | None) -> str:
    """Subject of the OLDEST commit this ref has that the base does not.

    The first commit of a branch says what the branch was started for; the tip
    says what happened most recently. When no description exists, the first
    commit is the better guess at intent — and it is gated (a commit message is
    reviewed), which is why it is preferred over anything an agent might write.
    """
    if base_ref is None or ref == base_ref:
        return ""
    result = _git(repo, "log", "--reverse", "--format=%s", f"{base_ref}..{ref}",
                  check=False)
    if result.returncode:
        return ""
    for line in result.stdout.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _next_action(description: str) -> str | None:
    """The optional ``next: <single next action>`` line of a description."""
    for line in description.splitlines()[1:]:
        stripped = line.strip()
        if stripped.lower().startswith("next:"):
            return stripped[len("next:"):].strip() or None
    return None


def _intent(
    repo: Path,
    name: str,
    ref: Ref,
    base_ref: str | None,
    descriptions: dict[str, str],
) -> tuple[str, str, str | None]:
    """``(intent, source, next_action)`` — described, else derived, else tip."""
    described = descriptions.get(name, "")
    if described.strip():
        first = next((line.strip() for line in described.splitlines() if line.strip()), "")
        return first, INTENT_DESCRIPTION, _next_action(described)
    first_commit = _first_commit_subject(repo, ref.full_name, base_ref)
    if first_commit:
        return first_commit, INTENT_FIRST_COMMIT, None
    if ref.subject.strip():
        return ref.subject.strip(), INTENT_TIP_COMMIT, None
    return "", INTENT_NONE, None


# ── state (Component 2: derived, never stored) ───────────────────────────────

def _age_seconds(evidence_epoch: int | None, now: float) -> int | None:
    """Wall-clock age, clamped at zero.

    Wall clock steps BACKWARDS on an NTP correction and on resume-from-suspend,
    which would otherwise produce a negative age and a branch that reads
    "committed in the future".
    """
    if evidence_epoch is None:
        return None
    return max(0, int(now) - evidence_epoch)


def lifecycle_state(
    *,
    merged: str,
    upstream_missing: bool,
    wedged: bool,
    locked: bool,
    age_seconds: int | None,
) -> str:
    """First match wins. Nothing here is stored; every input is read from Git.

    Order matters. ``wedged`` outranks everything because it is the one state
    that BLOCKS work (the branch cannot be checked out until
    ``git worktree prune`` runs) and the one a locked registration hides.
    ``merged`` outranks the age bands because a merged branch's age is no
    longer interesting. A LOCKED worktree reads ``active`` however old it is:
    a lock is a deliberate finalizer set by a human or a live session, and
    treating it as stale is how a tool talks somebody into deleting live work.
    """
    if wedged:
        return STATE_WEDGED
    if merged == "merged":
        return STATE_MERGED
    if upstream_missing:
        return STATE_ORPHANED
    if locked:
        return STATE_ACTIVE
    if age_seconds is None:
        return STATE_STALE
    if age_seconds < ACTIVE_MAX_SECONDS:
        return STATE_ACTIVE
    if age_seconds < IDLE_MAX_SECONDS:
        return STATE_IDLE
    return STATE_STALE


def _divergence(repo: Path, local_ref: str, upstream_ref: str) -> tuple[int, int]:
    result = _git(repo, "rev-list", "--left-right", "--count", f"{local_ref}...{upstream_ref}")
    left, right = result.stdout.strip().split()
    return int(left), int(right)


def _branches(
    repo: Path,
    worktrees: Sequence[Worktree],
    probe: MergeProbe | None = None,
    pr_index: dict[str, str] | None = None,
    now: float | None = None,
) -> tuple[list[Branch], int, int, str | None]:
    now = time.time() if now is None else now
    refs = _refs(repo)
    locals_ = [ref for ref in refs if ref.full_name.startswith("refs/heads/")]
    remotes = {
        ref.full_name: ref
        for ref in refs
        if ref.full_name.startswith("refs/remotes/") and not ref.symbolic_target
    }
    checked_out = {
        worktree.branch_ref: worktree.path
        for worktree in worktrees
        if worktree.branch_ref
    }
    # A registration whose directory is gone still owns the branch name.
    wedged_at = {
        worktree.branch_ref: worktree.path
        for worktree in worktrees
        if worktree.branch_ref and worktree.gone
    }
    locked_refs = {
        worktree.branch_ref
        for worktree in worktrees
        if worktree.branch_ref and worktree.locked is not None and not worktree.gone
    }
    worktree_mtimes = {
        worktree.branch_ref: worktree.mtime_epoch
        for worktree in worktrees
        if worktree.branch_ref and worktree.mtime_epoch is not None
    }
    base_ref = _base_ref(repo)
    base_tree = _base_tree(repo, base_ref) if probe is not None else None
    descriptions = branch_descriptions(repo)
    consumed: set[str] = set()
    branches: list[Branch] = []

    def lifecycle(ref: Ref) -> dict:
        """Every derived field for one ref, in one place (local and remote)."""
        intent, intent_source, next_action = _intent(
            repo, ref.short_name, ref, base_ref, descriptions)
        tip = ref.committed_at
        mtime = worktree_mtimes.get(ref.full_name)
        evidence, source = tip, "tip-commit"
        if mtime is not None and (evidence is None or mtime > evidence):
            evidence, source = mtime, "worktree-mtime"
        age = _age_seconds(evidence, now)
        return {
            "intent": intent,
            "intent_source": intent_source,
            "next_action": next_action,
            "evidence_epoch": evidence,
            "evidence_source": source,
            "age_seconds": age,
            "wedged_at": wedged_at.get(ref.full_name),
            "locked": ref.full_name in locked_refs,
            "pr": (pr_index or {}).get(ref.short_name),
        }

    for ref in locals_:
        upstream = remotes.get(ref.upstream_ref) if ref.upstream_ref else None
        upstream_missing = bool(ref.upstream_ref and upstream is None)
        ahead = behind = None
        if upstream is not None:
            ahead, behind = _divergence(repo, ref.full_name, upstream.full_name)
            consumed.add(upstream.full_name)
        merged = _merged_state(repo, ref.full_name, base_ref, probe, base_tree)
        derived = lifecycle(ref)
        branches.append(
            Branch(
                scope="L+R" if upstream is not None else "L",
                name=ref.short_name,
                ref=ref,
                upstream=upstream,
                upstream_missing=upstream_missing,
                ahead=ahead,
                behind=behind,
                merged=merged,
                worktree_path=checked_out.get(ref.full_name),
                state=lifecycle_state(
                    merged=merged,
                    upstream_missing=upstream_missing,
                    wedged=derived["wedged_at"] is not None,
                    locked=derived["locked"],
                    age_seconds=derived["age_seconds"],
                ),
                **derived,
            )
        )

    for ref in remotes.values():
        if ref.full_name in consumed:
            continue
        merged = _merged_state(repo, ref.full_name, base_ref, probe, base_tree)
        derived = lifecycle(ref)
        branches.append(
            Branch(
                scope="R",
                name=ref.short_name,
                ref=ref,
                upstream=None,
                upstream_missing=False,
                ahead=None,
                behind=None,
                merged=merged,
                worktree_path=None,
                state=lifecycle_state(
                    merged=merged,
                    upstream_missing=False,
                    wedged=False,
                    locked=False,
                    age_seconds=derived["age_seconds"],
                ),
                **derived,
            )
        )

    branches.sort(key=lambda branch: (branch.name != "main", branch.name.casefold(), branch.scope))
    return branches, len(locals_), len(remotes), base_ref


def _redact_url(url: str) -> str:
    return re.sub(r"(?P<scheme>^[a-z][a-z0-9+.-]*://)[^/@]+@", r"\g<scheme>***@", url)


def _remotes(repo: Path) -> list[Remote]:
    names = [name for name in _git(repo, "remote").stdout.splitlines() if name]
    remotes: list[Remote] = []
    for name in sorted(names):
        result = _git(repo, "remote", "get-url", name, check=False)
        url = _redact_url(result.stdout.strip()) if result.returncode == 0 else "(URL unavailable)"
        remotes.append(Remote(name=name, url=url))
    return remotes


def pull_request_index(root: Path, timeout: float = 20.0) -> tuple[dict[str, str], str | None]:
    """``({branch: "#12 OPEN"}, error)`` from ``gh`` — the ONE network call here.

    GitHub is the authority on whether work is done, and nothing local can
    answer it. That is also why this is opt-in (``--pr``): the dashboard is the
    mandated preflight and must stay instant and offline by default, per its
    own "remote state is cached; no fetch was performed" contract.

    One ``gh pr list`` covers every branch. Any failure — ``gh`` absent, not
    authenticated, no GitHub remote, a timeout — returns the reason, never a
    guess; an absent PR and an unanswerable question must not look alike.
    """
    if shutil.which("gh") is None:
        return {}, "gh is not installed"
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "all", "--limit", "200",
             "--json", "number,headRefName,state,isDraft"],
            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, f"gh pr list failed: {exc}"
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        return {}, f"gh pr list exited {result.returncode}: {detail[0] if detail else ''}"
    try:
        records = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return {}, "gh pr list returned output that is not JSON"
    index: dict[str, str] = {}
    for record in records:
        head = record.get("headRefName")
        if not head or head in index:  # newest first; keep the newest PR
            continue
        label = f"#{record.get('number')} {record.get('state', '?')}"
        if record.get("isDraft"):
            label += " draft"
        index[head] = label
    return index, None


def inspect_repository(
    label: str,
    root: Path,
    *,
    want_pr: bool = False,
    now: float | None = None,
) -> Repository:
    worktrees = _worktrees(root)
    pr_index: dict[str, str] = {}
    pr_error: str | None = None
    if want_pr:
        pr_index, pr_error = pull_request_index(root)
    probe = open_merge_probe(root)
    try:
        branches, local_count, remote_count, base_ref = _branches(
            root, worktrees, probe, pr_index, now)
    finally:
        probe.close()
    return Repository(
        label=label,
        root=root.resolve(),
        worktrees=worktrees,
        branches=branches,
        remotes=_remotes(root),
        local_ref_count=local_count,
        remote_ref_count=remote_count,
        base_ref=base_ref,
        merge_probe=probe.mode,
        merge_probe_note=probe.note,
        pr_requested=want_pr,
        pr_error=pr_error,
    )


def discover_repositories(root: Path) -> list[tuple[str, Path]]:
    repos = [("PUBLIC", root.resolve())]
    private = root / "private"
    if _git_toplevel(private) == private.resolve():
        repos.append(("PRIVATE", private.resolve()))
    return repos


def _count(noun: str, amount: int) -> str:
    if amount == 1:
        rendered = noun
    elif noun.endswith("y") and not noun.endswith(("ay", "ey", "iy", "oy", "uy")):
        rendered = noun[:-1] + "ies"
    else:
        rendered = noun + "s"
    return f"{amount} {rendered}"


def _short_path(path: Path, workspace_root: Path) -> str:
    try:
        relative = path.resolve().relative_to(workspace_root.resolve())
        return "." if not relative.parts else str(relative)
    except (OSError, ValueError):
        try:
            return "~" + os.sep + str(path.resolve().relative_to(Path.home().resolve()))
        except (OSError, ValueError):
            return str(path)


def _safe_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def _worktree_state(worktree: Worktree) -> str:
    if worktree.status_error:
        return "status unavailable"
    if not worktree.changes:
        return "clean"
    pieces = [f"dirty {len(worktree.changes)}"]
    if worktree.staged:
        pieces.append(f"S{worktree.staged}")
    if worktree.unstaged:
        pieces.append(f"M{worktree.unstaged}")
    if worktree.untracked:
        pieces.append(f"?{worktree.untracked}")
    if worktree.conflicts:
        pieces.append(f"!{worktree.conflicts}")
    return " · ".join(pieces)


def _merged_style(state: str, palette: Palette) -> str:
    if state in {"main", "merged"}:
        return palette.GREEN
    if state == "unmerged":
        return palette.YELLOW
    return palette.RED


def _state_style(state: str, palette: Palette) -> str:
    if state == STATE_ACTIVE:
        return palette.GREEN
    if state == STATE_IDLE:
        return palette.CYAN
    if state == STATE_MERGED:
        return palette.BLUE
    if state == STATE_STALE:
        return palette.YELLOW
    return palette.RED


def _age_text(seconds: int | None) -> str:
    """A width-bounded wall-clock age: ``12m``, ``3h``, ``5d``, ``11w``."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    if seconds < 86400 * 21:
        return f"{seconds // 86400}d"
    return f"{seconds // (86400 * 7)}w"


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[:max(0, width - 1)] + "…"


def render(
    repositories: Sequence[Repository],
    workspace_root: Path,
    verbose: bool,
    palette: Palette,
    stale_days: int | None = None,
) -> str:
    total_worktrees = sum(len(repo.worktrees) for repo in repositories)
    dirty = sum(1 for repo in repositories for worktree in repo.worktrees if worktree.dirty)
    local_refs = sum(repo.local_ref_count for repo in repositories)
    remote_refs = sum(repo.remote_ref_count for repo in repositories)
    summary = (
        f"{_count('repository', len(repositories))} · {_count('worktree', total_worktrees)} · "
        f"{dirty} dirty · {local_refs} local + {remote_refs} cached remote branches"
    )
    lines = [
        f"{palette.paint('GIT WORKSPACE', palette.BOLD, palette.CYAN)}  {summary}",
        palette.paint("Remote state is cached; no fetch was performed.", palette.DIM),
    ]

    for repo in repositories:
        lines.append("")
        repo_color = palette.BLUE if repo.label == "PUBLIC" else palette.MAGENTA
        heading = f"{repo.label} · {repo.root.name}"
        lines.append(palette.paint(heading, palette.BOLD, repo_color))
        if verbose:
            lines.append(f"  {repo.root}")
        dirty_repo = sum(1 for worktree in repo.worktrees if worktree.dirty)
        lines.append(
            palette.paint(
                f"  {_count('worktree', len(repo.worktrees))} · {dirty_repo} dirty · "
                f"{repo.local_ref_count} local + {repo.remote_ref_count} cached remote branches",
                palette.DIM,
            )
        )
        if repo.merge_probe_note:
            lines.append(palette.paint(f"  {repo.merge_probe_note}", palette.RED))
        if repo.pr_error:
            lines.append(palette.paint(
                f"  pull-request state unavailable: {repo.pr_error}", palette.RED))

        lines.append(palette.paint(f"  WORKTREES ({len(repo.worktrees)})", palette.BOLD))
        branch_width = max((len(worktree.branch) for worktree in repo.worktrees), default=1)
        state_width = max(
            (len(_worktree_state(worktree)) for worktree in repo.worktrees),
            default=1,
        )
        for worktree in repo.worktrees:
            state = _worktree_state(worktree)
            if worktree.status_error:
                symbol = palette.paint("×", palette.RED)
                state_text = palette.paint(state, palette.RED)
            elif worktree.dirty:
                symbol = palette.paint("●", palette.YELLOW)
                state_text = palette.paint(state, palette.YELLOW)
            else:
                symbol = palette.paint("●", palette.GREEN)
                state_text = palette.paint(state, palette.GREEN)
            path = _short_path(worktree.path, workspace_root)
            lines.append(
                f"    {symbol} {worktree.branch:<{branch_width}}  "
                f"{state_text}{' ' * (state_width - len(state))}  {path}"
            )
            admin = []
            if worktree.locked is not None:
                admin.append("locked" + (f": {worktree.locked}" if worktree.locked else ""))
            if worktree.prunable is not None:
                admin.append("prunable" + (f": {worktree.prunable}" if worktree.prunable else ""))
            if verbose and admin:
                lines.append(palette.paint("      " + " · ".join(admin), palette.RED))
            if verbose and worktree.status_error:
                lines.append(palette.paint(f"      {worktree.status_error}", palette.RED))
            if verbose:
                for change in worktree.changes:
                    path_text = _safe_path(change.path)
                    if change.old_path:
                        path_text = f"{_safe_path(change.old_path)} → {path_text}"
                    lines.append(f"      {change.code}  {path_text}")

        shown = list(repo.branches)
        hidden = 0
        if stale_days is not None:
            threshold = stale_days * 86400
            kept = [b for b in shown
                    if b.age_seconds is not None and b.age_seconds >= threshold]
            hidden = len(shown) - len(kept)
            shown = kept
        branch_count = _count("row", len(shown))
        heading = f"  BRANCHES ({branch_count})"
        if stale_days is not None:
            heading += f" — untouched for {stale_days}+ days; {hidden} newer row(s) hidden"
        lines.append(palette.paint(heading, palette.BOLD))
        name_width = min(28, max((len(branch.name) for branch in shown), default=1))
        sync_width = max((len(branch.sync) for branch in shown), default=1)
        state_width = max((len(branch.state) for branch in shown), default=1)
        merged_width = max((len(branch.merged) for branch in shown), default=1)
        pr_width = max((len(branch.pr or "—") for branch in shown), default=1)
        for branch in shown:
            marker = "*" if branch.worktree_path else " "
            scope_color = palette.CYAN if branch.scope == "L+R" else (
                palette.BLUE if branch.scope == "L" else palette.MAGENTA
            )
            scope = palette.paint(f"{branch.scope:<3}", scope_color)
            merged = palette.paint(
                f"{branch.merged:<{merged_width}}",
                _merged_style(branch.merged, palette),
            )
            state = palette.paint(
                f"{branch.state:<{state_width}}",
                _state_style(branch.state, palette),
            )
            row = (
                f"    {marker} {scope}  {_truncate(branch.name, name_width):<{name_width}}  "
                f"{state}  {_age_text(branch.age_seconds):>4}  "
                f"{branch.sync:<{sync_width}}  {merged}"
            )
            if repo.pr_requested:
                row += f"  {(branch.pr or '—'):<{pr_width}}"
            row += f"  {_truncate(branch.intent, INTENT_WIDTH)}"
            lines.append(row.rstrip())
            if verbose:
                lines.append(
                    palette.paint(
                        f"        {branch.ref.short_oid} · {branch.ref.relative_date} · "
                        f"{branch.ref.subject}",
                        palette.DIM,
                    )
                )
                details = []
                if branch.upstream is not None:
                    details.append(f"upstream {branch.upstream.short_name}")
                elif branch.upstream_missing:
                    expected = branch.ref.upstream_short or branch.ref.upstream_ref
                    details.append(f"expected {expected}")
                if branch.worktree_path:
                    location = _short_path(branch.worktree_path, workspace_root)
                    details.append(f"checked out at {location}")
                details.append(f"intent from {branch.intent_source}")
                details.append(f"age from {branch.evidence_source}")
                if branch.locked:
                    details.append("worktree locked")
                if details:
                    lines.append(palette.paint("        " + " · ".join(details), palette.DIM))
                if branch.next_action:
                    lines.append(palette.paint(
                        f"        next: {branch.next_action}", palette.DIM))
                if branch.wedged_at is not None:
                    lines.append(palette.paint(
                        "        WEDGED: a worktree registration at "
                        f"{_short_path(branch.wedged_at, workspace_root)} still owns "
                        "this branch but its directory is gone — `git switch` will "
                        "refuse until `git worktree prune` runs",
                        palette.RED,
                    ))

        if verbose and repo.remotes:
            lines.append(palette.paint("  REMOTES", palette.BOLD))
            for remote in repo.remotes:
                lines.append(f"    {remote.name:<10}  {remote.url}")
        if verbose and repo.base_ref is None:
            lines.append(
                palette.paint(
                    "  No local or origin/main ref; merge state is unavailable.",
                    palette.RED,
                )
            )

    lines.extend(
        [
            "",
            palette.paint(
                "Legend: * checked out · L local · R cached remote · "
                "merged = merging it into local main would change nothing "
                "(catches squash-merges)",
                palette.DIM,
            ),
            palette.paint(
                "State (derived, never stored): active <30m · idle <24h · stale "
                "older · merged contained by main · orphaned upstream gone · "
                "wedged worktree registration outlived its directory. Age is the "
                "newest of the tip commit date and the worktree's own files.",
                palette.DIM,
            ),
            palette.paint(
                "Intent: `git branch --edit-description` (shared across worktrees, "
                "never pushed); otherwise the branch's first commit subject.",
                palette.DIM,
            ),
        ]
    )
    return "\n".join(lines)


# ── machine-readable output ──────────────────────────────────────────────────

def _worktree_json(worktree: Worktree) -> dict:
    return {
        "bare": worktree.bare,
        "branch": worktree.branch,
        "branch_ref": worktree.branch_ref,
        "changes": [
            {"code": change.code, "path": change.path, "old_path": change.old_path}
            for change in worktree.changes
        ],
        "conflicts": worktree.conflicts,
        "detached": worktree.detached,
        "directory_missing": worktree.directory_missing,
        "dirty": worktree.dirty,
        "gone": worktree.gone,
        "head": worktree.head,
        "locked": worktree.locked,
        "mtime_epoch": worktree.mtime_epoch,
        "path": str(worktree.path),
        "prunable": worktree.prunable,
        "staged": worktree.staged,
        "status_error": worktree.status_error,
        "unstaged": worktree.unstaged,
        "untracked": worktree.untracked,
    }


def _branch_json(branch: Branch) -> dict:
    return {
        "ahead": branch.ahead,
        "age_seconds": branch.age_seconds,
        "behind": branch.behind,
        "evidence_epoch": branch.evidence_epoch,
        "evidence_source": branch.evidence_source,
        "intent": branch.intent,
        "intent_source": branch.intent_source,
        "locked": branch.locked,
        "merged": branch.merged,
        "name": branch.name,
        "next_action": branch.next_action,
        "oid": branch.ref.oid,
        "pull_request": branch.pr,
        "ref": branch.ref.full_name,
        "scope": branch.scope,
        "state": branch.state,
        "subject": branch.ref.subject,
        "sync": branch.sync,
        "upstream": branch.upstream.short_name if branch.upstream else None,
        "upstream_missing": branch.upstream_missing,
        "wedged_at": str(branch.wedged_at) if branch.wedged_at else None,
        "worktree_path": str(branch.worktree_path) if branch.worktree_path else None,
    }


def repository_json(repo: Repository) -> dict:
    return {
        "base_ref": repo.base_ref,
        "branches": [_branch_json(branch) for branch in repo.branches],
        "label": repo.label,
        "local_ref_count": repo.local_ref_count,
        "merge_probe": repo.merge_probe,
        "merge_probe_note": repo.merge_probe_note,
        "pull_request_error": repo.pr_error,
        "pull_requests_requested": repo.pr_requested,
        "remote_ref_count": repo.remote_ref_count,
        "remotes": [{"name": r.name, "url": r.url} for r in repo.remotes],
        "root": str(repo.root),
        "worktrees": [_worktree_json(worktree) for worktree in repo.worktrees],
    }


def workspace_json(repositories: Sequence[Repository], now: float | None = None) -> dict:
    """The whole model, exactly as the table renders it — one schema, one truth.

    Ages are seconds and instants are Unix seconds (wall clock, UTC): a consumer
    must never have to parse a relative phrase like "3 days ago" back into time.
    """
    moment = time.time() if now is None else now
    return {
        "fetched": False,
        "generated_at": datetime.datetime.fromtimestamp(
            moment, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_epoch": int(moment),
        "repositories": [repository_json(repo) for repo in repositories],
        "schema": JSON_SCHEMA,
        "states": list(STATES),
        "thresholds": {
            "active_max_seconds": ACTIVE_MAX_SECONDS,
            "idle_max_seconds": IDLE_MAX_SECONDS,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Show worktrees and local/cached-remote branch state for this toolkit "
            "and its optional private overlay."
        )
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show changed files, commits, remotes, and worktree flags",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize output (default: auto)",
    )
    parser.add_argument("--no-color", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the whole model as JSON instead of the table",
    )
    parser.add_argument(
        "--stale",
        type=int,
        metavar="DAYS",
        help="show only branches untouched for DAYS or more (wall clock; the "
             "newest of the tip commit date and the worktree's own files)",
    )
    parser.add_argument(
        "--pr",
        action="store_true",
        help="ask GitHub for each branch's pull-request state via `gh` "
             "(the only network call this command can make; off by default)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.stale is not None and args.stale < 0:
        print("workspace status: --stale takes a non-negative number of days",
              file=sys.stderr)
        return 2
    try:
        validate_toolkit_root(REPO_ROOT)
        repositories = [
            inspect_repository(label, root, want_pr=args.pr)
            for label, root in discover_repositories(REPO_ROOT)
        ]
    except GitError as exc:
        print(f"workspace status: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(workspace_json(repositories), indent=2, sort_keys=True))
        return 0

    color_mode = "never" if args.no_color or os.environ.get("NO_COLOR") is not None else args.color
    use_color = color_mode == "always" or (color_mode == "auto" and sys.stdout.isatty())
    print(render(repositories, REPO_ROOT, args.verbose, Palette(use_color), args.stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
