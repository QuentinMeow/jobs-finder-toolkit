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
table to what nobody has touched (never the row you are standing on).

Three invariants this module is responsible for, all learned the hard way:

* THE PRIVATE OVERLAY IS NOT A PEER REPOSITORY. ``private/`` is a separate repo
  holding the owner's real identity. Everything it contributes to this output
  passes through ``redact_repository`` first — see the long note above it.
* THE CACHE HAS AN AGE, AND THE READER MUST SEE IT. Every ``merged`` and
  ``behind`` figure below is only as good as the last fetch, so each repository
  prints a CHECKOUT verdict carrying how far behind the checked-out branch is
  and how old the remote knowledge that says so actually is — measured against
  the base ref ``resolve_base`` picked, which is printed too.
* A FALSE ``merged`` IS THE ONLY ANSWER HERE THAT LOSES WORK. Every other
  wrong answer over-keeps a branch; this one authorises deleting it. So the
  containment probe treats any non-zero ``merge-tree`` exit as NO ANSWER — see
  ``_merged_state``.

Tests: ``.venv/bin/python -m unittest discover automation/workspace/tests``
"""

from __future__ import annotations

import argparse
import dataclasses
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

PUBLIC_LABEL = "PUBLIC"
PRIVATE_LABEL = "PRIVATE"
# The overlay's mount point. It is documented in the tracked AGENTS.md, so the
# word itself is public; nothing BELOW it is.
PRIVATE_MOUNT = "private"

# ── the base a branch is judged "merged" against ─────────────────────────────
#
# REMOTE-TRACKING FIRST. Measured on this workspace: the overlay's local `main`
# sat 4 commits behind its cached `origin/main`, and BOTH of its branches were
# ancestors of `origin/main` and of neither local `main` — so every one of them
# graded `unmerged`, permanently, because nothing ever fetches the overlay. The
# public checkout showed the same shape 88 commits deep. The error direction is
# conservative (it over-KEEPS finished work, it never proposes deleting live
# work), which is exactly why it hid for so long.
#
# `origin/main` is what local `main` is going to become; a local `main` that is
# behind is a strictly worse answer to "is this work already landed". The local
# ref is the fallback for a repository that has no remote-tracking ref at all.
# Whichever is used is PRINTED, because a base that silently rots is the defect.
BASE_REFS_REMOTE_FIRST = ("refs/remotes/origin/main", "refs/heads/main")

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

# ── how much this dashboard can be trusted (the CHECKOUT verdict) ───────────
#
# WHAT THE VERDICT MEASURES, AND WHY IT IS NOT "behind n". This repository
# merged 88 commits in 18 hours. A banner keyed on the commit count would be
# loud every single day, and a banner that is always loud is one nobody reads —
# so `behind n` is REPORTED as a calm fact and is not what colours the line.
#
# What actually degrades is the AGE OF THE REMOTE KNOWLEDGE. `behind n` and the
# whole `merged` column are computed against a CACHED remote ref, so a stale
# cache does not make the numbers alarming, it makes them WRONG — and wrong in
# the flattering direction: unfetched, an 88-commit gap renders `synced`. The
# age of the last fetch is therefore the one number that says how much of this
# table is fiction, and it is the number the verdict is keyed on.
#
# THE THRESHOLDS.
#   < 24h  `fresh`  — calm. 24h is this module's own definition of "a working
#                     day has passed" (IDLE_MAX_SECONDS below, "close the laptop
#                     at 6pm, reopen at 9am"); one notion of a day, not two.
#                     Being behind by any number of commits inside a working day
#                     is the normal state here, not an incident.
#   < 7d   `dated`  — a nudge, not an alarm. The numbers are still directionally
#                     right and a fetch is cheap.
#   >= 7d  `BLIND`  — loud, and rarely. At this repository's measured cadence a
#                     week is on the order of eight hundred commits: not "a bit
#                     out of date" but a different repository, in which `merged`
#                     and `behind` carry no information at all. This is the only
#                     state the tool is actively misleading in, so it is the only
#                     one that shouts.
#   never  `unknown` — a checkout that has never fetched (a fresh clone writes no
#                     FETCH_HEAD). Freshness cannot be established, which is a
#                     caveat, not a danger — so it warns, it does not shout.
# No exit code changes on any of these: the verdict informs, it does not gate.
CHECKOUT_DATED_SECONDS = 24 * 60 * 60
CHECKOUT_BLIND_SECONDS = 7 * 24 * 60 * 60

FRESHNESS_FRESH = "fresh"
FRESHNESS_DATED = "dated"
FRESHNESS_BLIND = "BLIND"
FRESHNESS_UNKNOWN = "unknown"
FRESHNESS_NO_REMOTE = "local-only"

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
        # The overlay's redaction blanks ``head``; an object id is not owner
        # prose, but neither is it worth printing for a repository whose
        # contents this tool refuses to describe.
        return f"(detached @{self.head[:8]})" if self.head else "(detached)"

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


@dataclass(frozen=True)
class Checkout:
    """The verdict for the branch the reader is standing on. See the note above.

    ``branch_ref`` is the join key back to that branch's row — redaction
    RELABELS it rather than blanking it, and ``_checkout_json`` never emits it,
    so it stays usable without ever carrying an overlay name out of the model.
    """

    branch: str
    branch_ref: str | None
    sync: str
    ahead: int | None
    behind: int | None
    freshness: str
    fetched_epoch: int | None
    knowledge_age_seconds: int | None


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
    checkout: Checkout | None = None
    # Set for the private overlay. Everything below it is already redacted; the
    # flag exists so the renderer can SKIP sections outright rather than trust
    # that every value inside them was scrubbed.
    private: bool = False
    # Real path -> what may be printed for it. Consulted only when ``private``,
    # and it FAILS CLOSED: an unmapped path renders as PATH_WITHHELD.
    path_display: dict[str, str] = field(default_factory=dict)


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


def resolve_base(repo: Path, *, prefer_remote: bool = True) -> str | None:
    """The ref a branch must be contained by, and the ONE implementation of it.

    Back-ported from ``cleanup.py``, which solved this for itself and never
    shared it — ``cleanup.resolve_base`` now delegates here, so the dashboard
    and the retirement planner can no longer drift apart on what "merged" means.

    ``prefer_remote`` is the only difference between the two callers, and it is
    a difference in what each has EARNED. The dashboard never fetches, so it
    reads the cached ``origin/main`` and says how old that cache is (see
    BASE_REFS_REMOTE_FIRST). The planner deletes things, so it prefers the
    remote base only once it has actually fetched one, and falls back to the
    local ref otherwise.
    """
    order = (BASE_REFS_REMOTE_FIRST if prefer_remote
             else tuple(reversed(BASE_REFS_REMOTE_FIRST)))
    for ref in order:
        if _ref_exists(repo, ref):
            return ref
    return None


def _fetch_head_epoch(repo: Path) -> int | None:
    """When anything in this repository last learned from a remote, or ``None``.

    ``FETCH_HEAD`` is a PER-WORKTREE file, and in this workspace agents fetch
    from linked worktrees constantly, so reading only the main worktree's copy
    reports the remote knowledge as older than it is. The newest across all of
    them is the honest answer to "when did this checkout last hear from origin".

    ``None`` means no ``FETCH_HEAD`` exists anywhere — a checkout that has never
    fetched. ``git clone`` writes none, so this is a real, benign state and is
    reported as ``unknown`` rather than as danger.
    """
    result = _git(repo, "rev-parse", "--git-common-dir", check=False)
    if result.returncode:
        return None
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = repo / common
    candidates = [common / "FETCH_HEAD"]
    try:
        candidates.extend(sorted((common / "worktrees").glob("*/FETCH_HEAD")))
    except OSError:
        pass
    stamps: list[int] = []
    for candidate in candidates:
        try:
            stamps.append(int(candidate.stat().st_mtime))
        except OSError:
            continue
    return max(stamps) if stamps else None


def checkout_freshness(*, has_remote: bool, age_seconds: int | None) -> str:
    """How much of this table is still true. Thresholds argued at the top."""
    if not has_remote:
        return FRESHNESS_NO_REMOTE
    if age_seconds is None:
        return FRESHNESS_UNKNOWN
    if age_seconds >= CHECKOUT_BLIND_SECONDS:
        return FRESHNESS_BLIND
    if age_seconds >= CHECKOUT_DATED_SECONDS:
        return FRESHNESS_DATED
    return FRESHNESS_FRESH


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
        # ── A NON-ZERO EXIT IS NEVER EVIDENCE OF CONTAINMENT ─────────────────
        #
        # This module's ONE data-loss risk is a false `merged`, because the
        # cleanup planner reads it as permission to propose a deletion. The
        # earlier rule accepted exit 1 (CONFLICT) and then compared trees, on
        # the reasoning that a conflict is still "a real answer". It is not,
        # and the counter-example is not exotic — MEASURED here, git 2.55:
        #
        #   * a branch whose only change edits a file git auto-detects as
        #     BINARY (a NUL byte anywhere in it) that main also edited:
        #     `merge-tree` exits 1 and its first stdout line IS THE BASE TREE,
        #     because a binary conflict is resolved by keeping "ours". The old
        #     rule read that as `merged` for a branch holding work that exists
        #     nowhere in main. This repository tracks 22 such files — DOCX and
        #     PDF resumes, JPGs, `.json.zst` blobs.
        #   * the same shape for a TEXT file marked `-merge` (or `binary`) in
        #     `.gitattributes` — no NUL byte, so nothing about the content
        #     warns you — and for a SUBMODULE pointer that diverged rather
        #     than fast-forwarded.
        #
        # So: exit 0 is the only exit whose tree answers the question. On any
        # non-zero exit the probe DID NOT ANSWER, and the verdict fails closed.
        #
        # One refinement, and it can only ever over-keep: a conflicted merge
        # whose tree DIFFERS from the base still proves that merging would
        # change main, which is this module's definition of not-contained — so
        # that case keeps the informative `unmerged` (it is what the `ws-variant`
        # add/add fixture is). A conflicted merge whose tree EQUALS the base is
        # exactly the masked case above and degrades to `unknown`, which every
        # consumer treats as "keep it" (cleanup.py: KEEP_UNKNOWN_MERGE).
        if not _OID_RE.match(head):
            # No tree at all: a ref that does not resolve (1), or an unrelated
            # history / usage error (128).
            return _MERGED_UNKNOWN
        if result.returncode == 0:
            return "merged" if head == base_tree else "unmerged"
        if head != base_tree:
            return "unmerged"
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
    base_ref = resolve_base(repo)
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


# ── the private overlay: structure and counts, never content ─────────────────
#
# WHY THIS EXISTS. ``private/`` is a git-ignored SEPARATE repository holding the
# owner's real identity — employers, applications, interview material, private
# skills. This dashboard is the MANDATED first command of every session
# (AGENTS.md, "Runtime Environment"), so whatever it prints lands in every
# agent's context every session, and in anything an agent then pastes into a
# public PR description, commit message or issue. Reproduced in a fabricated
# sandbox, one `-v` run printed an employer name inside a branch name, the same
# name in a commit subject, the owner's own `git branch --edit-description`
# prose, an `applications/<stage>/<employer>/` path and an absolute home path.
#
# ``cleanup.py`` (_private_counts) and ``gardener/workspace_hygiene.py``
# (_print_private) already answer this correctly — counts only, and they say so.
# This module was the one outlier, and this section makes it consistent.
#
# THE RULE. For the private repository this tool prints STRUCTURE, COUNTS, AGES
# and LIFECYCLE STATES, and nothing whose characters came out of the overlay.
# Concretely withheld: commit subjects, branch descriptions and their `next:`
# lines, changed-file paths, worktree paths, the overlay's absolute location,
# remote names and URLs, worktree lock/prunable reasons, and `gh` error text.
# Kept, because they are the useful part and none of them can carry a name:
# how many worktrees and branches there are, how dirty each is, how old
# everything is, and each branch's lifecycle and merge state.
#
# BRANCH NAMES — the hard case, and the rule. `codex/remove-resume-review-pdf`
# is mechanical and harmless; `codex/<employer>-onsite-loop` is not, and NOTHING
# MECHANICAL TELLS THEM APART. Three candidate rules; only one survives:
#
#   * A BLOCKLIST would have to enumerate every employer the owner might ever
#     apply to. That list IS the private data — a public tool cannot hold it,
#     and it fails OPEN on the first name nobody thought of.
#   * A HASH is not redaction of a low-entropy secret. A company name is drawn
#     from a small guessable set, so anyone holding the digest confirms a guess
#     by hashing candidates. It reads as safe and is not.
#   * AN ALLOWLIST is safe by CONSTRUCTION: a character can reach stdout only if
#     it is already a literal in this public source file. It fails CLOSED — an
#     unrecognised name degrades to an ordinal instead of leaking.
#
# So a private branch prints as an ORDINAL — `#3`, its position in this run's
# sorted branch list — optionally prefixed by its leading path segment WHEN AND
# ONLY WHEN that segment is one of the conventional, tool-generated prefixes in
# SAFE_BRANCH_PREFIXES. An ordinal has no preimage, and it still does the one
# job the name did here: it ties a worktree row to its branch row within a
# single run. `main`/`master` print verbatim because they are the base ref and
# are already literals in this file. To see the real names the owner runs
# `git -C private branch`, which prints to a terminal rather than into an
# agent's context.
SAFE_BRANCH_PREFIXES = frozenset({
    "build", "chore", "ci", "codex", "dev", "docs", "feat", "feature", "fix",
    "hotfix", "perf", "refactor", "release", "revert", "style", "test", "wip",
})
SAFE_BRANCH_NAMES = frozenset({"main", "master"})
SAFE_REMOTE_NAMES = frozenset({"origin", "upstream"})

PATH_WITHHELD = "(withheld — private overlay)"
REMOTE_WITHHELD = "(withheld — private overlay)"
PRIVATE_POLICY_NOTE = (
    "private overlay: structure, counts, ages and states only — branch names, "
    "commit subjects, descriptions, paths and remotes are withheld because this "
    "output is read into every agent session and pasted into public PRs. "
    "`git -C private branch` shows the real names, in your terminal."
)
PRIVATE_STATUS_ERROR = "status unavailable"
PRIVATE_PR_ERROR = "pull-request state unavailable"
PRIVATE_INSPECT_ERROR = (
    "the private overlay could not be inspected; git's own message is withheld "
    "because it names refs and files — rerun the failing command yourself with "
    "`git -C private ...` to see it"
)


def is_private_overlay(label: str, root: Path) -> bool:
    """Is this repository the overlay? TWO independent triggers, both cheap.

    The label is the ordinary one, and the LOCATION is the backstop: a caller
    that inspects ``<toolkit>/private`` under some other label — the gardener
    passes ``"REPO"`` — still gets a redacted model. A public repository whose
    own directory happens to be named ``private`` is redacted too; that error
    direction costs a little detail, and the other direction costs the owner's
    identity, so this one fails closed on purpose.
    """
    if label == PRIVATE_LABEL:
        return True
    try:
        return root.resolve().name == PRIVATE_MOUNT
    except OSError:
        return True


def redact_branch_label(name: str, ordinal: int, scope: str) -> str:
    """``main`` · ``codex/#3`` · ``origin/#3`` · ``#3``. Rule argued above."""
    prefix = ""
    rest = name
    if scope == "R":
        remote, _, rest = name.partition("/")
        if remote not in SAFE_REMOTE_NAMES or not rest:
            return f"#{ordinal}"
        prefix = remote + "/"
    if rest in SAFE_BRANCH_NAMES:
        return prefix + rest
    head, separator, _ = rest.partition("/")
    if separator and head in SAFE_BRANCH_PREFIXES:
        return f"{prefix}{head}/#{ordinal}"
    return f"{prefix}#{ordinal}"


def _redact_ref(ref: Ref, label: str, upstream_label: str) -> Ref:
    """A ``Ref`` stripped to what is mechanical: its dates and its shape."""
    kind = "refs/remotes/" if ref.full_name.startswith("refs/remotes/") else "refs/heads/"
    return Ref(
        full_name=kind + label,
        short_name=label,
        oid="",
        short_oid="",
        upstream_ref="" if not ref.upstream_ref else "refs/remotes/" + upstream_label,
        upstream_short="" if not ref.upstream_short else upstream_label,
        relative_date=ref.relative_date,
        subject="",
        symbolic_target="",
        committer_epoch=ref.committer_epoch,
    )


def redact_repository(repo: Repository) -> Repository:
    """Rebuild ``repo`` so every string left in it is safe to print.

    Redaction happens HERE, at the model boundary, rather than in the renderer:
    the table, ``-v`` and ``--json`` are three consumers and a fourth will be
    written some day, so the value a consumer receives has to be the safe one
    already. ``Repository.private`` then lets the renderer additionally skip
    whole sections instead of trusting this function to have been exhaustive.
    """
    labels = {
        branch.ref.full_name: redact_branch_label(branch.name, index + 1, branch.scope)
        for index, branch in enumerate(repo.branches)
    }
    # A checked-out branch is always a local head, so its label is already known;
    # the fallback exists only so an unexpected shape cannot leak a real name.
    def label_for(full_name: str | None) -> str:
        return labels.get(full_name or "", "#?")

    path_display: dict[str, str] = {}
    worktrees: list[Worktree] = []
    for index, worktree in enumerate(repo.worktrees):
        # `git worktree list` reports the MAIN worktree first, and for the
        # overlay that is the mount point itself — a path AGENTS.md already
        # names. Every other registration lives somewhere only the owner knows.
        display = PRIVATE_MOUNT if index == 0 else f"overlay worktree #{index + 1}"
        path_display[str(worktree.path)] = display
        worktrees.append(
            Worktree(
                path=worktree.path,
                head="",
                branch_ref=(None if worktree.branch_ref is None
                            else "refs/heads/" + label_for(worktree.branch_ref)),
                detached=worktree.detached,
                bare=worktree.bare,
                locked=None if worktree.locked is None else "",
                prunable=None if worktree.prunable is None else "",
                changes=[Change(code=change.code, path="", old_path=None)
                         for change in worktree.changes],
                status_error=(None if worktree.status_error is None
                              else PRIVATE_STATUS_ERROR),
                mtime_epoch=worktree.mtime_epoch,
                directory_missing=worktree.directory_missing,
            )
        )

    branches = []
    for index, branch in enumerate(repo.branches):
        label = labels[branch.ref.full_name]
        # The upstream carries the SAME ordinal as the row it belongs to, so
        # `#3 · upstream origin/#3` reads as one thing rather than two.
        upstream_label = redact_branch_label(
            branch.upstream.short_name if branch.upstream is not None
            else (branch.ref.upstream_short or "origin/?"),
            index + 1, "R")
        branches.append(
            dataclasses.replace(
                branch,
                name=label,
                ref=_redact_ref(branch.ref, label, upstream_label),
                upstream=(None if branch.upstream is None
                          else _redact_ref(branch.upstream, upstream_label, upstream_label)),
                intent="",
                intent_source=INTENT_NONE,
                next_action=None,
            )
        )

    return dataclasses.replace(
        repo,
        # Nothing downstream of inspection resolves this; it exists to be shown,
        # and what may be shown is the publicly documented mount point.
        root=Path(PRIVATE_MOUNT),
        worktrees=worktrees,
        branches=branches,
        remotes=[Remote(name=f"remote #{index + 1}", url=REMOTE_WITHHELD)
                 for index, _ in enumerate(repo.remotes)],
        pr_error=None if repo.pr_error is None else PRIVATE_PR_ERROR,
        checkout=(None if repo.checkout is None else dataclasses.replace(
            repo.checkout,
            branch=label_for(repo.checkout.branch_ref),
            # Relabelled, not blanked: the renderer joins this against the
            # branch rows to keep the checked-out row out of `--stale`, and the
            # label it now carries is already the public one.
            branch_ref=(None if repo.checkout.branch_ref is None
                        else "refs/heads/" + label_for(repo.checkout.branch_ref)),
        )),
        private=True,
        path_display=path_display,
    )


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


def _checkout(
    repo_root: Path,
    worktrees: Sequence[Worktree],
    branches: Sequence[Branch],
    remotes: Sequence[Remote],
    now: float,
) -> Checkout | None:
    """The verdict for the branch the reader is standing on.

    "Standing on" is the MAIN worktree's branch: ``git worktree list`` reports
    the main worktree first, and it is the one whose files a plain ``cd`` lands
    in. Linked worktrees each get their own row in the table below; the verdict
    is about the checkout the reader almost certainly means.
    """
    main_worktree = next((worktree for worktree in worktrees if not worktree.bare), None)
    if main_worktree is None:
        return None
    branch = next((item for item in branches
                   if item.ref.full_name == main_worktree.branch_ref), None)
    fetched_epoch = _fetch_head_epoch(repo_root)
    age = _age_seconds(fetched_epoch, now)
    return Checkout(
        branch=main_worktree.branch,
        branch_ref=main_worktree.branch_ref,
        sync=branch.sync if branch is not None else "no branch",
        ahead=branch.ahead if branch is not None else None,
        behind=branch.behind if branch is not None else None,
        freshness=checkout_freshness(has_remote=bool(remotes), age_seconds=age),
        fetched_epoch=fetched_epoch,
        knowledge_age_seconds=age,
    )


def inspect_repository(
    label: str,
    root: Path,
    *,
    want_pr: bool = False,
    now: float | None = None,
    private: bool | None = None,
) -> Repository:
    """Inspect one repository, redacting it when it is the private overlay.

    ``private`` defaults to ``is_private_overlay(label, root)``, which arms on
    the LABEL *or* on the location. Arming on the label alone would have made
    the guarantee depend on every caller picking the right string —
    ``gardener/workspace_hygiene.py`` already inspects the overlay under the
    label ``"REPO"`` — so location is the second, independent trigger. A caller
    may force redaction on; forcing it off is deliberate and explicit.

    A ``GitError`` raised while inspecting the overlay is REWRITTEN rather than
    propagated: ``_git`` builds its message out of the repository path and git's
    own stderr, and git's stderr names refs and files. That message is printed
    by ``main`` and would carry exactly what the rest of this function exists to
    withhold.
    """
    redact = is_private_overlay(label, root) if private is None else private
    try:
        repository = _inspect_repository(label, root, want_pr=want_pr, now=now)
    except GitError:
        if redact:
            raise GitError(PRIVATE_INSPECT_ERROR) from None
        raise
    return redact_repository(repository) if redact else repository


def _inspect_repository(
    label: str,
    root: Path,
    *,
    want_pr: bool = False,
    now: float | None = None,
) -> Repository:
    """The unredacted inspection. Only ``inspect_repository`` should call this."""
    moment = time.time() if now is None else now
    worktrees = _worktrees(root)
    pr_index: dict[str, str] = {}
    pr_error: str | None = None
    if want_pr:
        pr_index, pr_error = pull_request_index(root)
    probe = open_merge_probe(root)
    try:
        branches, local_count, remote_count, base_ref = _branches(
            root, worktrees, probe, pr_index, moment)
    finally:
        probe.close()
    remotes = _remotes(root)
    return Repository(
        label=label,
        root=root.resolve(),
        worktrees=worktrees,
        branches=branches,
        remotes=remotes,
        local_ref_count=local_count,
        remote_ref_count=remote_count,
        base_ref=base_ref,
        merge_probe=probe.mode,
        merge_probe_note=probe.note,
        pr_requested=want_pr,
        pr_error=pr_error,
        checkout=_checkout(root, worktrees, branches, remotes, moment),
    )


def discover_repositories(root: Path) -> list[tuple[str, Path]]:
    repos = [(PUBLIC_LABEL, root.resolve())]
    private = root / PRIVATE_MOUNT
    if _git_toplevel(private) == private.resolve():
        repos.append((PRIVATE_LABEL, private.resolve()))
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


def _display_path(repo: Repository, path: Path | None, workspace_root: Path) -> str:
    """The only way a path reaches the output. FAILS CLOSED for the overlay.

    For the private repository a path is printed only if ``redact_repository``
    put an explicit stand-in in ``path_display``; anything else — including a
    path a future edit starts passing through here — is withheld rather than
    guessed at.
    """
    if path is None:
        return ""
    if repo.private:
        return repo.path_display.get(str(path), PATH_WITHHELD)
    return _short_path(path, workspace_root)


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


def _sync_style(sync: str, palette: Palette) -> str:
    """``sync`` was the ONE column with no style path — the incident's hiding place.

    Reproduced with ``--color=always``: ``active`` and ``main`` carried
    ``\\033[32m`` while ``behind 88`` carried no escape at all, so the single
    token that said the checkout was 88 commits stale rendered exactly like
    surrounding punctuation.
    """
    if sync.startswith("diverged") or sync == "upstream missing":
        return palette.RED
    if sync.startswith("behind"):
        return palette.YELLOW
    if sync.startswith("ahead"):
        return palette.CYAN
    if sync == "synced":
        return palette.GREEN
    return palette.DIM


def _freshness_style(freshness: str, palette: Palette) -> str:
    if freshness == FRESHNESS_BLIND:
        return palette.RED
    if freshness in (FRESHNESS_DATED, FRESHNESS_UNKNOWN):
        return palette.YELLOW
    if freshness == FRESHNESS_FRESH:
        return palette.GREEN
    return palette.DIM


def _knowledge_text(checkout: Checkout) -> str:
    if checkout.freshness == FRESHNESS_NO_REMOTE:
        return "no remote configured"
    if checkout.knowledge_age_seconds is None:
        return "never fetched in this checkout"
    return f"remote knowledge {_age_text(checkout.knowledge_age_seconds)} old"


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
        palette.paint(
            "Remote state is cached; no fetch was performed — each CHECKOUT line "
            "below says how old that cache is.",
            palette.DIM,
        ),
    ]

    for repo in repositories:
        lines.append("")
        repo_color = palette.BLUE if repo.label == PUBLIC_LABEL else palette.MAGENTA
        heading = f"{repo.label} · {repo.root.name}"
        lines.append(palette.paint(heading, palette.BOLD, repo_color))
        if verbose:
            lines.append(f"  {repo.root}")
        if repo.private:
            lines.append(palette.paint(f"  {PRIVATE_POLICY_NOTE}", palette.DIM))
        dirty_repo = sum(1 for worktree in repo.worktrees if worktree.dirty)
        lines.append(
            palette.paint(
                f"  {_count('worktree', len(repo.worktrees))} · {dirty_repo} dirty · "
                f"{repo.local_ref_count} local + {repo.remote_ref_count} cached remote branches",
                palette.DIM,
            )
        )
        if repo.checkout is not None:
            checkout = repo.checkout
            row = (
                f"  {palette.paint('CHECKOUT', palette.BOLD)}  "
                f"{palette.paint(checkout.freshness, _freshness_style(checkout.freshness, palette))}  "
                f"{checkout.branch} · "
                f"{palette.paint(checkout.sync, _sync_style(checkout.sync, palette))} · "
                f"{_knowledge_text(checkout)}"
            )
            if checkout.freshness in (FRESHNESS_BLIND, FRESHNESS_UNKNOWN):
                row += palette.paint(
                    " — `git fetch --prune origin` before trusting `merged` or "
                    "`behind` below", palette.DIM)
            lines.append(row)
        # WHICH BASE, ALWAYS. `merged` means "contained by this ref"; a reader
        # who cannot see which ref that was cannot tell a finished branch from a
        # branch that only looks finished against a local main nobody updated.
        lines.append(palette.paint(
            f"  merged is judged against {repo.base_ref}" if repo.base_ref
            else "  no base ref resolves; merge state is unavailable",
            palette.DIM if repo.base_ref else palette.RED,
        ))
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
            path = _display_path(repo, worktree.path, workspace_root)
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
            # The overlay's change paths are already blanked by redaction; the
            # section is skipped as well, so a future edit that stops blanking
            # them still cannot print them from here.
            if verbose and not repo.private:
                for change in worktree.changes:
                    path_text = _safe_path(change.path)
                    if change.old_path:
                        path_text = f"{_safe_path(change.old_path)} → {path_text}"
                    lines.append(f"      {change.code}  {path_text}")

        shown = list(repo.branches)
        hidden = 0
        if stale_days is not None:
            threshold = stale_days * 86400
            # THE ROW YOU ARE STANDING ON IS NEVER FILTERED OUT. `--stale 1`
            # used to delete the `main` row outright, which is how a checkout 88
            # commits behind could be read past: the one row describing the
            # reader's own position vanished and the table that remained looked
            # healthy. A filter may narrow what you are being shown; it may not
            # remove your own position from the map.
            #
            # Only THAT row is exempt — the branch the CHECKOUT verdict above
            # describes. Other checked-out branches (linked worktrees) stay
            # subject to the filter, because "show me what nobody has touched"
            # legitimately means hiding a worktree somebody edited a minute ago.
            standing_on = repo.checkout.branch_ref if repo.checkout else None
            kept = [b for b in shown
                    if (standing_on is not None and b.ref.full_name == standing_on)
                    or (b.age_seconds is not None and b.age_seconds >= threshold)]
            hidden = len(shown) - len(kept)
            shown = kept
        branch_count = _count("row", len(shown))
        heading = f"  BRANCHES ({branch_count})"
        if stale_days is not None:
            heading += (f" — untouched for {stale_days}+ days; {hidden} newer row(s) "
                        f"hidden; the checked-out row is always shown")
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
            sync = palette.paint(
                f"{branch.sync:<{sync_width}}",
                _sync_style(branch.sync, palette),
            )
            row = (
                f"    {marker} {scope}  {_truncate(branch.name, name_width):<{name_width}}  "
                f"{state}  {_age_text(branch.age_seconds):>4}  "
                f"{sync}  {merged}"
            )
            if repo.pr_requested:
                row += f"  {(branch.pr or '—'):<{pr_width}}"
            row += f"  {_truncate(branch.intent, INTENT_WIDTH)}"
            lines.append(row.rstrip())
            if verbose:
                # Joined by what SURVIVES rather than by position: the overlay's
                # object id and commit subject are blank, and an empty field
                # must not leave a dangling separator behind.
                provenance = " · ".join(part for part in (
                    branch.ref.short_oid, branch.ref.relative_date,
                    branch.ref.subject) if part)
                if provenance:
                    lines.append(palette.paint(f"        {provenance}", palette.DIM))
                details = []
                if branch.upstream is not None:
                    details.append(f"upstream {branch.upstream.short_name}")
                elif branch.upstream_missing:
                    expected = branch.ref.upstream_short or branch.ref.upstream_ref
                    details.append(f"expected {expected}")
                if branch.worktree_path:
                    location = _display_path(repo, branch.worktree_path, workspace_root)
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
                        f"{_display_path(repo, branch.wedged_at, workspace_root)} still "
                        "owns this branch but its directory is gone — `git switch` will "
                        "refuse until `git worktree prune` runs",
                        palette.RED,
                    ))

        if verbose and repo.remotes:
            lines.append(palette.paint("  REMOTES", palette.BOLD))
            for remote in repo.remotes:
                lines.append(f"    {remote.name:<10}  {remote.url}")

    lines.extend(
        [
            "",
            palette.paint(
                "Legend: * checked out · L local · R cached remote · "
                "merged = merging it into the base ref named above would change "
                "nothing (catches squash-merges) · unknown = the probe could not "
                "answer, so the branch is kept",
                palette.DIM,
            ),
            palette.paint(
                "State (derived, never stored): active <30m · idle <24h · stale "
                "older · merged contained by the base ref · orphaned upstream gone · "
                "wedged worktree registration outlived its directory. Age is the "
                "newest of the tip commit date and the worktree's own files.",
                palette.DIM,
            ),
            palette.paint(
                "Intent: `git branch --edit-description` (shared across worktrees, "
                "never pushed); otherwise the branch's first commit subject.",
                palette.DIM,
            ),
            palette.paint(
                f"CHECKOUT: how much of this is still true — fresh <24h · dated "
                f"<{CHECKOUT_BLIND_SECONDS // 86400}d · BLIND older (`merged` and "
                "`behind` are computed against a cached ref, so they age with it).",
                palette.DIM,
            ),
        ]
    )
    return "\n".join(lines)


# ── machine-readable output ──────────────────────────────────────────────────

def _json_path(repo: Repository, path: Path | None) -> str | None:
    """The JSON counterpart of ``_display_path`` — same fail-closed rule."""
    if path is None:
        return None
    if repo.private:
        return repo.path_display.get(str(path), PATH_WITHHELD)
    return str(path)


def _worktree_json(worktree: Worktree, repo: Repository) -> dict:
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
        # Through the same fail-closed gate the table uses; ``--json`` is pasted
        # into issues at least as often as the table is.
        "path": _json_path(repo, worktree.path),
        "prunable": worktree.prunable,
        "staged": worktree.staged,
        "status_error": worktree.status_error,
        "unstaged": worktree.unstaged,
        "untracked": worktree.untracked,
    }


def _branch_json(branch: Branch, repo: Repository) -> dict:
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
        "wedged_at": _json_path(repo, branch.wedged_at),
        "worktree_path": _json_path(repo, branch.worktree_path),
    }


def _checkout_json(checkout: Checkout | None) -> dict | None:
    if checkout is None:
        return None
    return {
        "ahead": checkout.ahead,
        "behind": checkout.behind,
        "branch": checkout.branch,
        "fetched_epoch": checkout.fetched_epoch,
        "freshness": checkout.freshness,
        "knowledge_age_seconds": checkout.knowledge_age_seconds,
        "sync": checkout.sync,
    }


def repository_json(repo: Repository) -> dict:
    return {
        "base_ref": repo.base_ref,
        "branches": [_branch_json(branch, repo) for branch in repo.branches],
        "checkout": _checkout_json(repo.checkout),
        "label": repo.label,
        "local_ref_count": repo.local_ref_count,
        "merge_probe": repo.merge_probe,
        "merge_probe_note": repo.merge_probe_note,
        "private": repo.private,
        "redaction": PRIVATE_POLICY_NOTE if repo.private else None,
        "pull_request_error": repo.pr_error,
        "pull_requests_requested": repo.pr_requested,
        "remote_ref_count": repo.remote_ref_count,
        "remotes": [{"name": r.name, "url": r.url} for r in repo.remotes],
        "root": str(repo.root),
        "worktrees": [_worktree_json(worktree, repo) for worktree in repo.worktrees],
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
            "checkout_dated_seconds": CHECKOUT_DATED_SECONDS,
            "checkout_blind_seconds": CHECKOUT_BLIND_SECONDS,
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
