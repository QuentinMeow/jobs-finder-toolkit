#!/usr/bin/env python3
"""Plan — never perform — the retirement of finished branches and worktrees.

THERE IS NO EXECUTOR. This tool classifies, explains, and writes a shell script
the OWNER reads and runs. Its own ``--execute`` does only things that cannot
lose anything: it writes backup refs, verifies them, prunes worktree metadata
whose directory the owner already deleted, and optionally writes an archive tag.
Every genuinely destructive step — ``git branch -d``, moving a worktree
directory — is EMITTED, not run. That is why this does not reverse
``docs/handbook/post-merge-cutover.md``'s prohibition on ``rm``, ``git clean``,
``git worktree remove`` and ``git branch -D``: it runs none of them, and the
script it writes uses ``mv`` and ``-d``.

WHAT MAKES A BRANCH PROPOSABLE (every one of these, or it is kept and the
reason is printed):

1. main CONTAINS its content — ``git merge-tree --write-tree`` says merging it
   would change nothing. Ancestry is not enough: it misses squash-merges. A
   patch-id probe is not allowed anywhere near this decision — patch-id ignores
   whitespace, so it calls an 8-space and a 2-space Python body identical;
2. the merge was judged against a FETCHED base. Without ``--fetch`` the whole
   plan is stamped stale and its script is emitted COMMENTED OUT;
3. no worktree references it — including a registration whose directory is
   gone, which a lock can hide from ``prunable``;
4. ``git rev-list <branch> --not --remotes`` is empty — every commit exists on a
   remote — OR the FETCHED base ref demonstrably contains the branch's entire
   content. That second clause is not a loophole, it is the repair of a rule
   that had become unsatisfiable: after a squash-merge whose head branch GitHub
   deleted, the branch's own commits are on no remote-tracking ref and no future
   ref can ever carry them, so the proxy ("every commit is on a remote") can
   never again be true while the thing it stands for ("deleting this loses
   nothing") is plainly true. The waiver is printed as a note, needs a fresh
   fetch, and the tip is pinned before anything deletes it;
5. deleting it would not orphan a COMMIT that ``automation/publish/review_ledger.yaml``
   names. The question is REACHABILITY, never whether the branch's name appears
   in that file: a row degrades from NOT_ANCESTOR to UNKNOWN OBJECT when the
   commit its ``base:``/``commit:`` field names stops being reachable in a fresh
   clone, and a branch whose commits are all reachable from the base ref cannot
   cause that however often its name is written in someone's prose;
6. ``git branch -d`` will actually accept it — or, where it structurally cannot,
   this planner's own containment proof supersedes its verdict and the deletion
   is emitted as a COMPARE-AND-SWAP instead. That is a DIFFERENT question from
   point 1: git judges ``-d`` against the branch's own upstream when one is
   configured and its tracking ref resolves, and against ``HEAD`` otherwise —
   never against the base ref this planner tests. Two refs, two relations, and
   after a squash-merge the ``-d`` relation can never hold again. The full
   argument, and the four things that are still refused outright, are at
   ``deletion_method``;
7. a backup ref resolves TO THE RIGHT COMMIT, and no other item's backup can be
   written over it. The reflog does NOT protect worktree-only commits (measured:
   0 hits after ``worktree remove --force`` + ``branch -D``);
   ``refs/agent-trash/<ts>/<branch>-<sha12>`` makes the tip reachable, so it
   survives even ``git gc --prune=now``. The tip is IN THE NAME because it had
   to be: ``slug`` maps ``/`` to ``-``, so ``feat/a`` and ``feat-a`` derived one
   ref, the second write clobbered the first, and both rows still reported
   ``backup_written: true``.

A BRANCH TIP IS NOT THE ONLY THING A RETIREMENT CAN ORPHAN. Point 7 above was
written for branches and, for a long time, only implemented for branches — while
a worktree carries its OWN reflog at ``.git/worktrees/<id>/logs/HEAD``, and the
emitted ``mv`` + ``git worktree prune`` deletes that whole administrative
directory. Measured on git 2.55, in the suite's own fixture:

* a commit made while the worktree's HEAD is DETACHED, after HEAD returns to a
  branch, is recorded in ``worktrees/<id>/logs/HEAD`` and NOWHERE else. Running
  the script this tool wrote, then ``git gc --prune=now``, erased it. No backup
  ref had been written for it, because it was not any branch's tip;
* a commit made on the worktree's branch and then ``reset --hard`` away is in
  that same per-worktree reflog AND in the COMMON ``logs/refs/heads/<branch>``,
  so retiring the worktree alone does not lose it — but only a reflog is holding
  it, and a later ``git branch -d`` deletes that reflog too.

So every worktree this tool proposes to retire gets its own reflog swept first:
``git -C <wt> reflog --format=%H HEAD``, deduped against every commit already
reachable from a ref, with one verified ``refs/agent-trash/<ts>-worktrees/…``
ref per survivor — written FIRST, verified, and the worktree dropped from the
plan if the ref cannot be written.

AND SO DOES EVERY WORKTREE IT PROPOSES TO **PRUNE**. That path had no sweep at
all: a gone registration went straight to ``action="prune"`` before the sweep
was reachable, and ``--execute``'s own ``git worktree prune`` then deleted the
administrative directory the reflog lives in. Measured, with a control arm: the
owner deleting the directory and running ``git gc --prune=now`` does NOT lose a
detached-HEAD commit — the per-worktree reflog still protects it — while
``cleanup.py --execute`` followed by the same ``gc`` DID, with zero backup refs
written, reporting the step as "pruned (metadata only)". The directory being
gone does not make the reflog unreadable; ``git --git-dir=<admin> reflog HEAD``
answers until prune runs. And because ``git worktree prune`` cannot be aimed at
one entry, a fail-closed KEEP on any gone registration now holds back the whole
run's pruning rather than being overruled by a neighbour. The sweep is bounded by the reflog itself and
by the exclusion walk; it never enumerates history. Stash entries are EXCLUDED
rather than backed up: ``refs/stash`` and ``logs/refs/stash`` were measured to
live in the COMMON ref store, so ``git worktree prune`` cannot destroy them and
a backup here would be a ref this tool does not owe.

WHAT MAKES A WORKTREE RETIRABLE — and the one thing that never is. The MAIN
working tree (the directory that physically contains ``.git``) is not a
worktree this tool may propose, under any condition, on any invocation. It was
proposed once: the guard compared each worktree against the planner's OWN root,
and run from a linked worktree that root IS the linked worktree, so the main
working tree compared unequal and looked retirable. The emitted script's first
destructive line was a ``mv`` of the repository root into a trash directory
nested inside one of its own linked worktrees. The guard is now git's own
definition — ``--git-dir`` equals ``--git-common-dir`` in the main working tree
and in no other — asked of each worktree, so it holds from anywhere; it is
unioned with two more signals; an unanswerable probe keeps; and the emitter
re-checks it independently, because ``build_script`` is the only place a
destructive line is ever written and that is where "impossible" has to be true.

ONE ITEM REFUSING MUST NOT CANCEL THE INDEPENDENT ITEMS AFTER IT. The emitted
script used to be a bare ``set -eu`` list, so the first ``git branch -d`` that
declined ended the run: measured on this repository, one refusal left two
perfectly safe deletions unperformed and handed the operator a failure with no
statement of which items had been fine. Each item is now its own guarded block —
a refusal is RECORDED and the next item still runs — while everything that is
not an item stays fatal (``cd`` into the root, ``mkdir -p`` of the trash
directory, an unset variable). What may never become per-item is the backup ref:
a pin that does not read back still stops THAT item's ``git branch -d`` or
``mv``, because a deletion standing behind nothing is the failure this whole
design exists to prevent. The script prints a summary naming every item that
completed and every item that refused, and exits 1 if anything refused, so a
refusal can never be read as success.

Exit codes:
    0  fresh remote knowledge and every proposal cleared every precondition
    1  readable, but stale (no --fetch) or something needs judgement
    2  argparse usage error
    3  REFUSED — a fail-closed condition; this is not a state to plan from

Tests: ``.venv/bin/python -m unittest discover automation/workspace/tests``
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import status  # noqa: E402  (import after the sys.path bootstrap, by design)

REPO_ROOT = status.REPO_ROOT
SCHEMA = "workspace-cleanup-plan/v1"
TOOL = "automation/workspace/cleanup.py"
TRASH_REF_ROOT = "refs/agent-trash"
ARCHIVE_TAG_PREFIX = "archive"
OUTPUT_DIR = Path("local") / "workspace"
REVIEW_LEDGER = Path("automation") / "publish" / "review_ledger.yaml"

# Branch names nothing may ever propose, whatever the probes say.
PROTECTED = frozenset({"main", "master", "HEAD"})

# Worktrees the Claude Code harness owns. It runs its own sweep over these —
# releasing locks whose process exited, never releasing a lock a human set, and
# skipping any worktree holding changed files or unpushed commits. A second
# sweeper on the same directory is how two correct programs delete live work,
# so by DEFAULT this one reports them and proposes nothing.
#
# WHY THERE IS AN OPT-IN NOW. Keeping them unconditionally did not make anyone
# safer; it made the tool silent about the one pile the owner actually cleans by
# hand. An operator, reading a plan that proposed none of eleven agent
# worktrees, ran eleven `git worktree remove` calls outside the plan — the exact
# command `docs/handbook/post-merge-cutover.md` names as prohibited. A tool
# whose output routes people to a prohibited command has not prevented the
# risk, it has moved it somewhere with no backup refs and no report.
#
# `--include-harness-worktrees` is therefore the supported path, and the KEEP
# reason names it so a reader of the plan finds it. It waives ONE thing — this
# marker — and nothing else: clean tree, contained in the fetched base,
# unlocked, not the main working tree, not the planner's own directory, and the
# per-worktree reflog sweep above all still decide. And it changes nothing about
# what this tool RUNS: the retirement is still emitted as `mv` into a trash
# directory for the owner to read and run, so the handbook's prohibition on this
# tool performing `git worktree remove` is untouched.
HARNESS_WORKTREE_MARKER = ".claude/worktrees"

# One line, printed in the report and in the emitted script's header, so the
# tension is visible to whoever runs the script rather than buried here.
HARNESS_HANDBOOK_NOTE = (
    "harness worktrees are included by request (--include-harness-worktrees): "
    "`docs/handbook/post-merge-cutover.md` forbids this TOOL from running "
    "`git worktree remove`, and it still runs nothing — the retirement below is "
    "an emitted `mv` into a trash directory, and the script is the owner's to "
    "read and run.")

# The most commits one worktree's reflog sweep will pin. A HEAD reflog is finite
# but not small-by-definition, and a script with a thousand `update-ref` lines
# is not a script anyone reads. Over this, the worktree is KEPT and says so:
# over-keeping costs a directory until someone looks, and the alternative is
# truncating a backup set, which is the failure this whole feature exists to
# prevent.
MAX_WORKTREE_BACKUP_REFS = 200

# ── fail-closed refusals (each exits 3) ──────────────────────────────────────
CODE_TOOLKIT_GUARD = "not-the-toolkit-repository"
CODE_MERGE_PROBE_DEGRADED = "merge-probe-degraded"
CODE_BASE_REF_MISSING = "base-ref-missing"
CODE_OPERATION_IN_PROGRESS = "operation-in-progress"
CODE_FETCH_FAILED = "fetch-failed"
CODE_OUTPUT_UNWRITABLE = "output-unwritable"
CODE_BACKUP_REF_FAILED = "backup-ref-failed"

# ── why an item is kept (printed verbatim; these ARE the report) ─────────────
KEEP_PROTECTED = "protected branch name"
KEEP_BASE = "this is the base branch"
KEEP_WORKTREE = "a worktree has it checked out"
KEEP_WEDGED = ("a worktree registration still owns it — `git worktree prune` "
               "first (that destroys nothing; the directory is already gone)")
KEEP_UNMERGED = "main does not contain its content"
KEEP_UNKNOWN_MERGE = "the merge probe could not answer for this ref"
KEEP_UNPUSHED = "commit(s) reachable from no remote-tracking ref"
KEEP_LEDGER = (
    "deleting it would orphan a commit the review ledger names — that row "
    "degrades to UNKNOWN OBJECT in a fresh clone. Ledger commit")
KEEP_LEDGER_UNREADABLE = (
    "the review ledger names commit(s) git could not judge for reachability, "
    "and an unanswerable probe about losing a reviewed commit is treated as yes")
KEEP_DELETE_REFUSED = "`git branch -d` would refuse it"
KEEP_UNSAFE_NAME = "the name would need shell quoting this tool will not guess"
KEEP_NO_BACKUP = "the backup ref did not resolve"
KEEP_HARNESS = (
    "harness-owned worktree — Claude Code sweeps these itself, so this planner "
    "keeps them by default. Pass --include-harness-worktrees to have them "
    "judged like any other worktree (every other precondition still applies); "
    "that is the supported path — do NOT reach for `git worktree remove`")
KEEP_NO_REFLOG = (
    "its own reflog could not be read, so the commits `git worktree prune` is "
    "about to destroy cannot be enumerated")
KEEP_TOO_MANY_ORPHANS = (
    "commit(s) live only in its reflog — more than this run will pin to refs. "
    "Recover or discard them yourself, then re-run")
KEEP_NO_REFLOG_BACKUP = (
    "a reflog backup ref did not resolve, so retiring it could orphan a commit")
KEEP_DIRTY = "changed path(s) here — untracked files have no git recovery story"
KEEP_STATUS_UNREADABLE = (
    "its `git status` could not be answered, so whether it holds uncommitted "
    "work is UNKNOWN — and an unanswerable dirty probe is treated as dirty. "
    "git said")
KEEP_PRUNE_HELD_BACK = (
    "another gone registration in this run could not be swept for the commits "
    "`git worktree prune` would destroy, and prune cannot be aimed at ONE "
    "entry — so this run prunes nothing. Fix or remove that one and re-run")
KEEP_NOT_CONTAINED = (
    "this planner's own containment re-check does not put its content in the "
    "base ref. A `merge-tree` CONFLICT is an answer — 'merging would change "
    "the base' — and conflicts git resolves by keeping the base's side "
    "verbatim (binary files, `-merge` attributes, submodule pointers) print a "
    "tree identical to the base's while the branch's content is nowhere in it")
KEEP_DETACHED_UNCONTAINED = (
    "detached HEAD at a commit the base ref does NOT contain. There is no "
    "branch to judge it by AND no proof its work landed anywhere, which is "
    "exactly the shape of an unpushed experiment — so it stays")
KEEP_LOCKED = "the worktree is locked — a deliberate finalizer"
KEEP_LOCKED_GONE = (
    "locked AND its directory is gone — `git worktree prune` cannot clear it "
    "while the lock stands, so it wedges its branch indefinitely. Clearing it "
    "needs a doubled `-f -f` this tool will never pass: run "
    "`git worktree unlock <path>` yourself, then re-run this planner")
KEEP_MAIN = (
    "this is the MAIN working tree — the directory that physically contains "
    "`.git` and every other worktree's administrative data. Nothing may ever "
    "propose moving it")
KEEP_MAIN_UNPROVEN = (
    "git could not say whether this is the main working tree, and an "
    "unprovable answer is treated as yes")
KEEP_RUNNING_HERE = (
    "the planner is running from here — its own script, plan and trash "
    "directory all live inside it. Re-run from another worktree to retire it")
KEEP_CONTAINS_WORKTREE = (
    "another registered worktree lives inside it — moving this directory would "
    "silently relocate live work git still believes is at the old path")
KEEP_SELF_NESTING = (
    "the only destination this run can offer is inside the directory being "
    "moved, and `mv` into your own subdirectory is not a move")
KEEP_UNSAFE_PATH = (
    "the path holds a newline or control character, which cannot be written "
    "into a shell comment without becoming a command")

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
# A path this tool will not describe in an emitted script. `git worktree list
# --porcelain -z` faithfully carries a newline inside a path, and
# `# worktree <path>` would then end its comment early and leave the tail of
# the path standing as a COMMAND. shlex.quote protects the `mv`; it does not
# protect the comment above it.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Blocking:
    code: str
    subject: str
    message: str

    def to_json(self) -> dict:
        return {"code": self.code, "message": self.message, "subject": self.subject}


# How the emitted script spells one branch's deletion. `git branch -d` is the
# default and stays the default; the compare-and-swap exists only for the shape
# `-d` structurally cannot accept — see `deletion_method` below.
DELETE_BRANCH_D = "git branch -d"
DELETE_CAS = "git update-ref -d (compare-and-swap on the tip)"


@dataclass
class BranchItem:
    name: str
    ref: str
    tip: str
    state: str
    merged: str
    intent: str
    age_seconds: int | None
    keep_reasons: list[str] = field(default_factory=list)
    backup_ref: str | None = None
    backup_written: bool = False
    archive_tag: str | None = None
    unpushed: int = 0
    # Rules this item cleared by EVIDENCE rather than by passing. Printed in the
    # report and written into the script: a relaxed rule nobody is told about is
    # a relaxed rule nobody can object to.
    notes: list[str] = field(default_factory=list)
    delete_method: str = DELETE_BRANCH_D

    @property
    def proposed(self) -> bool:
        return not self.keep_reasons

    def to_json(self) -> dict:
        return {
            "age_seconds": self.age_seconds,
            "archive_tag": self.archive_tag,
            "backup_ref": self.backup_ref,
            "backup_written": self.backup_written,
            "delete_method": self.delete_method,
            "intent": self.intent,
            "keep_reasons": list(self.keep_reasons),
            "merged": self.merged,
            "name": self.name,
            "notes": list(self.notes),
            "proposed": self.proposed,
            "ref": self.ref,
            "state": self.state,
            "tip": self.tip,
            "unpushed_commits": self.unpushed,
        }


@dataclass
class WorktreeItem:
    path: str
    branch: str | None
    action: str            # "prune" | "retire" | "keep"
    keep_reasons: list[str] = field(default_factory=list)
    gone: bool = False
    locked: bool = False
    dirty_paths: int = 0
    pruned: bool = False
    harness: bool = False
    detached: bool = False
    # `git status` failing is NOT "clean" — it is "unanswerable". Carried on the
    # item so the plan JSON shows the same thing the dashboard shows.
    status_error: str | None = None
    # (backup ref, commit) for every commit this worktree's own reflog is the
    # only thing holding. Empty is the ordinary answer — a worktree whose HEAD
    # never left its branch has nothing here.
    backups: list[tuple[str, str]] = field(default_factory=list)
    backups_written: bool = False
    # Same contract as BranchItem.notes: the positive evidence a proposal rests
    # on, printed rather than assumed.
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "action": self.action,
            "backup_refs": [{"commit": oid, "ref": ref} for ref, oid in self.backups],
            "backups_written": self.backups_written,
            "branch": self.branch,
            "detached": self.detached,
            "dirty_paths": self.dirty_paths,
            "gone": self.gone,
            "harness_owned": self.harness,
            "keep_reasons": list(self.keep_reasons),
            "locked": self.locked,
            "notes": list(self.notes),
            "path": self.path,
            "pruned": self.pruned,
            "status_error": self.status_error,
        }


# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def make_run_id(moment: datetime.datetime | None = None) -> str:
    return (moment or _now()).strftime("%Y%m%dT%H%M%SZ")


def slug(name: str) -> str:
    """Lowercase, ref-safe. macOS case collisions are NONDETERMINISTIC.

    With a LOOSE ref ``refs/heads/agent/Task-1`` present, creating
    ``agent/task-1`` fails; after ``git gc`` packs the refs the SAME command
    succeeds, leaving two refs whose loose filenames collide. A backup ref
    derived from a branch name must not inherit that coin flip.
    """
    return _SLUG_RE.sub("-", name.lower()).strip("-") or "branch"


def _git(repo: Path, *args: str, check: bool = False,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """``env`` overlays the caller's environment — only the merge probe uses it."""
    return status._git(repo, *args, check=check, env=env)


def _in_progress_operation(repo: Path) -> str | None:
    result = _git(repo, "rev-parse", "--git-dir")
    if result.returncode:
        return None
    git_dir = Path(result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    for marker, label in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
                          ("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"),
                          ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect")):
        if (git_dir / marker).exists():
            return label
    return None


def _fetch(repo: Path) -> tuple[bool, str]:
    """``git fetch --prune origin`` — the ONE call here that touches the network."""
    remotes = _git(repo, "remote").stdout.split()
    if "origin" not in remotes:
        return False, "no remote named origin; remote knowledge cannot be refreshed"
    result = _git(repo, "fetch", "--prune", "origin")
    if result.returncode == 0:
        return True, ""
    detail = result.stderr.strip().replace("\n", " ")
    return False, f"git fetch --prune origin exited {result.returncode}: {detail}"


def resolve_base(repo: Path, fetched: bool) -> str | None:
    """The ref a branch must be contained by.

    After a fetch the authority is ``origin/main`` — the field-tested deletion
    criterion is containment by the FETCHED remote base, not by whatever the
    local main happens to be. Without a fetch the local ref is all there is,
    and the plan says so.
    """
    order = (("refs/remotes/origin/main", "refs/heads/main") if fetched
             else ("refs/heads/main", "refs/remotes/origin/main"))
    for ref in order:
        if status._ref_exists(repo, ref):
            return ref
    return None


# ── the review ledger, and what deleting a branch can actually cost it ───────
#
# WHAT THE RULE IS FOR. A ledger row is keyed to a COMMIT (`base:`, `commit:`).
# `automation/publish/review_gate.py` reports a row whose commit it cannot find
# as `UNKNOWN OBJECT — not in this checkout at all`, and a fresh clone carries
# only REACHABLE objects, so a branch that is the last thing holding a
# ledger-named commit takes that row's inspectability with it when it is
# deleted. That, and only that, is the hazard.
#
# WHAT THE RULE WAS. `branch.name in <the ledger's raw text>` — a substring
# search over the whole file. It answered a question nobody had:
#
#   * IT WAS THE WRONG QUESTION. A name appearing in a `finding:` string carries
#     no object. Measured on this repository: `fix/filter-pipeline-reports` was
#     kept forever because one row's prose reads "Merge of origin/main into
#     fix/filter-pipeline-reports…", while its tip is an ANCESTOR of
#     `origin/main` and it holds zero commits `origin/main` does not. No row
#     could degrade, and the keep was pure cost.
#   * THE FEEDBACK LOOP THAT MADE IT. Every branch that lands here writes a
#     ledger row, and an agent writing that row naturally names the branch it is
#     on. Under a name match, WRITING A BRANCH'S NAME INTO A `finding:` PINS
#     THAT BRANCH FOREVER — the tool that exists to stop branch accumulation was
#     being fed by the one ritual every branch performs on its way in.
#   * THE MATCH SET WAS POLLUTED. Raw-text substring matching does not even
#     restrict itself to branch names: `docs/handbook`, `docs/designs`,
#     `docs/roadmap`, `tasks/0`, `tasks/3`, `tasks/4` all occur in that file as
#     DIRECTORY PATHS, and `main` occurs inside every `origin/main`. A branch
#     named for a directory the ledger happens to mention was unretirable for a
#     reason that had nothing to do with any commit.
#
# So the ledger is read for COMMITS and matched against nothing else. Over-keep
# on ambiguity — an unresolvable probe keeps — but never on a name coincidence.

# 7 is git's own minimum abbreviation. Deliberately greedy: a token that is not
# a commit simply fails to resolve, and collecting a few extra candidates is the
# safe direction, while missing a real one is not.
_LEDGER_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


@dataclass(frozen=True)
class LedgerRisk:
    """Which ledger commits a branch deletion could actually orphan.

    ``at_risk`` holds the ledger commits that the BASE REF does not already make
    reachable — the only ones any branch here could be the last holder of. It is
    normally EMPTY, because a healthy ledger names commits that landed on main,
    and then no branch is kept on ledger grounds at all.

    ``unreadable`` is the fail-closed flag: the ledger named commits and git
    could not answer the reachability question, so every branch is kept and says
    so. It is never set merely because the ledger file is absent.
    """
    at_risk: tuple[str, ...] = ()
    unreadable: bool = False


def ledger_text(repo: Path) -> str:
    """The review ledger's raw text, or ``""`` when there is no ledger."""
    path = repo / REVIEW_LEDGER
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def ledger_commits(repo: Path, text: str) -> list[str]:
    """Every commit the ledger NAMES, resolved to a full oid, in one git call.

    ``git cat-file --batch-check`` takes the whole candidate set on stdin, so
    this costs one subprocess rather than one per token — the ledger carries
    hundreds. Tokens git reports as ``missing`` are prose that merely looked like
    a sha; tokens it reports as ``ambiguous`` are RESOLVED rather than dropped
    (``--disambiguate`` lists every object sharing the prefix, and every
    candidate that is a commit is then treated as named), because dropping an
    ambiguous row would silently narrow the protection.
    """
    tokens = list(dict.fromkeys(_LEDGER_SHA_RE.findall(text)))
    if not tokens:
        return []
    commits, ambiguous = _batch_check_commits(repo, tokens)
    extra: list[str] = []
    for prefix in ambiguous:
        listed = _git(repo, "rev-parse", f"--disambiguate={prefix}")
        if listed.returncode == 0:
            extra.extend(listed.stdout.split())
    if extra:
        resolved, _ = _batch_check_commits(repo, list(dict.fromkeys(extra)))
        commits.extend(resolved)
    return list(dict.fromkeys(commits))


def _batch_check_commits(repo: Path,
                         tokens: Sequence[str]) -> tuple[list[str], list[str]]:
    """``(full oids that are commits, prefixes git called ambiguous)``.

    Spelled out rather than routed through ``status._git`` for one reason: this
    is the only query here that feeds git on STDIN, which that helper does not
    take. ``--no-optional-locks`` is carried over from it deliberately — a
    read-only probe must not touch the index.
    """
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), "cat-file",
         "--batch-check"],
        input="\n".join(tokens) + "\n", stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        errors="replace", check=False)
    if result.returncode and not result.stdout:
        return [], []
    commits: list[str] = []
    ambiguous: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        if fields[1] == "ambiguous":
            ambiguous.append(fields[0])
        elif fields[1] == "commit":
            commits.append(fields[0])
    return commits, ambiguous


def ledger_risk(repo: Path, base_ref: str | None) -> LedgerRisk:
    """The ledger commits the base ref does NOT already keep reachable.

    Reachability from the base ref is the whole test. A ledger commit that
    ``origin/main`` reaches survives every deletion this planner could propose,
    so it can keep nothing; one it does not reach is a commit some branch may be
    the last holder of, and that is the case worth a keep.
    """
    named = ledger_commits(repo, ledger_text(repo))
    if not named or base_ref is None:
        return LedgerRisk()
    # `--not <base>` stops the walk at the base ref, so this enumerates only
    # what the base does not already have; intersecting back with `named` drops
    # the at-risk commits' ancestors, which no ledger row claims.
    walk = _git(repo, "rev-list", "--ignore-missing", *named, "--not", base_ref)
    if walk.returncode:
        return LedgerRisk(at_risk=tuple(named), unreadable=True)
    outside = set(walk.stdout.split())
    return LedgerRisk(at_risk=tuple(oid for oid in named if oid in outside))


def ledger_keep_reasons(repo: Path, ref: str, risk: LedgerRisk) -> list[str]:
    """Why this branch must stay for the ledger's sake — usually nothing.

    A branch is kept only when it REACHES a ledger commit the base ref does not,
    which is the one shape whose deletion can turn a row into UNKNOWN OBJECT.
    This deliberately over-keeps when a second surviving branch also reaches that
    commit: proving otherwise means reasoning about which other branches this
    same plan deletes, and over-keeping costs a branch until the next run while
    under-keeping costs a review nobody can inspect again.
    """
    if not risk.at_risk:
        return []
    if risk.unreadable:
        return [KEEP_LEDGER_UNREADABLE]
    reasons: list[str] = []
    for oid in risk.at_risk:
        probe = _git(repo, "merge-base", "--is-ancestor", oid, ref)
        if probe.returncode == 0:
            reasons.append(f"{KEEP_LEDGER} {oid[:8]}")
        elif probe.returncode != 1:
            return [KEEP_LEDGER_UNREADABLE]
    return reasons


# ── containment, asked by THIS tool, of any commit-ish ───────────────────────
#
# WHY A SECOND PROBE WHEN `status` ALREADY COMPUTES `merged`. Three reasons,
# and the third is the one that matters.
#
# 1. `status.Branch.merged` answers for BRANCHES. A worktree with a DETACHED
#    HEAD has no branch, so the dashboard has no verdict to lend — and the only
#    honest question about such a worktree is whether the base already contains
#    the commit it is sitting on. That question needs a probe that takes a raw
#    commit-ish.
# 2. Every rule below that is RELAXED is relaxed on containment. A rule relaxed
#    on a verdict computed in another module, for another purpose, is a rule
#    relaxed on a promise.
# 3. MEASURED, and the reason exit 1 is not accepted here: `git merge-tree
#    --write-tree` exits 1 for a CONFLICTING merge and still prints a tree. For
#    every conflict class git resolves by keeping OUR side verbatim — a file git
#    auto-detects as binary (any NUL byte), a path carrying `binary`/`-merge` in
#    `.gitattributes`, a submodule pointer — that printed tree IS the base tree,
#    so "result == base tree" reads CONTAINED for a branch whose content exists
#    nowhere in the base. This repository tracks 22 files with NUL bytes. A
#    conflict is by definition "merging would change the base", so it is
#    answered NOT contained, full stop, and the destructive line is never
#    written on its say-so.


class Containment:
    """``does <base_ref> already contain everything <rev> has?`` — cached.

    ``True`` / ``False`` / ``None``, and ``None`` is UNANSWERABLE: every caller
    here keeps on it. One merge probe is opened for the whole run (each one
    costs a temporary object directory), and every answer is cached, because
    the classifier and the emitter deliberately ask the same question twice.
    """

    def __init__(self, root: Path, base_ref: str | None) -> None:
        self.root = root
        self.base_ref = base_ref
        self._probe = status.open_merge_probe(root)
        self._base_tree = status._base_tree(root, base_ref)
        self._answers: dict[str, bool | None] = {}

    def contains(self, rev: str | None) -> bool | None:
        if not rev:
            return None
        if rev not in self._answers:
            self._answers[rev] = self._ask(rev)
        return self._answers[rev]

    def _ask(self, rev: str) -> bool | None:
        if self.base_ref is None or self._probe.degraded or not self._base_tree:
            return None
        if rev == self.base_ref:
            return True
        result = _git(self.root, "merge-tree", "--write-tree", self.base_ref,
                      rev, env=self._probe.env)
        head = result.stdout.split("\n", 1)[0].strip()
        if result.returncode == 0 and status._OID_RE.match(head):
            return head == self._base_tree
        if result.returncode == 1:
            # CONFLICT — see the note above. A real answer, and the answer is no.
            return False
        return None      # 128: unrelated histories, a ref that will not resolve

    def close(self) -> None:
        self._probe.close()


def unpushed_commits(repo: Path, ref: str) -> int:
    result = _git(repo, "rev-list", "--count", ref, "--not", "--remotes")
    if result.returncode:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


# ── will `git branch -d` actually accept this branch? ────────────────────────
#
# THIS IS NOT THE SAME QUESTION AS "IS IT MERGED". The planner's containment
# probe asks whether the BASE REF already has the branch's content. `git branch
# -d` asks something else entirely (builtin/branch.c, `branch_merged`): is the
# branch an ANCESTOR of its own upstream when one is configured and that
# tracking ref resolves, and of HEAD otherwise. Two different refs, two
# different relations — so a branch can pass every precondition here and still
# be refused, and the tool used to emit that doomed command anyway.
#
# MEASURED, on this repository and reproduced in a scratch repo on git 2.55:
# `fix/cleanup-worktree-gaps` held ZERO commits `origin/main` did not
# (`git rev-list <b> --not origin/main` → 0) yet stood one commit ahead of
# `origin/fix/cleanup-worktree-gaps`, and `git branch -d` said
#
#     warning: not deleting branch '<b>' that is not yet merged to
#              'refs/remotes/origin/<b>', even though it is merged to HEAD
#     error: the branch '<b>' is not fully merged
#
# IS THERE A NON-FORCING WAY TO DELETE IT? No, and this was checked rather than
# assumed. Three things make `-d` accept such a branch, and each works only by
# removing the evidence git consults:
#   * `git branch -D` / `--force` — banned outright, and there is no --force in
#     this tooling;
#   * `git update-ref -d refs/heads/<b>` — plumbing, with no safety check at
#     all. Strictly more forcing than the flag that is banned;
#   * deleting the remote-tracking ref, or `git branch --unset-upstream` —
#     measured to work (the probe run for this fix deleted
#     `refs/remotes/origin/topic` and the identical `-d` then succeeded), and
#     that is exactly why neither is emitted. The upstream is not stale: the
#     branch is still on the remote, the next `git fetch` restores the tracking
#     ref, and unsetting the upstream is an unbacked-up config mutation whose
#     only purpose is to make git ask an easier question. A tool that quietly
#     disarms a safety check has not made the deletion safe, it has made the
#     check silent.
# So the honest outcome is a KEEP that names the situation and the two remedies
# that are the OWNER'S to choose: retire the branch on the remote (then
# `--fetch` prunes the tracking ref and a re-run proposes it), or move the local
# branch back onto its upstream.


def deletion_reference(repo: Path, name: str) -> str:
    """The ref ``git branch -d <name>`` will demand ancestry of.

    ``<name>@{upstream}`` is git's own spelling of the same lookup: it exits 0
    with the tracking ref's full name when the branch has an upstream AND that
    ref resolves, and non-zero otherwise — which is precisely when
    ``branch_merged`` falls back to HEAD. Verified against a fixture whose
    tracking ref was deleted out from under a configured upstream, where
    ``for-each-ref %(upstream)`` still prints the configured name and this does
    not.
    """
    result = _git(repo, "rev-parse", "--symbolic-full-name", "--verify",
                  "--quiet", f"{name}@{{upstream}}")
    upstream = result.stdout.strip()
    if result.returncode == 0 and upstream:
        return upstream
    return "HEAD"


def delete_refusal(repo: Path, name: str, ref: str) -> str | None:
    """``None`` when ``git branch -d`` would accept it; else why it would not."""
    reference = deletion_reference(repo, name)
    probe = _git(repo, "merge-base", "--is-ancestor", ref, reference)
    if probe.returncode == 0:
        return None
    if probe.returncode != 1:
        return (f"{KEEP_DELETE_REFUSED} or accept it — git could not say "
                f"whether it is an ancestor of {reference}, and an unanswerable "
                f"probe is treated as a refusal")
    if reference == "HEAD":
        return (f"{KEEP_DELETE_REFUSED}: git judges `-d` against HEAD when a "
                f"branch has no resolvable upstream, and this branch is not an "
                f"ancestor of HEAD even though the base ref contains its "
                f"content. Check out the base branch here and re-run, or delete "
                f"it yourself once you have read it — this tool has no -D")
    return (f"{KEEP_DELETE_REFUSED}: git judges `-d` against the branch's own "
            f"upstream, not against the base ref this planner tested, and it is "
            f"ahead of {reference}. Nothing here can make `-d` accept it without "
            f"disarming that check — deleting the tracking ref or unsetting the "
            f"upstream both work only by hiding the evidence, and there is no -D "
            f"in this tooling. Retire the branch on the remote (a later --fetch "
            f"prunes the tracking ref and this branch is proposed again), or "
            f"move it back onto {reference} yourself")


# ── when `-d`'s verdict and this planner's proof disagree ────────────────────
#
# THE TWO RULES WERE JOINTLY UNSATISFIABLE, AND THIS REPOSITORY'S OWN MERGE
# SHAPE TRIPPED BOTH. Measured on this checkout, and reproduced in scratch
# repositories on git 2.55: an agent branch is pushed, its PR is SQUASH-merged,
# GitHub deletes the head branch, and the next `--fetch` (which is
# `git fetch --prune`) drops the remote-tracking ref. From that moment:
#
#   * `git rev-list <b> --not --remotes` is non-empty FOREVER — the branch's own
#     commits are on no remote-tracking ref and no ref could ever carry them
#     again, because the branch they were pushed to no longer exists;
#   * `git branch -d` falls back to HEAD (there is no resolvable upstream any
#     more) and a squash-merged branch is not an ancestor of HEAD. Also forever,
#     and that is genuinely git's behaviour rather than a bug in the probe.
#
# So the branch was unretirable permanently, while `origin/main` demonstrably
# contained every byte of its content — and the tool exited 0 saying so at
# length. `--fetch --prune` was itself the step that destroyed the evidence that
# would have permitted retirement. Two live branches sat in exactly this state.
#
# WHAT CHANGED, AND WHY IT IS NOT "DISARMING THE CHECK". `git branch -d`'s
# verdict is EVIDENCE, not scripture: it answers "is this branch an ancestor of
# <its upstream, or else HEAD>", which is a question about a ref this planner
# never tested and, after a squash-merge, one that cannot be satisfied. When
# this tool's OWN containment proof says the fetched base already holds the
# branch's whole content, that proof is about the right ref and is strictly more
# informative, so it supersedes — and the emitted line becomes
#
#     git update-ref -d refs/heads/<b> <tip>
#
# which is a COMPARE-AND-SWAP: git refuses it unless the branch still points at
# the exact tip this plan proved contained and pinned. The three prohibited
# shortcuts are still prohibited and none of them is used: no `-D`, no
# `--force`, no `git branch --unset-upstream` and no deletion of a
# remote-tracking ref. Nothing that git consults is hidden — the upstream, the
# tracking ref and `-d`'s own verdict are all still there, still true, and the
# verdict is PRINTED in the plan and in the script next to the line it did not
# get to write.
#
# WHAT THE COMPARE-AND-SWAP GIVES BACK. `-d` is a run-time check: it re-asks its
# question at the moment the script runs, which is the only reason the branch
# path survived a plan going stale between writing and running. `update-ref -d`
# with an explicit old value re-checks something narrower but sharper at exactly
# the same moment — "has this branch moved since the plan was written?" — and
# the emitted block additionally refuses if any worktree has checked the branch
# out in the meantime, which is the other thing `-d` would have caught.
#
# THE GUARD RAILS, ALL OF WHICH STILL HOLD. A compare-and-swap deletion is
# emitted only when: the plan is FRESH (a stale plan's script is commented out
# in full); this tool's own probe answered CONTAINED (a merge-tree conflict is
# not containment); the tip is pinned to a verified `refs/agent-trash` ref that
# survives `gc --prune=now`; and the script — which the owner reads before
# running — says in a comment exactly what `-d` said and why the line differs.


def deletion_method(root: Path, item: "BranchItem", *,
                    containment: "Containment", fresh: bool,
                    ) -> tuple[str | None, str | None]:
    """``(method, refusal)`` — how this branch's deletion may be spelled.

    ``(DELETE_BRANCH_D, None)`` is the ordinary answer. ``(DELETE_CAS, note)``
    is the shape above. ``(None, why)`` means keep it, and ``why`` is printed.
    """
    refusal = delete_refusal(root, item.name, item.ref)
    if refusal is None:
        return DELETE_BRANCH_D, None
    if not fresh:
        return None, (f"{refusal}. (Remote knowledge is STALE, so this run will "
                      f"not weigh its own containment proof against that.)")
    if containment.contains(item.ref) is not True:
        return None, refusal
    return DELETE_CAS, (
        f"`git branch -d` would refuse this branch, and its refusal is about a "
        f"ref this planner never tested. The fetched base contains the branch's "
        f"entire content, so the deletion is emitted as "
        f"`git update-ref -d {item.ref} {item.tip[:12]}` — a compare-and-swap "
        f"git refuses if the branch has moved since this plan was written, plus "
        f"an explicit check that no worktree has it checked out. No -D, no "
        f"--force, no unset upstream, no deleted tracking ref, and the tip stays "
        f"pinned to its refs/agent-trash ref either way. "
        f"What `-d` said, verbatim: {refusal}")


# ── the main working tree, and what may never be moved ───────────────────────
#
# WHY NOT `os.getcwd()`, AND WHY NOT LIST ORDER. The bug this section exists for
# compared each worktree against the planner's own repository root. Run from a
# linked worktree — which is how agents run everything here — that root IS the
# linked worktree, so the MAIN working tree compared unequal to it and passed
# every "safe to retire" precondition. The fix cannot be a better spelling of
# "where am I": the question is not where the planner is, it is which directory
# owns the repository. Git answers that directly, and the answer does not
# depend on the asker.
#
# SHOULD THE WORKTREE THE PLANNER IS RUNNING INSIDE EVER BE PROPOSED?
# No — and this is a separate decision from the main-worktree rule, so it gets
# its own argument rather than inheriting one.
#   FOR proposing it: it is just a linked worktree like any other; a merged,
#   clean, unlocked worktree is exactly what this tool exists to retire, and
#   refusing it means an agent worktree can never be cleaned up by a planner an
#   agent runs — arguably the most common case there is.
#   AGAINST: the planner writes its own outputs INTO this root
#   (`local/workspace/cleanup-<id>.sh`, the matching `.json`, and the trash
#   directory every move lands in). Retiring it means the emitted script moves
#   the directory that contains the script — `sh local/workspace/cleanup-x.sh`
#   loses its own file mid-run, and `set -eu` then leaves a HALF-APPLIED plan,
#   which is the one outcome a tool whose whole justification is "safer than
#   doing it by hand" may not produce. The trash directory is derived from this
#   root too, so retiring it is precisely the self-nesting `mv` below. And the
#   owner's shell is very likely sitting inside it.
#   DECIDED: keep it. The asymmetry settles it — the cost of over-keeping is one
#   directory surviving until a run started from somewhere else, fully
#   recoverable and visible in the report; the cost of under-keeping is a
#   truncated destructive script. Note this rule is WEAKER than the
#   main-worktree rule on purpose: the main working tree is unretirable on every
#   invocation, while this one only says "not by this invocation", so the tool
#   does not become a no-op for agent worktrees — run it from the main working
#   tree and they are proposable again.


def _normalise(path: Path) -> Path:
    """Absolute and symlink-free, or absolute at least. Never raises."""
    try:
        return path.resolve()
    except OSError:
        return Path(os.path.abspath(str(path)))


def _rev_parse_paths(repo: Path, *flags: str) -> list[Path] | None:
    """Absolute answers to ``git rev-parse`` path flags, or None if git balked.

    ``None`` is NOT "no" — it is "unanswerable", and every caller here treats it
    as a reason to keep. A predicate that quietly returns False when git fails
    is how a directory nobody could classify becomes a directory something
    proposes to move.
    """
    if not repo.is_dir():
        return None
    result = _git(repo, "rev-parse", "--path-format=absolute", *flags)
    if result.returncode:
        # Older wording. The answers may come back relative, which the loop
        # below resolves against `repo` — `git -C repo` made it the cwd, and a
        # bare `.git` is exactly what the MAIN working tree prints.
        result = _git(repo, "rev-parse", *flags)
    if result.returncode:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != len(flags):
        return None
    answers: list[Path] = []
    for line in lines:
        path = Path(line)
        if not path.is_absolute():
            path = repo / path
        answers.append(_normalise(path))
    return answers


def is_main_worktree(path: Path) -> bool | None:
    """Git's own definition: ``--git-dir`` and ``--git-common-dir`` are equal.

    They are equal in the MAIN working tree and in no other, which makes this
    the one test that still holds when the planner runs FROM a linked worktree —
    the configuration that produced the incident. Returns ``None`` when git
    could not answer; callers keep on ``None``.
    """
    answered = _rev_parse_paths(path, "--git-dir", "--git-common-dir")
    if answered is None:
        return None
    git_dir, common_dir = answered
    return git_dir == common_dir


def main_worktree_verdicts(
        worktrees: Sequence[status.Worktree]) -> dict[Path, bool | None]:
    """``{path: True | False | None}`` — asked once, of each worktree."""
    return {_normalise(worktree.path): is_main_worktree(worktree.path)
            for worktree in worktrees}


def main_worktree_paths(root: Path,
                        verdicts: dict[Path, bool | None]) -> set[Path]:
    """Every path that could be the main working tree — a UNION, on purpose.

    The two errors do not cost the same. Keeping a linked worktree that was
    retirable wastes a directory until the next run and prints why. Retiring the
    main working tree moves the directory that physically contains ``.git``,
    every linked worktree's administrative data, and — when the planner runs
    from a linked worktree — the destination it is being moved into. So any one
    signal is enough:

    1. ``--git-dir`` == ``--git-common-dir``, per worktree (``verdicts``);
    2. the PARENT of ``--git-common-dir`` — ``<main>/.git`` for an ordinary
       checkout. This answers even for a worktree whose own directory cannot be
       queried, so signal 1 having failed does not leave the set empty;
    3. the FIRST record of ``git worktree list --porcelain``, which git
       documents as the main worktree. Corroboration only — nothing here rests
       on ordering, which is why it is third and not first.
    """
    found = {path for path, verdict in verdicts.items() if verdict}

    answered = _rev_parse_paths(root, "--git-common-dir")
    if answered:
        found.add(_normalise(answered[0].parent))

    listed = _git(root, "worktree", "list", "--porcelain")
    if listed.returncode == 0:
        for line in listed.stdout.splitlines():
            if line.startswith("worktree "):
                found.add(_normalise(Path(line[len("worktree "):].strip())))
                break
    return found


def _is_inside(inner: Path, outer: Path) -> bool:
    """True when *inner* IS *outer*, or lives beneath it."""
    return inner == outer or outer in inner.parents


def move_is_self_nesting(source: Path, destination: Path) -> bool:
    """``mv source destination`` where the destination is inside the source.

    Same filesystem, ``rename(2)`` returns EINVAL and ``mv`` refuses — which
    with ``set -eu`` aborts the script part-way through. ACROSS filesystems
    ``mv`` falls back to a recursive copy that walks into the destination it is
    creating. Neither outcome may be reachable from a script this tool wrote, so
    the line is never written. Tested in both the literal and the
    symlink-resolved spelling: either one saying "nested" is enough.
    """
    literal = (Path(os.path.abspath(str(source))),
               Path(os.path.abspath(str(destination))))
    resolved = (_normalise(source), _normalise(destination))
    return any(_is_inside(dst, src) for src, dst in (literal, resolved))


def contains_another_worktree(path: Path,
                              worktrees: Sequence[status.Worktree]) -> bool:
    """Does another live worktree registration sit inside this directory?

    Moving such a directory takes the nested worktree with it, leaving git
    pointing at a path that no longer exists — and the next ``mv`` in the same
    script fails on a source that vanished, aborting the run half-done. The
    ``.claude/worktrees`` layout makes this the ordinary shape here, not an
    exotic one.
    """
    here = _normalise(path)
    for other in worktrees:
        if other.gone:
            continue        # no directory to carry along
        there = _normalise(other.path)
        if there != here and _is_inside(there, here):
            return True
    return False


def _trash_root(root: Path, run_id: str) -> Path:
    """ABSOLUTE, deliberately.

    The destination used to be relative to a ``cd`` at the top of the script, so
    what a line actually moved a directory INTO depended on a command several
    lines earlier. The containment guard has to reason about the exact string
    that gets emitted, so the string is made absolute and self-contained.
    """
    return _normalise(root / OUTPUT_DIR / f"trash-{run_id}")


def _comment(text: str) -> str:
    """Flatten anything interpolated into a ``#`` line to a single safe line."""
    return _CONTROL_RE.sub("?", str(text))


def _wrap(text: str, width: int = 72) -> list[str]:
    """Break a fixed note into comment-width lines. Never splits a word."""
    lines: list[str] = []
    current = ""
    for word in _comment(text).split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def path_is_describable(path: str) -> bool:
    return _CONTROL_RE.search(path) is None


# ── the per-worktree reflog sweep ────────────────────────────────────────────
#
# `git worktree prune` removes `.git/worktrees/<id>/` — and `logs/HEAD` inside
# it is that worktree's ENTIRE HEAD history. Anything reachable from no ref and
# recorded only there becomes reachable from nothing the moment prune runs. The
# branch path has protected against exactly this since day one; this is the
# same discipline applied to the other half of what a retirement destroys.

_REF_COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _ref_component(name: str) -> str:
    """A slug that ``git update-ref`` will actually accept as one path part.

    ``slug`` guarantees the character class, not ref legality: a directory named
    ``..`` or ``.hidden`` slugs to something git refuses (a component may not
    start with ``.`` or contain ``..``, and may not end ``.lock``). A rejected
    ref would drop the worktree from the plan — safe, but for a reason that has
    nothing to do with the owner's work — so an unusable component degrades to a
    fixed stem instead. Collision is harmless: the commit id is the leaf, so two
    worktrees sharing a stem share a ref only when they share a commit, and then
    both writes set it to the same value.
    """
    candidate = slug(name)
    if (_REF_COMPONENT_RE.match(candidate) and ".." not in candidate
            and not candidate.endswith(".lock")):
        return candidate
    return "worktree"


def worktree_backup_ref(run_id: str, path: Path, oid: str) -> str:
    """``refs/agent-trash/<run>-worktrees/<dir>/<sha12>``.

    The second segment is deliberately NOT ``<run_id>``: branch backups live at
    ``refs/agent-trash/<run_id>/<branch-slug>``, and git cannot hold both a ref
    ``a/b`` and a ref ``a/b/c``. ``slug`` strips a branch name down to a single
    path part, so a branch backup is always exactly one level under the run id —
    giving worktrees their own sibling namespace makes the collision impossible
    by construction rather than unlikely.
    """
    return (f"{TRASH_REF_ROOT}/{run_id}-worktrees/"
            f"{_ref_component(path.name or 'worktree')}/{oid[:12]}")


def worktree_reflog_commits(worktree: Path) -> tuple[list[str], list[str]] | None:
    """``(HEAD reflog commits, stash commits)`` for one worktree, or None.

    ``None`` means UNANSWERABLE and every caller keeps on it — a worktree whose
    reflog cannot be read is a worktree whose losses cannot be enumerated, and
    proposing to move it would be guessing.

    The stash list is returned separately because it is an EXCLUSION, not an
    input. Measured: a ``git stash`` taken inside a linked worktree writes
    ``refs/stash`` and ``logs/refs/stash`` in the COMMON ref store, both of which
    outlive ``git worktree prune``. A stash entry is therefore not something this
    step endangers, and pinning one would be this tool taking custody of a risk
    it did not create. A failure to LIST stashes is tolerated rather than fatal:
    the only effect of an empty exclusion set is more backup refs, which is the
    safe direction.
    """
    reflog = _git(worktree, "reflog", "--format=%H", "HEAD")
    if reflog.returncode:
        return None
    stash = _git(worktree, "stash", "list", "--format=%H")
    stashed = stash.stdout.split() if stash.returncode == 0 else []
    return list(dict.fromkeys(reflog.stdout.split())), list(dict.fromkeys(stashed))


# ── the same sweep, for a worktree whose DIRECTORY is already gone ───────────
#
# THIS WAS THE HOLE, AND IT WAS THE DESTRUCTIVE ONE. `classify` used to send
# every worktree whose directory is missing straight to `action="prune"` and
# `continue` — BEFORE the reflog sweep this module was built around. `--execute`
# then ran `git worktree prune`, which deletes `.git/worktrees/<id>/` entire,
# `logs/HEAD` included, and the report called that step "pruned (metadata
# only)". Measured, with a control arm:
#
#   * a commit made while the worktree's HEAD was detached, after HEAD returned
#     to a branch, lives ONLY in that per-worktree reflog;
#   * the owner deleting the directory and running `git gc --prune=now` does NOT
#     lose it — the reflog is still there, still protecting it;
#   * `cleanup.py --execute` followed by the same `gc` DID lose it, with zero
#     backup refs written. The tool was the thing that destroyed it.
#
# The directory being gone does not make the reflog unreadable: the
# ADMINISTRATIVE directory is what holds it, and that outlives the working
# directory until prune runs. `git --git-dir=<admin> reflog HEAD` reads it
# (verified on git 2.55 against a directory removed with `rm -rf`), so the sweep
# the retire path gets is now run here too, and it can KEEP: a gone worktree
# whose reflog cannot be enumerated is not pruned at all.


def worktree_admin_dir(root: Path, worktree: Path) -> Path | None:
    """``<common>/worktrees/<id>`` for *worktree* — the reflog's last home.

    Found by reading each candidate's own ``gitdir`` file, which git maintains
    as ``<worktree>/.git``, rather than by guessing the id from the directory
    name: git derives that id from the basename but disambiguates collisions
    with a numeric suffix, so the name is a hint and the ``gitdir`` file is the
    fact. ``None`` means "could not be identified" and every caller keeps on it.
    """
    answered = _rev_parse_paths(root, "--git-common-dir")
    if not answered:
        return None
    target = _normalise(worktree)
    try:
        candidates = sorted((answered[0] / "worktrees").iterdir())
    except OSError:
        return None
    for candidate in candidates:
        try:
            recorded = (candidate / "gitdir").read_text(
                encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if recorded and _normalise(Path(recorded).parent) == target:
            return candidate
    return None


def gone_worktree_reflog_commits(root: Path, worktree: Path,
                                 ) -> tuple[list[str], list[str]] | None:
    """``worktree_reflog_commits`` for a worktree with no working directory.

    Same contract, same ``None``-is-unanswerable rule. ``git -C <root>`` supplies
    a working directory that exists while ``--git-dir=<admin>`` names the store
    the reflog is in, which is the only spelling that answers once the
    worktree's own directory has been removed.
    """
    admin = worktree_admin_dir(root, worktree)
    if admin is None:
        return None
    where = f"--git-dir={admin}"
    reflog = _git(root, where, "reflog", "--format=%H", "HEAD")
    if reflog.returncode:
        return None
    stash = _git(root, where, "stash", "list", "--format=%H")
    stashed = stash.stdout.split() if stash.returncode == 0 else []
    return list(dict.fromkeys(reflog.stdout.split())), list(dict.fromkeys(stashed))


def unreachable_commits(repo: Path, oids: Sequence[str], *,
                        protected: Sequence[str] = ()) -> list[str] | None:
    """Which of *oids* no surviving ref can reach. ``None`` if git could not say.

    BOUNDED BY CONSTRUCTION. ``--not --all`` makes the walk stop at every ref in
    the repository, so what it enumerates is only the commits that are already
    orphaned — never history. The answer is then INTERSECTED back with *oids*:
    the walk also reports an orphan's orphaned ancestors, and a ref at the
    descendant already makes those reachable, so pinning them too would be
    ``N`` refs where one does the job.

    ``--single-worktree`` is not optional. Without it ``--all`` also pretends
    every OTHER worktree's HEAD is a ref — including the HEAD of the worktree
    being retired, and of any other worktree the same script is about to move.
    Counting a ref that this plan destroys as protection is precisely the bug.
    """
    if not oids:
        return []
    unique = list(dict.fromkeys(oids))
    result = _git(repo, "rev-list", "--single-worktree", "--ignore-missing",
                  *unique, "--not", "--all", *protected)
    if result.returncode:
        return None
    walked = set(result.stdout.split())
    return [oid for oid in unique if oid in walked]


def plan_worktree_backups(repo: Path, item: WorktreeItem, worktree: Path, *,
                          run_id: str, gone: bool = False) -> list[str]:
    """Fill ``item.backups``; return the reasons to KEEP it instead, if any.

    ``gone`` selects where the reflog is read from — the worktree itself, or the
    administrative directory that outlives it. Everything after that is
    identical on purpose: one cap, one exclusion set, one ref-naming scheme, one
    place for the fail-closed answers to be forgotten.
    """
    enumerated = (gone_worktree_reflog_commits(repo, worktree) if gone
                  else worktree_reflog_commits(worktree))
    if enumerated is None:
        return [KEEP_NO_REFLOG]
    reflog, stashed = enumerated
    orphans = unreachable_commits(repo, reflog, protected=stashed)
    if orphans is None:
        return [KEEP_NO_REFLOG]
    if len(orphans) > MAX_WORKTREE_BACKUP_REFS:
        return [f"{len(orphans)} {KEEP_TOO_MANY_ORPHANS}"]
    item.backups = [(worktree_backup_ref(run_id, worktree, oid), oid)
                    for oid in orphans]
    return []


# ── classification ───────────────────────────────────────────────────────────

def classify(repo: status.Repository, root: Path, *, run_id: str,
             ledger: LedgerRisk | None = None,
             include_harness: bool = False,
             containment: Containment | None = None,
             fresh: bool = False,
             ) -> tuple[list[BranchItem], list[WorktreeItem]]:
    base_ref = repo.base_ref
    risk = ledger if ledger is not None else LedgerRisk()
    owned = containment is None
    if containment is None:
        containment = Containment(root, base_ref)
    try:
        return _classify(repo, root, run_id=run_id, risk=risk,
                         include_harness=include_harness,
                         containment=containment, fresh=fresh)
    finally:
        if owned:
            containment.close()


def _classify(repo: status.Repository, root: Path, *, run_id: str,
              risk: LedgerRisk, include_harness: bool,
              containment: Containment, fresh: bool,
              ) -> tuple[list[BranchItem], list[WorktreeItem]]:
    base_ref = repo.base_ref
    worktree_refs = {
        branch.ref.full_name for branch in repo.branches if branch.worktree_path
    }
    branches: list[BranchItem] = []
    for branch in repo.branches:
        if branch.scope == "R":
            continue
        item = BranchItem(
            name=branch.name, ref=branch.ref.full_name, tip=branch.ref.oid,
            state=branch.state, merged=branch.merged, intent=branch.intent,
            age_seconds=branch.age_seconds,
        )
        if branch.name in PROTECTED:
            item.keep_reasons.append(KEEP_PROTECTED)
        if base_ref is not None and branch.ref.full_name == base_ref:
            item.keep_reasons.append(KEEP_BASE)
        if branch.wedged_at is not None:
            item.keep_reasons.append(KEEP_WEDGED)
        elif branch.ref.full_name in worktree_refs:
            item.keep_reasons.append(KEEP_WORKTREE)
        contained = containment.contains(branch.ref.full_name)
        if branch.merged == "unmerged":
            item.keep_reasons.append(KEEP_UNMERGED)
        elif branch.merged not in ("merged", "main"):
            item.keep_reasons.append(KEEP_UNKNOWN_MERGE)
        elif contained is not True and branch.ref.full_name != base_ref:
            # The dashboard said contained and this tool's own probe did not.
            # A disagreement about whether deleting this loses content is
            # settled by the more conservative answer, every time.
            item.keep_reasons.append(KEEP_NOT_CONTAINED)
        if not _SAFE_NAME_RE.match(branch.name):
            item.keep_reasons.append(KEEP_UNSAFE_NAME)
        item.unpushed = unpushed_commits(root, branch.ref.full_name)
        if item.unpushed != 0:
            count = "an unknown number of" if item.unpushed < 0 else str(item.unpushed)
            # THE RULE THAT WAS UNSATISFIABLE. "Every commit exists on a remote"
            # is a proxy for "deleting this loses nothing", and after a
            # squash-merge whose head branch GitHub deleted it is a proxy that
            # can never be satisfied again while the thing it stands for is
            # plainly true: the base ref holds every byte the branch had. So the
            # proxy yields to the fact — but only to a FRESH, positively proven
            # fact, and never to an unanswerable one.
            if item.unpushed > 0 and fresh and contained is True:
                item.notes.append(
                    f"{count} commit(s) here are on no remote-tracking ref "
                    f"(the shape a squash-merge plus a deleted head branch "
                    f"leaves behind, permanently). Waived because the FETCHED "
                    f"base ref contains this branch's entire content and the "
                    f"tip is pinned to a backup ref before anything deletes it")
            else:
                item.keep_reasons.append(f"{count} {KEEP_UNPUSHED}")
        item.keep_reasons.extend(
            ledger_keep_reasons(root, branch.ref.full_name, risk))
        # LAST among the branch probes, and asked of the ref rather than of the
        # plan: whatever the containment test decided, the emitted line has to
        # be one git will accept, and a command that is going to be refused is
        # not a proposal — it is a script that stops.
        method, detail = deletion_method(root, item, containment=containment,
                                         fresh=fresh)
        if method is None:
            item.keep_reasons.append(detail or KEEP_DELETE_REFUSED)
        else:
            item.delete_method = method
            if detail:
                item.notes.append(detail)
        if item.proposed:
            # The tip sha is part of the ref name, not decoration. `slug` maps
            # `/` to `-`, so `feat/a` and `feat-a` produced ONE ref name; the
            # second `update-ref` silently clobbered the first and both rows
            # still said `backup_written: true`, while the script printed
            # "Nothing was lost". Measured end to end: one tip became
            # unrecoverable. Two names can still share a ref only when they
            # share a TIP, and then both writes set the same value.
            item.backup_ref = (f"{TRASH_REF_ROOT}/{run_id}/"
                               f"{slug(branch.name)}-{branch.ref.oid[:12]}")
        branches.append(item)

    worktrees: list[WorktreeItem] = []
    branch_state = {b.ref.full_name: b for b in repo.branches}
    verdicts = main_worktree_verdicts(repo.worktrees)
    main_paths = main_worktree_paths(root, verdicts)
    trash = _trash_root(root, run_id)
    here = _normalise(root)
    for worktree in repo.worktrees:
        path = str(worktree.path)
        item = WorktreeItem(
            path=path, branch=worktree.branch_ref, action="keep",
            gone=worktree.gone, locked=worktree.locked is not None,
            dirty_paths=len(worktree.changes), detached=worktree.detached,
            status_error=worktree.status_error,
        )
        if worktree.gone:
            if item.locked:
                # Measured: `git worktree prune` will NOT clear a locked
                # registration, and git suppresses the `prunable` annotation
                # for it, so this entry wedges its branch invisibly and
                # indefinitely. Clearing it needs a doubled `-f -f`, which this
                # tool will never pass. Unlocking is the owner's decision.
                item.keep_reasons.append(KEEP_LOCKED_GONE)
            else:
                # NOT "metadata only". Pruning deletes this registration's
                # `logs/HEAD`, which is the ONLY record of every commit the
                # worktree made while its HEAD was detached — so the sweep runs
                # here, FIRST, exactly as it does on the retire path, and its
                # answer can keep the entry instead of pruning it.
                item.keep_reasons.extend(plan_worktree_backups(
                    root, item, worktree.path, run_id=run_id, gone=True))
                if not item.keep_reasons:
                    # Now, and only now, is this the un-ceremonious deletion the
                    # module always claimed it was: the directory is gone and
                    # everything its reflog held is pinned. It UN-WEDGES the
                    # branch, which git otherwise leaves unusable for three
                    # months (gc.worktreePruneExpire).
                    item.action = "prune"
            worktrees.append(item)
            continue
        # ── the never-move guards, before anything that could say "retire" ───
        where = _normalise(worktree.path)
        verdict = (verdicts[where] if where in verdicts
                   else is_main_worktree(worktree.path))
        if verdict is None:
            item.keep_reasons.append(KEEP_MAIN_UNPROVEN)
        elif verdict or where in main_paths:
            item.keep_reasons.append(KEEP_MAIN)
        if where == here:
            item.keep_reasons.append(KEEP_RUNNING_HERE)
        if contains_another_worktree(worktree.path, repo.worktrees):
            item.keep_reasons.append(KEEP_CONTAINS_WORKTREE)
        if move_is_self_nesting(worktree.path, trash / (worktree.path.name or "x")):
            item.keep_reasons.append(KEEP_SELF_NESTING)
        if not path_is_describable(path):
            item.keep_reasons.append(KEEP_UNSAFE_PATH)
        item.harness = HARNESS_WORKTREE_MARKER in path.replace("\\", "/")
        if item.harness and not include_harness:
            item.keep_reasons.append(KEEP_HARNESS)
        if item.locked:
            item.keep_reasons.append(KEEP_LOCKED)
        if worktree.status_error:
            # FAIL CLOSED. `status.py` records the failure and leaves `changes`
            # EMPTY, so a worktree whose `git status` cannot run — a corrupt
            # index is what a killed agent session leaves behind — used to read
            # as CLEAN here and be retired with its untracked files inside it.
            # The module's own rule already said so: "None is NOT 'no' — it is
            # 'unanswerable', and every caller here treats it as a reason to
            # keep." This caller did not, and now does.
            item.keep_reasons.append(
                f"{KEEP_STATUS_UNREADABLE}: {_comment(worktree.status_error)}")
        if worktree.changes:
            # Untracked and ignored files have NO git recovery story — measured:
            # zero blobs recoverable after `worktree remove --force`.
            item.keep_reasons.append(
                f"{len(worktree.changes)} {KEEP_DIRTY}")
        held = branch_state.get(worktree.branch_ref) if worktree.branch_ref else None
        if held is not None and held.merged not in ("merged", "main"):
            item.keep_reasons.append(KEEP_UNMERGED)
        if held is None and worktree.detached:
            # "NO BRANCH" IS NOT "NO EVIDENCE", AND THIS WAS THE UNWAIVABLE KEEP.
            # Every Claude Code harness worktree is detached by construction, so
            # an unconditional keep here fired on 100% of them, forever:
            # `--include-harness-worktrees` waived the harness rule and landed
            # on this one, which no flag could waive. That is the owner's actual
            # complaint — "every time an agent finishes it leaves a branch or
            # worktree and I have to clean it up by hand" — implemented.
            #
            # The polarity was being read backwards. Git REFUSES to delete a
            # branch that a worktree has checked out; a worktree sitting
            # detached at a commit the base already contains is the state that
            # makes cleanup POSSIBLE, not the state that blocks it. The harness's
            # completion signal was being treated as a blocker.
            #
            # So the question is answered with evidence instead of refused for
            # lack of a name: does the FETCHED base contain the commit this
            # worktree is sitting on? If yes, retiring it loses no content. If
            # no — which is precisely the shape of an unpushed experiment, the
            # documented data-loss report (claude-code#74719) where a detached
            # worktree holding an unpushed commit was reaped on AGE alone — it
            # is kept. Age is never sufficient and is not consulted here at all.
            # Whatever else the reflog holds is swept and pinned below, and an
            # unreadable reflog still keeps the worktree.
            if not fresh:
                item.keep_reasons.append(
                    f"{KEEP_DETACHED_UNCONTAINED} — and this run has no "
                    f"--fetch, so there is no fetched base to test it against")
            elif containment.contains(worktree.head) is not True:
                item.keep_reasons.append(KEEP_DETACHED_UNCONTAINED)
            else:
                item.notes.append(
                    f"detached HEAD at {worktree.head[:12]}, which the fetched "
                    f"base ref already contains — no branch to judge it by, but "
                    f"nothing here is the last holder of any content either")
        if not item.keep_reasons:
            # LAST, and only for a worktree everything else already cleared.
            # The sweep costs two git calls per candidate, and asking it of a
            # worktree that is kept anyway would be spending them to learn
            # nothing. Its own answer can still keep the worktree.
            item.keep_reasons.extend(
                plan_worktree_backups(root, item, worktree.path, run_id=run_id))
        if not item.keep_reasons:
            item.action = "retire"
        worktrees.append(item)
    hold_back_prunes(worktrees)
    return branches, worktrees


def hold_back_prunes(worktrees: Sequence[WorktreeItem]) -> bool:
    """All gone registrations get pruned this run, or none of them do.

    ``git worktree prune`` HAS NO TARGET. It sweeps every prunable registration
    in the repository, so a per-item KEEP on one gone worktree — its reflog
    could not be read, its orphans exceeded the cap, its backup refs did not
    resolve — is not a decision `prune` can honour. Left alone, one item's
    fail-closed answer would be overruled by another item's fail-open one, and
    the commits the KEEP existed to protect would be destroyed anyway.

    So the run refuses as a whole and says which entry stopped it. A locked
    gone registration is not counted: git declines to prune those regardless,
    which is precisely why they wedge their branch.
    """
    blocked = [item for item in worktrees
               if item.gone and not item.locked and item.action != "prune"]
    if not blocked:
        return False
    for item in worktrees:
        if item.action == "prune":
            item.action = "keep"
            item.keep_reasons.append(
                f"{KEEP_PRUNE_HELD_BACK}: {_comment(blocked[0].path)}")
    return True


# ── the non-destructive half of --execute ────────────────────────────────────

def _pin(root: Path, ref: str, oid: str, run_id: str) -> bool:
    """Write one backup ref and READ IT BACK. The only place either happens.

    Branch tips and worktree reflog commits go through this same function on
    purpose: two spellings of "write a backup ref" is two places for the verify
    to be forgotten, and the verify is the entire value of the write.

    THE WRITE IS A COMPARE-AND-SWAP, and the read-back checks the VALUE. The
    trailing ``""`` is git's own spelling of "this ref must not already exist",
    so a second write can never land ON a backup ref a first write is holding.
    That was a measured loss, not a hypothetical: ``slug`` maps ``/`` to ``-``,
    so ``feat/a`` and ``feat-a`` derived the same ref name and the plain
    ``update-ref`` used here silently overwrote the first tip with the second —
    both rows reporting ``backup_written: true``, the script printing "Nothing
    was lost", one tip unrecoverable after the ordinary
    fetch --prune / gc sequence.

    A failed write is deliberately not fatal by itself: writing the SAME oid
    again is how a re-run of the same plan behaves, and that is idempotent
    rather than wrong. What decides is the read-back, and it now compares the
    oid rather than merely resolving the ref — so a ref standing at somebody
    else's commit fails here instead of being reported as a backup.
    """
    _git(root, "update-ref", "-m", f"pre-delete backup ({TOOL} run {run_id})",
         ref, oid, "")
    resolved = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return resolved.stdout.strip() == oid


def write_backup_refs(root: Path, items: Sequence[BranchItem], run_id: str,
                      *, archive_tag: bool,
                      worktrees: Sequence[WorktreeItem] = ()) -> list[Blocking]:
    """Make every proposed tip reachable BEFORE anything could remove it.

    Order is not negotiable: ref first, verify second, and an item that fails
    verification is dropped from the plan rather than carried into a script.
    Worktrees are held to the identical rule — a retirement whose reflog backup
    did not resolve becomes a KEEP, because the alternative is a ``mv`` followed
    by a ``git worktree prune`` with nothing standing behind it.
    """
    blocking: list[Blocking] = []
    for item in items:
        if not item.proposed or item.backup_ref is None:
            continue
        ref = item.backup_ref
        if not _pin(root, ref, item.tip, run_id):
            item.keep_reasons.append(KEEP_NO_BACKUP)
            blocking.append(Blocking(
                CODE_BACKUP_REF_FAILED, item.name,
                f"the backup ref {ref} did not resolve to {item.tip[:8]}; "
                f"{item.name} was dropped from the plan"))
            continue
        item.backup_ref = ref
        item.backup_written = True
        if archive_tag:
            tag = f"{ARCHIVE_TAG_PREFIX}/{slug(item.name)}-{item.tip[:7]}"
            tagged = _git(root, "tag", "-a", tag, item.tip, "-m",
                          f"retired branch {item.name} ({TOOL} run {run_id})")
            if tagged.returncode == 0 or "already exists" in tagged.stderr:
                item.archive_tag = tag

    # "retire" AND "prune". The prune path was the one with no backups at all:
    # `git worktree prune` deletes the registration's `logs/HEAD`, which is
    # every bit as destructive as the `mv` the retire path performs, and this
    # tool runs the prune ITSELF under --execute rather than emitting it.
    for worktree in worktrees:
        if worktree.action not in ("retire", "prune") or not worktree.backups:
            continue
        failed = [(ref, oid) for ref, oid in worktree.backups
                  if not _pin(root, ref, oid, run_id)]
        if failed:
            worktree.action = "keep"
            worktree.keep_reasons.append(KEEP_NO_REFLOG_BACKUP)
            ref, oid = failed[0]
            blocking.append(Blocking(
                CODE_BACKUP_REF_FAILED, worktree.path,
                f"the reflog backup ref {ref} did not resolve to {oid[:8]}; "
                f"{worktree.path} was dropped from the plan"))
            continue
        worktree.backups_written = True
    # A worktree just dropped from the plan may have been the only thing
    # standing between `git worktree prune` and another entry's reflog.
    hold_back_prunes(worktrees)
    return blocking


def prune_gone_worktrees(root: Path, items: Sequence[WorktreeItem]) -> bool:
    """``git worktree prune`` — metadata only, and only when something is gone.

    The result is READ BACK rather than assumed: prune silently declines a
    locked registration, and a tool that reported "pruned" for one would be
    telling the owner their branch is usable when it is still wedged.

    ASKED AGAIN HERE, on purpose. ``hold_back_prunes`` is the classifier's
    answer; this is the last word before the one destructive thing this process
    performs itself, and `prune` sweeping EVERY prunable registration is exactly
    the shape where "the classifier surely decided that" is how a fail-closed
    keep gets overruled by an unrelated item.
    """
    targets = [item for item in items if item.action == "prune"]
    if not targets or hold_back_prunes(items):
        return False
    result = _git(root, "worktree", "prune")
    if result.returncode:
        return False
    listed = _git(root, "worktree", "list", "--porcelain").stdout
    still_registered = {line[len("worktree "):].strip()
                        for line in listed.splitlines()
                        if line.startswith("worktree ")}
    for item in targets:
        item.pruned = item.path not in still_registered
    return True


# ── the emitted script (the destructive half — for the owner to run) ─────────

def _unique_destination(trash: Path, source: Path, taken: set[Path]) -> Path:
    """A destination no other move in this run already claims.

    ``mv a b`` where ``b`` is an EXISTING DIRECTORY moves ``a`` INSIDE ``b``.
    Two worktrees sharing a basename — ``.../one/agent-1`` and
    ``.../two/agent-1`` — would therefore nest the second inside the first
    rather than landing beside it, and the plan's own trash directory would be
    the thing that swallowed a worktree.
    """
    stem = source.name or "worktree"
    candidate = trash / stem
    suffix = 2
    while _normalise(candidate) in taken:
        candidate = trash / f"{stem}-{suffix}"
        suffix += 1
    return candidate


def plan_moves(*, root: Path, run_id: str, worktrees: Sequence[WorktreeItem],
               ) -> tuple[list[tuple[WorktreeItem, Path]],
                          list[tuple[WorktreeItem, str]]]:
    """Pair each retiring worktree with a destination that CANNOT be inside it.

    This deliberately re-derives what ``classify`` already decided. ``build_script``
    is the ONLY place a destructive line is ever written, so it is the only
    place where "a ``mv`` whose destination is inside the thing being moved must
    be impossible by construction" can actually be made true: a classifier
    refactor that drops a check, or a future caller handing this function a
    hand-made list, still cannot get such a line out of it.

    Returns ``(moves, refused)``. A refusal is never silent — the script says so
    in a comment, because the two halves of this tool disagreeing is itself a
    finding.
    """
    trash = _trash_root(root, run_id)
    moves: list[tuple[WorktreeItem, Path]] = []
    refused: list[tuple[WorktreeItem, str]] = []
    taken: set[Path] = set()
    for item in worktrees:
        if item.action != "retire":
            continue
        source = Path(item.path)
        if not path_is_describable(item.path):
            refused.append((item, "its path holds a control character"))
            continue
        # Asked again, of the directory itself, at emission time.
        if is_main_worktree(source) is not False:
            refused.append((item, "it is the main working tree, or git could "
                                  "not prove that it is not"))
            continue
        if _normalise(source) == _normalise(root):
            refused.append((item, "the planner is running from inside it"))
            continue
        destination = _unique_destination(trash, source, taken)
        if move_is_self_nesting(source, destination):
            refused.append((item, "every destination this run can offer is "
                                  "inside it"))
            continue
        taken.add(_normalise(destination))
        moves.append((item, destination))
    return moves, refused


def plan_deletions(*, root: Path, branches: Sequence[BranchItem],
                   containment: Containment, fresh: bool,
                   ) -> tuple[list[BranchItem], list[tuple[BranchItem, str]]]:
    """The branches whose deletion may be WRITTEN, and how each one is spelled.

    The same construction argument as ``plan_moves``, applied to the other
    destructive verb this tool emits. ``classify`` already asked
    ``deletion_method``; asking again here is what makes "no emitted line is one
    git will predictably refuse" true of the EMITTER rather than of a classifier
    that a later refactor might change. A disagreement between the two is not
    silently reconciled — it is written into the script as a finding.

    The containment probe is asked again here for the same reason, and it is the
    reason it is asked at all: a compare-and-swap deletion may be written ONLY
    behind a fresh, positive containment proof, and this is the only place a
    destructive line is ever written.
    """
    emit: list[BranchItem] = []
    refused: list[tuple[BranchItem, str]] = []
    for item in branches:
        if not item.proposed:
            continue
        method, why = deletion_method(root, item, containment=containment,
                                      fresh=fresh)
        if method is None:
            refused.append((item, why or KEEP_DELETE_REFUSED))
            continue
        item.delete_method = method
        emit.append(item)
    return emit, refused


def apply_emitter_refusals(root: Path, run_id: str,
                           worktrees: Sequence[WorktreeItem],
                           branches: Sequence[BranchItem] = (),
                           *, containment: Containment | None = None,
                           base_ref: str | None = None,
                           fresh: bool = False) -> None:
    """Make the PLAN agree with what the emitter will actually write.

    ``plan_moves`` and ``plan_deletions`` are the last word on whether a
    destructive line can be emitted, so both are asked here too, before the plan
    object exists. A reader of ``cleanup-<id>.json`` therefore never sees
    ``"action": "retire"`` for a worktree the script declines to move, nor
    ``"proposed": true`` for a branch the script declines to delete: the plan and
    the script cannot disagree, because only one of them decides.
    """
    _, refused = plan_moves(root=root, run_id=run_id, worktrees=worktrees)
    for item, why in refused:
        item.action = "keep"
        item.keep_reasons.append(f"the emitter refused to write its move: {why}")
    owned = containment is None
    if containment is None:
        containment = Containment(root, base_ref)
    try:
        _, declined = plan_deletions(root=root, branches=branches,
                                     containment=containment, fresh=fresh)
    finally:
        if owned:
            containment.close()
    for branch, why in declined:
        branch.backup_ref = None
        branch.keep_reasons.append(
            f"the emitter refused to write its deletion: {why}")


# ── per-item isolation in the emitted script ─────────────────────────────────
#
# `set -eu` stays at the top: `cd` into the wrong directory, a trash directory
# that could not be created, or an unset variable must all still stop everything
# before a destructive line runs. What must NOT be fatal to the whole run is one
# ITEM declining. Measured on this repository: the plan proposed three branches,
# the first `git branch -d` was refused, and `set -e` ended the script there —
# two safe deletions never ran and the operator was left with a failure that
# named neither what had worked nor what had not.
#
# The shape below puts every item's guards in an `if` CONDITION, where POSIX
# suspends `set -e` (verified on sh, bash --posix, zsh and dash for a failing
# command, a failing function, and a braced `&&` chain). The backup ref keeps
# its veto — it just vetoes THAT item now instead of the file — and the run
# still fails overall through the summary's `exit 1`.
#
# The `git update-ref <ref> <oid>` line is written out literally rather than
# hidden behind a shell helper. This script's whole justification is that a
# human reads it before running it, and "which object is being pinned where" is
# the one thing that reader must be able to check without resolving an
# indirection.

_SUMMARY_DONE = "cleanup_done"
_SUMMARY_REFUSED = "cleanup_refused"
_SUMMARY_COUNT = "cleanup_refusals"


def _pin_condition(backups: Sequence[tuple[str, str]], *,
                   lead: str = "if ! { ") -> list[str]:
    """The guard clause: pin every ref and read every one of them back.

    Emitted as a single ``if ! { … && … ; }`` condition so that one unresolved
    backup ref stops this item's destructive line and nothing else's.

    TWO THINGS CHANGED HERE, both of them the same measured bug. The write is a
    compare-and-swap — the trailing ``''`` is git's "this ref must not already
    exist" — and the read-back compares the OID rather than merely resolving the
    ref. Without the first, two branches whose slugs collided wrote the same ref
    in sequence and the second silently replaced the first. Without the second,
    a ref standing at somebody else's commit reads back fine and the deletion
    proceeds behind a backup of the wrong object.

    The write is allowed to fail (``|| :``) and the VERIFY decides. Writing the
    same oid to the same ref again is what a re-run of this plan does — and what
    ``--execute`` already did before this script was ever read — so refusing on
    "already exists" would turn every second run into a wall of refusals. What
    can never pass is the verify seeing a different oid.
    """
    if not backups:
        return []
    lines: list[str] = []
    for index, (ref, oid) in enumerate(backups):
        prefix = lead if index == 0 else " " * len(lead)
        pad = " " * len(lead)
        verify = shlex.quote(ref + "^{commit}")
        lines.append(f"{prefix}{{ git update-ref -m 'pre-delete backup' "
                     f"{shlex.quote(ref)} {oid} '' 2>/dev/null || :; }} &&")
        lines.append(f"{pad}[ \"$(git rev-parse --verify --quiet {verify})\" "
                     f"= {oid} ] &&")
    # Drop the trailing `&&` of the last verify and close the group.
    lines[-1] = lines[-1][:-len(" &&")] + "; }; then"
    return lines


def _runtime_guards() -> list[str]:
    """Re-measure, at RUN time, what the plan measured at PLAN time.

    THE ASYMMETRY THIS CLOSES. ``git branch -d`` performs its own check when it
    runs, so the branch path was always safe against the world changing between
    a plan being written and being run: raced with new unmerged commits, it
    refused, exit 1, branch intact. Nothing did that for a worktree, because
    ``mv`` has no opinion. Measured: a worktree that was clean and unlocked at
    plan time gained an untracked file and a lock reading
    ``claude agent … (pid …)``; the script moved it anyway, out from under a
    live process's working directory, and then ``git worktree prune`` declined
    the LOCKED registration — leaving the branch permanently wedged, while the
    summary said "every item in this plan completed" and exited 0.

    So every precondition is asked again, of the world as it is now:

    * ``cleanup_worktree_ready`` — the directory still exists and is still a
      worktree; it is NOT the main working tree (``--git-dir`` == the common
      dir); no ``locked`` file sits in its administrative directory; and
      ``git status`` runs AND is empty. An unanswerable probe returns non-zero,
      so unreadable is refused exactly like dirty is.
    * ``cleanup_branch_free`` — no worktree has this branch checked out. That is
      the other thing ``git branch -d`` checks and a compare-and-swap deletion
      does not, so it is asked explicitly wherever the compare-and-swap is used.

    Both are called from ``if`` CONDITIONS, where POSIX suspends ``set -e``
    (verified on sh, bash, zsh and dash, for a failing command inside a function
    body), so a refusal records itself and the next item still runs.
    """
    return [
        "# ── run-time re-checks ─────────────────────────────────────────────",
        "# The plan measured all of this when it was WRITTEN. `git branch -d`",
        "# re-measures its own preconditions when it RUNS; `mv` and",
        "# `git update-ref -d` do not, so these do it for them. A worktree that",
        "# has since been locked by a live agent, or has gained uncommitted",
        "# files, or whose `git status` no longer answers, is NOT moved.",
        "cleanup_worktree_ready() {",
        "    cleanup_gd=$(git -C \"$1\" rev-parse --absolute-git-dir 2>/dev/null) "
        "|| return 1",
        "    cleanup_cd=$(git -C \"$1\" rev-parse --path-format=absolute "
        "--git-common-dir 2>/dev/null) || return 1",
        "    [ \"$cleanup_gd\" != \"$cleanup_cd\" ] || return 1",
        "    [ ! -e \"$cleanup_gd/locked\" ] || return 1",
        "    cleanup_dirt=$(git -C \"$1\" status --porcelain "
        "--untracked-files=all 2>/dev/null) || return 1",
        "    [ -z \"$cleanup_dirt\" ] || return 1",
        "}",
        "cleanup_branch_free() {",
        "    ! git worktree list --porcelain | grep -Fqx \"branch $1\"",
        "}",
        "",
    ]


def _record(kind: str, subject: str, detail: str = "") -> str:
    """One call to the summary bookkeeping the script defines for itself."""
    if kind == "done":
        return f"    record_done {shlex.quote(_comment(subject))}"
    return (f"    record_refused {shlex.quote(_comment(subject))} "
            f"{shlex.quote(_comment(detail))}")


def _summary_helpers() -> list[str]:
    """The bookkeeping every item reports into, and nothing else.

    Entries carry their own trailing newline, so the summary prints with
    ``printf %s`` and needs no separator handling — and no temporary file, which
    this script may not create. The newline is built with the ``printf '\\nx'``
    idiom rather than written literally between two quotes: a raw newline inside
    a shell string leaves a line of this file holding one unbalanced quote, and
    an emitted script has to stay parseable line by line — the suite's own
    ``mv``-auditing helper reads it that way, and so does a human.
    """
    return [
        "# Per-item bookkeeping. One item refusing is a FINDING to report, not a",
        "# reason to abandon the independent items after it — but the run still",
        "# fails at the end, so a refusal can never be read as success.",
        f"{_SUMMARY_DONE}=''",
        f"{_SUMMARY_REFUSED}=''",
        f"{_SUMMARY_COUNT}=0",
        "cleanup_nl=$(printf '\\nx')",
        "cleanup_nl=${cleanup_nl%x}",
        "record_done() {",
        f'    {_SUMMARY_DONE}="${{{_SUMMARY_DONE}}}  done     $1${{cleanup_nl}}"',
        "}",
        "record_refused() {",
        f'    {_SUMMARY_REFUSED}="${{{_SUMMARY_REFUSED}}}  REFUSED  '
        f'$1${{cleanup_nl}}           $2${{cleanup_nl}}"',
        f"    {_SUMMARY_COUNT}=$(({_SUMMARY_COUNT} + 1))",
        "}",
        "",
    ]


def _summary_footer() -> list[str]:
    """Name what completed, name what refused, and exit non-zero if any did."""
    note = ("A refusal is a finding: report it, and read the header of this "
            "file before reaching for a stronger flag.")
    return [
        "# The summary. An operator who scrolled past the middle of this run has",
        "# to be able to read the outcome of every item off the last few lines,",
        "# and an exit code that is 0 only when every item completed.",
        "echo ''",
        "echo 'workspace cleanup summary'",
        f'printf %s "${{{_SUMMARY_DONE}}}"',
        f'printf %s "${{{_SUMMARY_REFUSED}}}"',
        f'if [ "${{{_SUMMARY_COUNT}}}" -ne 0 ]; then',
        f'    echo "${{{_SUMMARY_COUNT}}} item(s) refused; the items above them '
        f'still ran." >&2',
        "    echo 'A refused item was NOT performed, and every tip this run "
        "did delete is pinned to its own refs/agent-trash ref.' >&2",
        f"    echo {shlex.quote(note)} >&2",
        "    exit 1",
        "fi",
        "echo 'every item in this plan completed.'",
        "",
    ]


def build_script(*, run_id: str, root: Path, base_ref: str | None, stale: bool,
                 branches: Sequence[BranchItem],
                 worktrees: Sequence[WorktreeItem],
                 containment: Containment | None = None,
                 include_harness: bool = False) -> str:
    trash = _trash_root(root, run_id)
    owned = containment is None
    if containment is None:
        containment = Containment(root, base_ref)
    try:
        proposed, declined = plan_deletions(root=root, branches=branches,
                                            containment=containment,
                                            fresh=not stale)
    finally:
        if owned:
            containment.close()
    moves, refused = plan_moves(root=root, run_id=run_id, worktrees=worktrees)
    lines = [
        "#!/bin/sh",
        f"# workspace cleanup — run {_comment(run_id)}",
        f"# generated by {TOOL} at {_now().strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "#",
        "# THIS SCRIPT IS THE DESTRUCTIVE HALF. The planner ran none of it.",
        "# Read it before running it; then run it with:  sh " +
        shlex.quote(str(OUTPUT_DIR / f'cleanup-{run_id}.sh')),
        "#",
        f"# base ref used for the containment test: "
        f"{_comment(base_ref) if base_ref else '(none)'}",
        "# Every branch below writes its backup ref FIRST and verifies its VALUE,",
        "# so a tip is reachable before anything can remove it, and no backup ref",
        "# can be written over another one (it is a compare-and-swap).",
        "# `git branch -d` is used deliberately: it refuses an unmerged branch.",
        "# IF IT REFUSES, THAT IS A FINDING — report it. Do not reach for -D;",
        "# there is no --force in this tooling at all.",
        "# A branch `-d` structurally cannot accept — a squash-merge whose head",
        "# branch the remote deleted — is deleted by `git update-ref -d <ref>",
        "# <tip>` instead: a COMPARE-AND-SWAP git refuses unless the branch still",
        "# points exactly where this plan proved its content was already in the",
        "# base ref. The `-d` verdict it supersedes is quoted above each such",
        "# line. Nothing is forced and no evidence is hidden.",
        "# EVERY precondition is re-measured HERE, when you run this, not only",
        "# when the plan was written: a worktree that has since been locked,",
        "# dirtied or made unreadable is not moved, and a branch that has since",
        "# moved or been checked out is not deleted.",
        "# Each item stands alone: one refusal is recorded and the remaining",
        "# items still run, because half a cleanup with no statement of which",
        "# half is worse than either outcome. A backup ref that does not read",
        "# back still stops ITS OWN item — never the deletion behind nothing.",
        "# The summary at the end names every item, and this script exits 1 if",
        "# any item refused.",
        "# Worktree directories are MOVED, never removed: untracked and ignored",
        "# files have no git recovery story whatsoever, and each one's own",
        "# reflog — which `git worktree prune` deletes — is swept first, so any",
        "# commit only it was holding is pinned to a ref before the move.",
        "#",
    ]
    if include_harness:
        wrapped = _wrap(HARNESS_HANDBOOK_NOTE)
        lines += [f"# NOTE: {wrapped[0]}"]
        lines += [f"#       {line}" for line in wrapped[1:]] + ["#"]
    if stale:
        lines += [
            "# ======================================================================",
            "# STALE PLAN — every command below is COMMENTED OUT.",
            "# This plan was built without --fetch, so 'merged' was judged against a",
            "# local ref that may be behind the remote. Re-run with --fetch and use",
            "# the script that run writes.",
            "# ======================================================================",
        ]
    lines += ["set -eu", f"cd {shlex.quote(str(root))}", ""]

    body: list[str] = []
    for item, why in refused:
        # Comment-only, so it survives the stale pass below without ever being
        # a command. This should be unreachable: `classify` keeps everything
        # this refuses. If it ever prints, the two halves have drifted.
        body += [
            f"# REFUSED to emit a move for {_comment(item.path)}",
            f"#   {_comment(why)}. The classifier called it retirable and the",
            "#   emitter would not write the line. REPORT THIS — the two halves",
            "#   of this tool are supposed to agree.",
            "",
        ]
    for item, why in declined:
        # The branch half of the same disagreement, and equally comment-only:
        # a `git branch -d` git is going to refuse is not written at all.
        body += [
            f"# REFUSED to emit a deletion of {_comment(item.name)}",
            f"#   {_comment(why)}",
            "#   The classifier called it proposable and the emitter would not",
            "#   write the line. REPORT THIS — the two halves are supposed to",
            "#   agree.",
            "",
        ]
    if moves or proposed:
        body += _summary_helpers()
        body += _runtime_guards()
    if moves:
        # Fatal on purpose, and outside every item: with no trash directory
        # there is nowhere for ANY move to land, so this is a precondition of
        # the run rather than a step of one item.
        body += [f"mkdir -p {shlex.quote(str(trash))}", ""]
    for item, destination in moves:
        subject = f"worktree {item.path}"
        body += [
            f"# worktree {_comment(item.path)}",
            f"#   clean, and its branch's content is already in "
            f"{_comment(base_ref)}",
        ]
        if item.harness:
            body += [f"#   {_comment(line)}" for line in _wrap(HARNESS_HANDBOOK_NOTE)]
        for note in item.notes:
            body += [f"#   {_comment(line)}" for line in _wrap(note, width=68)]
        if item.backups:
            # BEFORE the move, always. `git worktree prune` below deletes this
            # worktree's `logs/HEAD`, and these commits are reachable from
            # nothing else — so the pin has to already have happened, and the
            # read-back has to be able to stop this move.
            body.append(
                f"#   {len(item.backups)} commit(s) live only in this "
                f"worktree's reflog, which `git worktree prune` deletes:")
            body += [f"#     pinning {oid[:8]} to {_comment(ref)}"
                     for ref, oid in item.backups]
        # FIRST, before the pins and long before the `mv`: is this still the
        # worktree the plan described? See `_runtime_guards`.
        body += [
            f"if ! cleanup_worktree_ready {shlex.quote(item.path)}; then",
            _record("refused", subject,
                    "it is no longer the worktree this plan measured — it is "
                    "dirty, locked, unreadable or gone. NOT moved"),
        ]
        if item.backups:
            body += _pin_condition(item.backups, lead="elif ! { ")
            body += [
                _record("refused", subject,
                        "a reflog backup ref did not read back — NOT moved, so "
                        "nothing that reflog holds can be orphaned"),
                f"elif mv {shlex.quote(item.path)} "
                f"{shlex.quote(str(destination))}; then",
            ]
        else:
            body.append(f"elif mv {shlex.quote(item.path)} "
                        f"{shlex.quote(str(destination))}; then")
        body += [
            "    if git worktree prune; then",
            f"    {_record('done', subject)}",
            "    else",
            f"    {_record('refused', subject, 'moved, but git worktree prune failed — run it yourself')}",
            "    fi",
            "else",
            _record("refused", subject,
                    "the move itself failed — the directory is untouched and "
                    "its registration was left alone"),
            "fi",
            "",
        ]
    for item in proposed:
        ref = (item.backup_ref or
               f"{TRASH_REF_ROOT}/{run_id}/{slug(item.name)}-{item.tip[:12]}")
        subject = f"branch {item.name}"
        # `intent` is the first line of `git branch --edit-description`, and a
        # description is MULTI-LINE by design. It is single-line by the time it
        # arrives here, but that is a promise made in another module — one
        # refactor from putting a raw newline inside a `#` comment, where the
        # tail becomes a command. Every interpolation below is `shlex.quote`d
        # for the same reason: it used to sit inside hand-written single quotes
        # and depend on `_SAFE_NAME_RE` never admitting an apostrophe.
        body += [
            f"# branch {_comment(item.name)} — tip {item.tip[:8]}",
            f"#   {_comment(item.intent)}" if item.intent
            else "#   (no stated intent)",
            f"#   pinning the tip {item.tip[:8]}; the delete runs only if that "
            f"ref reads back",
        ]
        for note in item.notes:
            body += [f"#   {_comment(line)}" for line in _wrap(note, width=68)]
        if item.delete_method == DELETE_CAS:
            # `git branch -d` structurally cannot accept this branch (its
            # verdict is quoted in the comments above), and the planner's own
            # containment proof says the fetched base holds its whole content.
            # The two run-time checks `-d` would have performed are written out
            # instead of inherited: nothing has it checked out, and it still
            # points where the plan said.
            body += [
                f"if ! cleanup_branch_free {shlex.quote(item.ref)}; then",
                _record("refused", subject,
                        "a worktree checked this branch out after the plan was "
                        "written — left alone"),
            ]
            body += _pin_condition([(ref, item.tip)], lead="elif ! { ")
            body += [
                _record("refused", subject,
                        "its backup ref did not read back — NOT deleted, "
                        "because a deletion standing behind nothing is the "
                        "whole hazard"),
                f"elif git update-ref -d {shlex.quote(item.ref)} {item.tip}; then",
                _record("done", subject),
                "else",
                _record("refused", subject,
                        f"it no longer points at {item.tip[:8]} — the branch "
                        f"moved after this plan was written, so the "
                        f"compare-and-swap refused and it was left alone"),
                "fi",
                "",
            ]
        else:
            body += _pin_condition([(ref, item.tip)])
            body += [
                _record("refused", subject,
                        "its backup ref did not read back — NOT deleted, "
                        "because a deletion standing behind nothing is the "
                        "whole hazard"),
                f"elif git branch -d {shlex.quote(item.name)}; then",
                _record("done", subject),
                "else",
                _record("refused", subject,
                        "git branch -d declined it — report this; the tip is "
                        "still pinned and this tool has no stronger flag"),
                "fi",
                "",
            ]
    if moves or proposed:
        body += _summary_footer()
    if not any(line and not line.startswith("#") for line in body):
        body += ["# nothing is proposed for removal in this run.", ""]
    if stale:
        body = [line if not line or line.startswith("#") else f"# STALE: {line}"
                for line in body]
    lines += body
    lines += [
        "# Recovery: every tip above is reachable from its refs/agent-trash ref.",
        f"#   git for-each-ref {TRASH_REF_ROOT}/{run_id}",
        f"#   git log --oneline {TRASH_REF_ROOT}/{run_id}/<branch>-<sha12>",
        f"#   git branch <name> {TRASH_REF_ROOT}/{run_id}/<branch>-<sha12>",
        "# The tip sha is part of the ref name so that two branch names which",
        "# slug to the same string cannot share — and overwrite — one backup.",
    ]
    if any(item.backups for item, _ in moves):
        lines += [
            "# Commits that lived only in a retired worktree's reflog are under",
            f"#   git for-each-ref {TRASH_REF_ROOT}/{run_id}-worktrees",
            "# one ref per commit, named <worktree-dir>/<sha12>.",
        ]
    if moves:
        lines.append(f"# Moved worktrees are under {trash}/ — nothing was deleted.")
    lines.append("")
    return "\n".join(lines)


# ── plan assembly ────────────────────────────────────────────────────────────

def build_plan(*, run_id: str, root: Path, repo: status.Repository,
               branches: Sequence[BranchItem], worktrees: Sequence[WorktreeItem],
               blocking: Sequence[Blocking], fetched: bool, executed: bool,
               private_counts: dict | None, include_harness: bool = False) -> dict:
    stale = not fetched
    judgement = [item for item in branches
                 if KEEP_UNKNOWN_MERGE in item.keep_reasons
                 or KEEP_NO_BACKUP in item.keep_reasons]
    # `--include-harness-worktrees` deliberately does NOT push the exit code to
    # 1. It is the operator's judgement, already exercised at the command line;
    # a proposal it unlocks cleared every precondition an ordinary worktree
    # clears, so calling it "needs judgement" would train people to ignore a 1.
    # Nothing here exits 3: every fail-closed condition refuses BEFORE a plan
    # exists. A dropped item (its backup ref did not resolve) leaves the rest of
    # the plan readable and correct, which is exactly what exit 1 means.
    exit_code = 1 if (blocking or stale or judgement) else 0
    return {
        "base_ref": repo.base_ref,
        "blocking": [item.to_json() for item in blocking],
        "branches": [item.to_json() for item in branches],
        "executable": exit_code == 0,
        "executed_non_destructive": executed,
        "exit_code": exit_code,
        "generated_at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {"tool": TOOL, "merge_probe": repo.merge_probe},
        "include_harness_worktrees": include_harness,
        "private_overlay": private_counts,
        "remote_knowledge": {"fetched": fetched,
                             "state": "stale" if stale else "fresh"},
        "root": str(root),
        "run_id": run_id,
        "schema": SCHEMA,
        "worktrees": [item.to_json() for item in worktrees],
    }


def _bullet(text: str, out, indent: str = "          ") -> None:
    """One report bullet, WRAPPED.

    These reasons are ARGUMENTS, not labels — a superseded `git branch -d`
    verdict, quoted verbatim so the reader can weigh it, runs to several hundred
    characters — and a report whose lines never end is a report nobody reads to
    the end of.
    """
    wrapped = _wrap(text, width=76) or [""]
    print(f"{indent}· {wrapped[0]}", file=out)
    for line in wrapped[1:]:
        print(f"{indent}  {line}", file=out)


def print_report(plan: dict, branches: Sequence[BranchItem],
                 worktrees: Sequence[WorktreeItem], out) -> None:
    mode = ("non-destructive steps performed" if plan["executed_non_destructive"]
            else "dry-run")
    print(f"workspace cleanup plan  run {plan['run_id']}   ({mode}; the destructive "
          f"half is only ever a script)", file=out)
    print(f"base ref: {plan['base_ref']}  ·  merge probe: "
          f"{plan['generator']['merge_probe']}", file=out)
    if plan["remote_knowledge"]["state"] == "stale":
        print("remote knowledge: STALE — no --fetch. 'merged' was judged against a "
              "local ref that may be behind the remote, so the emitted script is "
              "commented out and nothing here is executable.", file=out)
    else:
        print("remote knowledge: FRESH (fetched origin)", file=out)
    if plan.get("include_harness_worktrees"):
        for line in _wrap(HARNESS_HANDBOOK_NOTE, width=76):
            print(line, file=out)
    print("", file=out)

    proposed = [item for item in branches if item.proposed]
    print(f"BRANCHES ({len(branches)} local · {len(proposed)} proposed)", file=out)
    width = max((len(item.name) for item in branches), default=1)
    for item in branches:
        verdict = "PROPOSE" if item.proposed else "keep"
        print(f"  {verdict:<7} {item.name:<{width}}  {item.merged:<8} "
              f"{item.state}", file=out)
        for reason in item.keep_reasons:
            _bullet(reason, out)
        for note in item.notes:
            _bullet(f"note: {note}", out)
        if item.proposed and item.backup_written:
            print(f"          · backup ref {item.backup_ref}", file=out)
        if item.proposed and item.delete_method != DELETE_BRANCH_D:
            print(f"          · deleted by: {item.delete_method}", file=out)
        if item.archive_tag:
            print(f"          · archive tag {item.archive_tag}", file=out)

    print("", file=out)
    print(f"WORKTREES ({len(worktrees)})", file=out)
    for item in worktrees:
        label = {"prune": "PRUNE", "retire": "RETIRE", "keep": "keep"}[item.action]
        print(f"  {label:<7} {item.path}", file=out)
        if item.action == "prune":
            note = ("pruned — its reflog was swept first, so this really was "
                    "metadata only" if item.pruned else
                    "its directory is gone; `git worktree prune` un-wedges the "
                    "branch, and its reflog is swept BEFORE that runs")
            print(f"          · {note}", file=out)
        if item.action in ("retire", "prune") and item.backups:
            if item.backups_written:
                written = "written and verified"
            elif item.action == "prune":
                written = "written by --execute before it prunes"
            else:
                written = "written by the script before its `mv`"
            destroys = ("`git worktree prune`" if item.action == "prune"
                        else "retiring it")
            print(f"          · {len(item.backups)} commit(s) live only in this "
                  f"worktree's reflog, which {destroys} destroys — backup "
                  f"ref(s) {written}", file=out)
            for ref, oid in item.backups:
                print(f"          ·   {oid[:8]}  {ref}", file=out)
        for reason in item.keep_reasons:
            _bullet(reason, out)
        for note in item.notes:
            _bullet(f"note: {note}", out)

    if plan["private_overlay"]:
        counts = plan["private_overlay"]
        print("", file=out)
        print(f"PRIVATE OVERLAY: {counts['branches']} local branch(es), "
              f"{counts['worktrees']} worktree(s) — counts only, and out of scope "
              f"for this planner. It never names a private branch, path, or item.",
              file=out)

    if plan["blocking"]:
        print("", file=out)
        print(f"BLOCKING ({len(plan['blocking'])})", file=out)
        for entry in plan["blocking"]:
            print(f"  {entry['code']}  {entry['subject']}", file=out)
            print(f"      {entry['message']}", file=out)


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Plan the retirement of finished branches and worktrees. Dry-run by "
            "default; --execute performs ONLY non-destructive steps. There is no "
            "--force flag, and there never will be."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="authorise the network: `git fetch --prune origin` before judging "
             "merge state. Without it every plan is stamped stale and its script "
             "is emitted commented out.")
    parser.add_argument(
        "--execute", action="store_true",
        help="perform the NON-DESTRUCTIVE steps: write and verify backup refs, "
             "and prune worktree metadata whose directory is already gone. "
             "Deleting anything remains the emitted script's job, and the "
             "owner's decision.")
    parser.add_argument(
        "--include-harness-worktrees", action="store_true",
        help="judge worktrees under .claude/worktrees like any other worktree "
             "instead of keeping them for the Claude Code harness. This waives "
             "ONE rule and no others: a clean tree, containment in the fetched "
             "base, an unlocked registration and the per-worktree reflog sweep "
             "all still decide. Nothing is executed either way — the retirement "
             "is emitted as `mv` into a trash directory for you to run.")
    parser.add_argument(
        "--archive-tag", action="store_true",
        help="with --execute, also write an annotated archive/<slug>-<sha> tag "
             "for each proposed branch (the repo's established retirement idiom)")
    parser.add_argument(
        "--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    try:
        return _plan(argv, out)
    except SystemExit:
        raise
    except BaseException as exc:  # refusing beats guessing
        print(f"REFUSED  crashed: {type(exc).__name__}: {exc}", file=out)
        return 3


def _plan(argv: Sequence[str] | None, out) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repo_root).resolve()
    run_id = make_run_id()
    blocking: list[Blocking] = []

    try:
        status.validate_toolkit_root(root)
    except status.GitError as exc:
        print(f"REFUSED  {CODE_TOOLKIT_GUARD}: {exc}", file=out)
        return 3

    operation = _in_progress_operation(root)
    if operation is not None:
        print(f"REFUSED  {CODE_OPERATION_IN_PROGRESS}: a {operation} is in progress; "
              f"finish or abort it before planning a cleanup", file=out)
        return 3

    probe_version = status.git_version(root)
    if not probe_version or probe_version < status.MERGE_TREE_MIN_VERSION:
        # Degrading here is not an option: the ancestor fallback misses
        # squash-merges, and a planner that proposes deletions on a probe it
        # knows is lossy is the one failure mode this design must not have.
        print(f"REFUSED  {CODE_MERGE_PROBE_DEGRADED}: {status.PROBE_DEGRADED_NOTE} "
              f"A cleanup plan may not rest on it — nothing is proposed.", file=out)
        return 3

    fetched = False
    if args.fetch:
        ok, detail = _fetch(root)
        if not ok:
            print(f"REFUSED  {CODE_FETCH_FAILED}: {detail}", file=out)
            return 3
        fetched = True

    base_ref = resolve_base(root, fetched)
    if base_ref is None:
        print(f"REFUSED  {CODE_BASE_REF_MISSING}: neither refs/heads/main nor "
              f"refs/remotes/origin/main resolves; there is nothing to be merged "
              f"into", file=out)
        return 3

    repo = status.inspect_repository("PUBLIC", root)
    # The dashboard prefers the LOCAL main; after a fetch the remote base is the
    # authority, so the containment verdicts are recomputed against it.
    if base_ref != repo.base_ref:
        repo = _recompute_against(repo, root, base_ref)

    include_harness = args.include_harness_worktrees
    # ONE probe for the whole run. The classifier and the emitter deliberately
    # ask the same containment question twice, and every answer is cached, so
    # asking twice costs one git call rather than two.
    containment = Containment(root, base_ref)
    try:
        branches, worktrees = classify(repo, root, run_id=run_id,
                                       ledger=ledger_risk(root, base_ref),
                                       include_harness=include_harness,
                                       containment=containment, fresh=fetched)
        apply_emitter_refusals(root, run_id, worktrees, branches,
                               containment=containment, fresh=fetched)

        executed = False
        if args.execute:
            blocking.extend(write_backup_refs(root, branches, run_id,
                                              archive_tag=args.archive_tag,
                                              worktrees=worktrees))
            prune_gone_worktrees(root, worktrees)
            executed = True

        private_counts = _private_counts(root)
        plan = build_plan(run_id=run_id, root=root, repo=repo, branches=branches,
                          worktrees=worktrees, blocking=blocking, fetched=fetched,
                          executed=executed, private_counts=private_counts,
                          include_harness=include_harness)

        print_report(plan, branches, worktrees, out)

        script = build_script(run_id=run_id, root=root, base_ref=base_ref,
                              stale=not fetched, branches=branches,
                              worktrees=worktrees, containment=containment,
                              include_harness=include_harness)
    finally:
        containment.close()
    destination = root / OUTPUT_DIR
    try:
        destination.mkdir(parents=True, exist_ok=True)
        script_path = destination / f"cleanup-{run_id}.sh"
        # Deliberately NOT executable: this file is meant to be read first and
        # then run on purpose with `sh <path>`, never double-clicked into.
        script_path.write_text(script, encoding="utf-8")
        (destination / f"cleanup-{run_id}.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("", file=out)
        print(f"script: {script_path}   (read it; run it with `sh <path>`)", file=out)
        print(f"plan:   {destination / f'cleanup-{run_id}.json'}", file=out)
    except OSError as error:
        print(f"REFUSED  {CODE_OUTPUT_UNWRITABLE}: {error}", file=out)
        return 3

    return int(plan["exit_code"])


def _recompute_against(repo: status.Repository, root: Path,
                       base_ref: str) -> status.Repository:
    """Re-judge containment against ``base_ref`` (the fetched remote base)."""
    probe = status.open_merge_probe(root)
    try:
        base_tree = status._base_tree(root, base_ref)
        rebuilt = []
        for branch in repo.branches:
            merged = status._merged_state(root, branch.ref.full_name, base_ref,
                                          probe, base_tree)
            state = status.lifecycle_state(
                merged=merged, upstream_missing=branch.upstream_missing,
                wedged=branch.wedged_at is not None, locked=branch.locked,
                age_seconds=branch.age_seconds)
            rebuilt.append(_replace_branch(branch, merged=merged, state=state))
    finally:
        probe.close()
    repo.branches = rebuilt
    repo.base_ref = base_ref
    return repo


def _replace_branch(branch: status.Branch, **changes) -> status.Branch:
    return dataclasses.replace(branch, **changes)


def _private_counts(root: Path) -> dict | None:
    """Counts ONLY. In the private mirror a NAME is itself content.

    The overlay is a separate repository with its own branches, and this
    planner does not touch it. What it may say about it is a number, never a
    branch name, a path, or a private skill folder — those are identity tokens,
    and this report is written to be pasted.
    """
    overlay = root / "private"
    if status._git_toplevel(overlay) != overlay.resolve():
        return None
    heads = _git(overlay, "for-each-ref", "--format=%(refname)", "refs/heads")
    worktrees = _git(overlay, "worktree", "list", "--porcelain")
    return {
        "branches": len([line for line in heads.stdout.splitlines() if line]),
        "worktrees": len([line for line in worktrees.stdout.splitlines()
                          if line.startswith("worktree ")]),
        "policy": "counts only — a private branch name is itself content",
    }


if __name__ == "__main__":
    raise SystemExit(main())
