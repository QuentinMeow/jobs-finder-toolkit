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
4. ``git rev-list <branch> --not --remotes`` is empty: every commit exists on a
   remote. A squash-merged branch fails this and is kept, deliberately;
5. no row of ``automation/publish/review_ledger.yaml`` names it — deleting such
   a branch degrades that row from NOT_ANCESTOR to UNKNOWN OBJECT in a fresh
   clone;
6. a backup ref resolves. The reflog does NOT protect worktree-only commits
   (measured: 0 hits after ``worktree remove --force`` + ``branch -D``);
   ``refs/agent-trash/<ts>/<branch>`` makes the tip reachable, so it survives
   even ``git gc --prune=now``.

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
# so this one reports them and proposes nothing.
HARNESS_WORKTREE_MARKER = ".claude/worktrees"

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
KEEP_LEDGER = "a review-ledger row names it"
KEEP_UNSAFE_NAME = "the name would need shell quoting this tool will not guess"
KEEP_NO_BACKUP = "the backup ref did not resolve"
KEEP_HARNESS = "harness-owned worktree — Claude Code sweeps these itself"
KEEP_DIRTY = "changed path(s) here — untracked files have no git recovery story"
KEEP_LOCKED = "the worktree is locked — a deliberate finalizer"
KEEP_LOCKED_GONE = (
    "locked AND its directory is gone — `git worktree prune` cannot clear it "
    "while the lock stands, so it wedges its branch indefinitely. Clearing it "
    "needs a doubled `-f -f` this tool will never pass: run "
    "`git worktree unlock <path>` yourself, then re-run this planner")

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class Blocking:
    code: str
    subject: str
    message: str

    def to_json(self) -> dict:
        return {"code": self.code, "message": self.message, "subject": self.subject}


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

    @property
    def proposed(self) -> bool:
        return not self.keep_reasons

    def to_json(self) -> dict:
        return {
            "age_seconds": self.age_seconds,
            "archive_tag": self.archive_tag,
            "backup_ref": self.backup_ref,
            "backup_written": self.backup_written,
            "intent": self.intent,
            "keep_reasons": list(self.keep_reasons),
            "merged": self.merged,
            "name": self.name,
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

    def to_json(self) -> dict:
        return {
            "action": self.action,
            "branch": self.branch,
            "dirty_paths": self.dirty_paths,
            "gone": self.gone,
            "keep_reasons": list(self.keep_reasons),
            "locked": self.locked,
            "path": self.path,
            "pruned": self.pruned,
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


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return status._git(repo, *args, check=check)


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


def ledger_names(repo: Path) -> str:
    """The review ledger's raw text, or "" — matched as a substring, on purpose.

    A row names a branch inside free prose (``finding:``), so parsing YAML
    would not narrow it. Substring matching over-keeps and never under-keeps,
    which is the only safe direction here.
    """
    path = repo / REVIEW_LEDGER
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def unpushed_commits(repo: Path, ref: str) -> int:
    result = _git(repo, "rev-list", "--count", ref, "--not", "--remotes")
    if result.returncode:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


# ── classification ───────────────────────────────────────────────────────────

def classify(repo: status.Repository, root: Path, *, run_id: str,
             ledger: str) -> tuple[list[BranchItem], list[WorktreeItem]]:
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
        if branch.merged == "unmerged":
            item.keep_reasons.append(KEEP_UNMERGED)
        elif branch.merged not in ("merged", "main"):
            item.keep_reasons.append(KEEP_UNKNOWN_MERGE)
        if not _SAFE_NAME_RE.match(branch.name):
            item.keep_reasons.append(KEEP_UNSAFE_NAME)
        item.unpushed = unpushed_commits(root, branch.ref.full_name)
        if item.unpushed != 0:
            count = "an unknown number of" if item.unpushed < 0 else str(item.unpushed)
            item.keep_reasons.append(f"{count} {KEEP_UNPUSHED}")
        if branch.name in ledger:
            item.keep_reasons.append(KEEP_LEDGER)
        if item.proposed:
            item.backup_ref = f"{TRASH_REF_ROOT}/{run_id}/{slug(branch.name)}"
        branches.append(item)

    worktrees: list[WorktreeItem] = []
    branch_state = {b.ref.full_name: b for b in repo.branches}
    for worktree in repo.worktrees:
        path = str(worktree.path)
        item = WorktreeItem(
            path=path, branch=worktree.branch_ref, action="keep",
            gone=worktree.gone, locked=worktree.locked is not None,
            dirty_paths=len(worktree.changes),
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
                # The one deletion automation may perform without ceremony: the
                # directory is already gone, so pruning its metadata destroys
                # nothing — and it UN-WEDGES the branch, which git otherwise
                # leaves unusable for three months (gc.worktreePruneExpire).
                item.action = "prune"
            worktrees.append(item)
            continue
        if worktree.path.resolve() == root.resolve():
            item.keep_reasons.append("this is the main worktree")
        if HARNESS_WORKTREE_MARKER in path.replace("\\", "/"):
            item.keep_reasons.append(KEEP_HARNESS)
        if item.locked:
            item.keep_reasons.append(KEEP_LOCKED)
        if worktree.changes:
            # Untracked and ignored files have NO git recovery story — measured:
            # zero blobs recoverable after `worktree remove --force`.
            item.keep_reasons.append(
                f"{len(worktree.changes)} {KEEP_DIRTY}")
        held = branch_state.get(worktree.branch_ref) if worktree.branch_ref else None
        if held is not None and held.merged not in ("merged", "main"):
            item.keep_reasons.append(KEEP_UNMERGED)
        if held is None and worktree.detached:
            item.keep_reasons.append("detached HEAD — no branch to judge it by")
        if not item.keep_reasons:
            item.action = "retire"
        worktrees.append(item)
    return branches, worktrees


# ── the non-destructive half of --execute ────────────────────────────────────

def write_backup_refs(root: Path, items: Sequence[BranchItem], run_id: str,
                      *, archive_tag: bool) -> list[Blocking]:
    """Make every proposed tip reachable BEFORE anything could remove it.

    Order is not negotiable: ref first, verify second, and an item that fails
    verification is dropped from the plan rather than carried into a script.
    """
    blocking: list[Blocking] = []
    for item in items:
        if not item.proposed or item.backup_ref is None:
            continue
        ref = item.backup_ref
        written = _git(root, "update-ref", ref, item.tip, "-m",
                       f"pre-delete backup ({TOOL} run {run_id})")
        resolved = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if written.returncode or resolved.stdout.strip() != item.tip:
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
    return blocking


def prune_gone_worktrees(root: Path, items: Sequence[WorktreeItem]) -> bool:
    """``git worktree prune`` — metadata only, and only when something is gone.

    The result is READ BACK rather than assumed: prune silently declines a
    locked registration, and a tool that reported "pruned" for one would be
    telling the owner their branch is usable when it is still wedged.
    """
    targets = [item for item in items if item.action == "prune"]
    if not targets:
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

def build_script(*, run_id: str, root: Path, base_ref: str | None, stale: bool,
                 branches: Sequence[BranchItem],
                 worktrees: Sequence[WorktreeItem]) -> str:
    trash = OUTPUT_DIR / f"trash-{run_id}"
    proposed = [item for item in branches if item.proposed]
    retiring = [item for item in worktrees if item.action == "retire"]
    lines = [
        "#!/bin/sh",
        f"# workspace cleanup — run {run_id}",
        f"# generated by {TOOL} at {_now().strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "#",
        "# THIS SCRIPT IS THE DESTRUCTIVE HALF. The planner ran none of it.",
        "# Read it before running it; then run it with:  sh " +
        shlex.quote(str(OUTPUT_DIR / f'cleanup-{run_id}.sh')),
        "#",
        f"# base ref used for the containment test: {base_ref or '(none)'}",
        "# Every branch below writes its backup ref FIRST and verifies it, so a",
        "# tip is reachable before anything can remove it. `git branch -d` is",
        "# used deliberately: it refuses an unmerged branch. IF IT REFUSES, THAT",
        "# IS A FINDING — report it. Do not reach for -D; there is no --force in",
        "# this tooling at all.",
        "# Worktree directories are MOVED, never removed: untracked and ignored",
        "# files have no git recovery story whatsoever.",
        "#",
    ]
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
    if retiring:
        body += [f"mkdir -p {shlex.quote(str(trash))}", ""]
    for item in retiring:
        name = Path(item.path).name
        body += [
            f"# worktree {item.path}",
            f"#   clean, and its branch's content is already in {base_ref}",
            f"mv {shlex.quote(item.path)} {shlex.quote(str(trash / name))}",
            "git worktree prune",
            "",
        ]
    for item in proposed:
        ref = (item.backup_ref or
               f"{TRASH_REF_ROOT}/{run_id}/{slug(item.name)}")
        quoted_ref = shlex.quote(ref)
        body += [
            f"# branch {item.name} — tip {item.tip[:8]}",
            f"#   {item.intent}" if item.intent else "#   (no stated intent)",
            f"git update-ref {quoted_ref} {item.tip} -m 'pre-delete backup'",
            f"git rev-parse --verify --quiet {shlex.quote(ref + '^{commit}')} "
            ">/dev/null || {",
            f"    echo 'backup ref missing — refusing to delete "
            f"{item.name}' >&2; exit 1; }}",
            f"git branch -d {shlex.quote(item.name)}",
            "",
        ]
    if not body:
        body = ["# nothing is proposed for removal in this run.", ""]
    if stale:
        body = [line if not line or line.startswith("#") else f"# STALE: {line}"
                for line in body]
    lines += body
    lines += [
        "# Recovery: every tip above is reachable from its refs/agent-trash ref.",
        f"#   git log --oneline {TRASH_REF_ROOT}/{run_id}/<branch>",
        f"#   git branch <name> {TRASH_REF_ROOT}/{run_id}/<branch>",
        f"# Moved worktrees are under {trash}/ — nothing was deleted.",
        "",
    ]
    return "\n".join(lines)


# ── plan assembly ────────────────────────────────────────────────────────────

def build_plan(*, run_id: str, root: Path, repo: status.Repository,
               branches: Sequence[BranchItem], worktrees: Sequence[WorktreeItem],
               blocking: Sequence[Blocking], fetched: bool, executed: bool,
               private_counts: dict | None) -> dict:
    stale = not fetched
    judgement = [item for item in branches
                 if KEEP_UNKNOWN_MERGE in item.keep_reasons
                 or KEEP_NO_BACKUP in item.keep_reasons]
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
        "private_overlay": private_counts,
        "remote_knowledge": {"fetched": fetched,
                             "state": "stale" if stale else "fresh"},
        "root": str(root),
        "run_id": run_id,
        "schema": SCHEMA,
        "worktrees": [item.to_json() for item in worktrees],
    }


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
    print("", file=out)

    proposed = [item for item in branches if item.proposed]
    print(f"BRANCHES ({len(branches)} local · {len(proposed)} proposed)", file=out)
    width = max((len(item.name) for item in branches), default=1)
    for item in branches:
        verdict = "PROPOSE" if item.proposed else "keep"
        print(f"  {verdict:<7} {item.name:<{width}}  {item.merged:<8} "
              f"{item.state}", file=out)
        for reason in item.keep_reasons:
            print(f"          · {reason}", file=out)
        if item.proposed and item.backup_written:
            print(f"          · backup ref {item.backup_ref}", file=out)
        if item.archive_tag:
            print(f"          · archive tag {item.archive_tag}", file=out)

    print("", file=out)
    print(f"WORKTREES ({len(worktrees)})", file=out)
    for item in worktrees:
        label = {"prune": "PRUNE", "retire": "RETIRE", "keep": "keep"}[item.action]
        print(f"  {label:<7} {item.path}", file=out)
        if item.action == "prune":
            note = "pruned (metadata only)" if item.pruned else (
                "its directory is gone; `git worktree prune` un-wedges the branch")
            print(f"          · {note}", file=out)
        for reason in item.keep_reasons:
            print(f"          · {reason}", file=out)

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

    branches, worktrees = classify(repo, root, run_id=run_id,
                                   ledger=ledger_names(root))

    executed = False
    if args.execute:
        blocking.extend(write_backup_refs(root, branches, run_id,
                                          archive_tag=args.archive_tag))
        prune_gone_worktrees(root, worktrees)
        executed = True

    private_counts = _private_counts(root)
    plan = build_plan(run_id=run_id, root=root, repo=repo, branches=branches,
                      worktrees=worktrees, blocking=blocking, fetched=fetched,
                      executed=executed, private_counts=private_counts)

    print_report(plan, branches, worktrees, out)

    script = build_script(run_id=run_id, root=root, base_ref=base_ref,
                          stale=not fetched, branches=branches, worktrees=worktrees)
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
