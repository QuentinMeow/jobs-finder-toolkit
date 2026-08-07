#!/usr/bin/env python3
"""Read-only two-repository post-merge cutover planner.

NOT ``automation/reconcile/reconcile.py``: that is the process-layer schema gate
wired into pre-commit and CI.  This inspects git state and writes nothing.  An
agent told to "run the reconciler" must never land here, which is why nothing in
this folder is called reconcile.

WHAT IT ANSWERS.  The prerequisite PRs merged while you were holding local work
against the OLD layout.  Which of your dirty paths did the merged branch move,
which did it also edit, which are git-ignored and need copying, and which does
nothing in Git explain?  All of that is one command away and used to be
reconstructed by reasoning.

WHAT IT DOES NOT DO.  It never mutates.  ``git hash-object`` is called without
``-w``; every other invocation is a query; ``--fetch`` writes remote-tracking
refs and only when you ask.  It proposes mechanical steps, and THE AGENT PERFORMS
THEM, guided by the plan — no executor ships in this repository yet (filed as a
follow-up; see ``docs/handbook/post-merge-cutover.md``).

Exit codes:
    0  every proposed step is mechanical, ``blocking`` is empty, remote fresh
    1  the plan is safe to read but needs agent judgement, or the remote is stale
    2  argparse usage error
    3  REFUSED — a fail-closed condition; the state is not safe to call a plan

The plan's human table and JSON name real overlay paths and application slugs.
The JSON defaults under the git-ignored ``local/``, and a ``--json-out`` inside
the public repo but outside ``local/`` is refused.

Tests: ``.venv/bin/python -m unittest discover automation/cutover/tests``
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import classify_dirty as CD  # noqa: E402  (import after sys.path bootstrap)

REPO_ROOT = CD.REPO_ROOT

_SHARED = REPO_ROOT / "automation" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
import config  # noqa: E402  (import after sys.path bootstrap, by design)


SCHEMA = "cutover-plan/v1"
TOOL = "automation/cutover/plan_cutover.py"
PUBLICATION_SKILL = "skills/github-workflow/SKILL.md"
PUBLICATION_RUNBOOK = "skills/github-workflow/scripts/merge_stack.py"
VALIDATION_PROFILE = "cutover"

# Pinned by a test and repeated verbatim in docs/handbook/post-merge-cutover.md.
# Two things named "reconcile" in one repo is a guaranteed misroute, so the
# disambiguation travels with the tool rather than living only in a doc.
DISAMBIGUATION_LINE = (
    "NOTE: this is not automation/reconcile/reconcile.py (the process-layer "
    "schema gate). This inspects git state and writes nothing."
)
TABLE_PRIVACY_WARNING = (
    "this table names private/ paths — never paste it into a public PR"
)

REPO_NAMES = ("private", "public")

# Rollup of git-ignored paths with no merged-layout counterpart (see
# RepoState.rollup_split). Depth 2 turns store/email/raw/<hash>/... into
# "store/email"; the limit bounds the JSON, and what it omits is counted.
ROLLUP_ZONE_DEPTH = 2
ROLLUP_ZONE_LIMIT = 60

# ── fail-closed condition codes (every one exits 3) ──────────────────────────
CODE_CONFIG_UNRESOLVED = "config-unresolved"
CODE_CONFIG_EXAMPLE = "config-is-example-fallback"
CODE_OVERLAY_NOT_MOUNTED = "overlay-not-mounted"
CODE_OVERLAY_NOT_A_REPO = "overlay-not-a-repo"
CODE_OVERLAY_IS_GITLINK = "overlay-is-gitlink"
CODE_OPERATION_IN_PROGRESS = "operation-in-progress"
CODE_DETACHED_HEAD = "detached-head"
CODE_BASE_REF_MISSING = "base-ref-missing"
CODE_REMOTE_MISSING = "remote-missing"
CODE_FETCH_FAILED = "fetch-failed"
CODE_WORKTREE_OWNED_STATE = "worktree-owned-state"
CODE_UNKNOWN_DIRTY = CD.CODE_UNKNOWN_DIRTY
CODE_UNSAFE_PATH_NAME = CD.CODE_UNSAFE_PATH_NAME
CODE_SUBMODULE_DIRTY = CD.CODE_SUBMODULE_DIRTY
CODE_SYMLINK_ESCAPES = CD.CODE_SYMLINK_ESCAPES
CODE_IGNORED_CONFLICT = CD.CODE_IGNORED_CONFLICT
CODE_PREREQ_UNREACHABLE = "prereq-unreachable"
CODE_JSON_OUT_TRACKED = "json-out-tracked-destination"

BLOCKING_CODES = (
    CODE_CONFIG_UNRESOLVED,
    CODE_CONFIG_EXAMPLE,
    CODE_OVERLAY_NOT_MOUNTED,
    CODE_OVERLAY_NOT_A_REPO,
    CODE_OVERLAY_IS_GITLINK,
    CODE_OPERATION_IN_PROGRESS,
    CODE_DETACHED_HEAD,
    CODE_BASE_REF_MISSING,
    CODE_REMOTE_MISSING,
    CODE_FETCH_FAILED,
    CODE_WORKTREE_OWNED_STATE,
    CODE_UNKNOWN_DIRTY,
    CODE_UNSAFE_PATH_NAME,
    CODE_SUBMODULE_DIRTY,
    CODE_SYMLINK_ESCAPES,
    CODE_IGNORED_CONFLICT,
    CODE_PREREQ_UNREACHABLE,
    CODE_JSON_OUT_TRACKED,
)

# ── step domains ─────────────────────────────────────────────────────────────
KIND_MECHANICAL = "mechanical"
KIND_AGENT = "agent"
KIND_HANDOFF = "handoff"
STEP_KINDS = (KIND_MECHANICAL, KIND_AGENT, KIND_HANDOFF)

OP_CHECKPOINT = "checkpoint"
OP_REPLAY = "replay"
OP_PATH_REWRITE = "path-rewrite"
OP_COPY_IGNORED = "copy-ignored"
OP_VALIDATE = "validate"
OP_RESOLVE = "resolve"
OP_PUBLISH = "publish"
STEP_OPS = (OP_CHECKPOINT, OP_REPLAY, OP_PATH_REWRITE, OP_COPY_IGNORED,
            OP_VALIDATE, OP_RESOLVE, OP_PUBLISH)

REMOTE_STATES = ("fresh", "stale")

_IN_PROGRESS_MARKERS = (
    ("rebase-merge", "rebase-merge"),
    ("rebase-apply", "rebase-apply"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
)


@dataclass(frozen=True)
class Blocking:
    code: str
    repo: str | None
    subject: str
    message: str
    owner_action_required: bool = True

    def to_json(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "owner_action_required": self.owner_action_required,
            "repo": self.repo,
            "subject": self.subject,
        }


@dataclass
class RepoState:
    name: str
    root: Path
    git: CD.ReadOnlyGit
    branch: str | None = None
    head: str | None = None
    detached: bool = False
    upstream: str | None = None
    base_ref: str = "origin/main"
    base: str | None = None
    merge_base: str | None = None
    ahead: int = 0
    behind: int = 0
    in_progress_op: str | None = None
    remote: dict | None = None
    worktrees: list[dict] = field(default_factory=list)
    dirty: list[CD.DirtyPath] = field(default_factory=list)
    renames: tuple[CD.Rename, ...] = ()
    similarity_renames: tuple[CD.Rename, ...] = ()
    prefix_pairs: tuple[tuple[str, str], ...] = ()
    fetched: bool = False
    fetch_age_seconds: int | None = None
    inventoried_dirty: bool = False

    def rollup_split(self, full: bool = False) -> tuple[list, dict]:
        """Split dirty paths into the ones an agent must read, and a count.

        The JSON is this tool's whole handoff — "later steps do not rediscover
        the state". Emitting one object per ignored path defeats that: measured
        against the real repositories it produced a **72 MB** plan (110,955
        private + 9,727 public paths), which no agent can read.

        Almost all of that mass is git-ignored scratch with NO counterpart in
        the merged layout — rebuildable store projections and tooling caches.
        Those are reported as per-directory counts. Everything actionable keeps
        its full entry: anything blocking, anything not merely ``ignored``, and
        — critically — every ignored path that DOES have a layout counterpart,
        because that is the non-overwriting copy case this tool exists to
        catch. Nothing is dropped: rolled-up paths are still counted, their
        directories still named, and ``--full-json`` restores every entry.
        """
        if full:
            return [d.to_json() for d in self.dirty], {}
        keep, folded = [], {}
        for entry in self.dirty:
            rollable = (entry.verdict == CD.VERDICT_IGNORED
                        and entry.merged_path is None
                        and not entry.blocking)
            if rollable:
                zone = "/".join(PurePosixPath(entry.path).parts[:ROLLUP_ZONE_DEPTH])
                folded[zone] = folded.get(zone, 0) + 1
            else:
                keep.append(entry.to_json())
        if not folded:
            return keep, {}
        # Grouped by ZONE, not by parent directory: one key per parent still
        # meant 71,689 keys for the real overlay. Ranked by count so the
        # largest zones survive the cap, and the remainder is COUNTED rather
        # than silently dropped — a cap that hides its own truncation reads as
        # "that was everything".
        ranked = sorted(folded.items(), key=lambda kv: (-kv[1], kv[0]))
        shown, hidden = ranked[:ROLLUP_ZONE_LIMIT], ranked[ROLLUP_ZONE_LIMIT:]
        rollup = {
            "reason": "git-ignored, no counterpart in the merged layout, not blocking",
            "paths": sum(folded.values()),
            "zone_depth": ROLLUP_ZONE_DEPTH,
            "zones": dict(shown),
            "zones_omitted": len(hidden),
            "paths_in_omitted_zones": sum(count for _, count in hidden),
            "note": "re-run with --full-json to emit every path individually",
        }
        return keep, rollup

    def to_json(self, full_json: bool = False) -> dict:
        dirty, rollup = self.rollup_split(full_json)
        return {
            "ahead": self.ahead,
            "base": self.base,
            "base_ref": self.base_ref,
            "behind": self.behind,
            "branch": self.branch,
            "detached": self.detached,
            "dirty": dirty,
            "dirty_total": len(self.dirty),
            "dirty_rolled_up": rollup,
            "head": self.head,
            "in_progress_op": self.in_progress_op,
            "merge_base": self.merge_base,
            "remote": self.remote,
            "root": str(self.root),
            "upstream": self.upstream,
            "worktrees": self.worktrees,
        }


# ── helpers ──────────────────────────────────────────────────────────────────
def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def make_run_id(moment: datetime.datetime | None = None) -> str:
    return (moment or _utc_now()).strftime("%Y%m%dT%H%M%SZ")


def _parse_worktree_list(text: str) -> list[dict]:
    """Parse ``git worktree list --porcelain`` into one dict per worktree."""
    records: list[dict] = []
    current: dict = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            if current:
                records.append(current)
            current = {"path": value, "branch": None, "detached": False,
                       "locked": False, "prunable": False, "head": None}
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value
        elif key == "detached":
            current["detached"] = True
        elif key == "locked":
            current["locked"] = True
        elif key == "prunable":
            current["prunable"] = True
    if current:
        records.append(current)
    return records


def _locked_worktree_paths(git: CD.ReadOnlyGit) -> set[str]:
    """Resolved paths of every LOCKED registered worktree.

    ``git worktree list --porcelain`` only grew a ``locked`` annotation in Git
    2.36, and a planner that silently stops noticing a lock on an older Git is a
    fail-OPEN planner.  The admin directory carries the same fact on every
    version: ``<common git dir>/worktrees/<name>/locked`` exists, and the sibling
    ``gitdir`` file names the worktree it belongs to.  Reading two files is not a
    mutation.
    """
    common = git.run("rev-parse", "--git-common-dir", check=False)
    if common.returncode != 0:
        return set()
    base = Path(common.stdout.decode("utf-8", "replace").strip())
    if not base.is_absolute():
        base = git.root / base
    registry = base / "worktrees"
    if not registry.is_dir():
        return set()
    locked: set[str] = set()
    for entry in sorted(registry.iterdir()):
        if not (entry / "locked").exists():
            continue
        pointer = entry / "gitdir"
        if not pointer.is_file():
            continue
        try:
            target = Path(pointer.read_text(encoding="utf-8").strip()).parent
            locked.add(str(target.resolve()))
        except OSError:  # pragma: no cover - unreadable admin file
            continue
    return locked


def _worktree_is_dirty(path: Path) -> bool | None:
    """True/False for a live worktree, None when it cannot be inspected."""
    if not path.is_dir():
        return None
    probe = CD.ReadOnlyGit(path)
    completed = probe.run("status", "--porcelain=v2", "-z",
                          "--untracked-files=normal", check=False)
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip(b"\0"))


def _in_progress_operation(git: CD.ReadOnlyGit) -> str | None:
    completed = git.run("rev-parse", "--git-dir", check=False)
    if completed.returncode != 0:
        return None
    raw = completed.stdout.decode("utf-8", "replace").strip()
    git_dir = Path(raw)
    if not git_dir.is_absolute():
        git_dir = git.root / git_dir
    for marker, name in _IN_PROGRESS_MARKERS:
        if (git_dir / marker).exists():
            return name
    return None


def _resolve_remote_name(git: CD.ReadOnlyGit, base_ref: str,
                         branch: str | None) -> str | None:
    """The remote the base ref belongs to, or None when there is not one."""
    completed = git.run("remote", check=False)
    if completed.returncode != 0:
        return None
    remotes = [r for r in completed.stdout.decode("utf-8", "replace").split() if r]
    if not remotes:
        return None
    if "/" in base_ref:
        head = base_ref.split("/", 1)[0]
        if head in remotes:
            return head
    if branch:
        upstream = git.run("rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}",
                           check=False)
        if upstream.returncode == 0:
            name = upstream.stdout.decode("utf-8", "replace").strip()
            head = name.split("/", 1)[0] if "/" in name else ""
            if head in remotes:
                return head
    return None


def _fetch(git: CD.ReadOnlyGit, remote: str) -> tuple[bool, str]:
    """``git fetch --prune <remote>`` — the ONLY writing call, refs only."""
    completed = git.run("fetch", "--prune", remote, check=False)
    if completed.returncode == 0:
        return True, ""
    detail = completed.stderr.decode("utf-8", "replace").strip().replace("\n", " ")
    return False, f"git fetch --prune {remote} exited {completed.returncode}: {detail}"


# ── repository inventory ─────────────────────────────────────────────────────
def inventory_repo(state: RepoState, *, fetch: bool) -> list[Blocking]:
    """Collect every read-only fact about one repository.

    A hard condition records a ``Blocking`` and skips the work that depends on
    it; everything cheap and already known still lands in the plan, so a refused
    plan is still a complete description of the state that was refused.
    """
    blocking: list[Blocking] = []
    git = state.git

    head = git.run("rev-parse", "HEAD", check=False)
    if head.returncode != 0:
        blocking.append(Blocking(
            CODE_BASE_REF_MISSING, state.name, "HEAD",
            "HEAD does not resolve to a commit (an empty repository has no state "
            "to cut over)"))
        return blocking
    state.head = head.stdout.decode("ascii", "replace").strip()

    abbrev = git.run("rev-parse", "--abbrev-ref", "HEAD", check=False)
    name = abbrev.stdout.decode("utf-8", "replace").strip()
    state.detached = name == "HEAD"
    state.branch = None if state.detached else name

    upstream = git.run("rev-parse", "--abbrev-ref", "@{upstream}", check=False)
    if upstream.returncode == 0:
        state.upstream = upstream.stdout.decode("utf-8", "replace").strip() or None

    # Worktree inventory is collected even for a refused repo: "another worktree
    # owns this state" is exactly the fact a human needs to see.
    state.worktrees, worktree_blocking = _inventory_worktrees(state)
    blocking.extend(worktree_blocking)

    state.in_progress_op = _in_progress_operation(git)
    if state.in_progress_op is not None:
        blocking.append(Blocking(
            CODE_OPERATION_IN_PROGRESS, state.name, state.in_progress_op,
            f"a {state.in_progress_op} is in progress; finish or abort it before "
            f"planning a cutover"))
        return blocking

    if state.detached:
        blocking.append(Blocking(
            CODE_DETACHED_HEAD, state.name, state.head,
            "HEAD is detached; there is no branch to replay onto"))
        return blocking

    remote = _resolve_remote_name(git, state.base_ref, state.branch)
    if remote is None:
        blocking.append(Blocking(
            CODE_REMOTE_MISSING, state.name, state.base_ref,
            f"no remote owns {state.base_ref}; remote knowledge cannot be refreshed "
            f"and must never be guessed"))
    else:
        url = git.run("remote", "get-url", remote, check=False)
        url_text = url.stdout.decode("utf-8", "replace").strip()
        state.remote = {"name": remote, "url_digest": _digest(url_text)}
        if fetch:
            started = time.monotonic()
            ok, detail = _fetch(git, remote)
            if ok:
                state.fetched = True
                state.fetch_age_seconds = int(time.monotonic() - started)
            else:
                # NEVER downgraded to "stale": a failed fetch is an unknown
                # remote, and the whole premise of this workflow is that the
                # prerequisites just merged.
                blocking.append(Blocking(
                    CODE_FETCH_FAILED, state.name, remote, detail))

    base = git.run("rev-parse", "--verify", "--quiet", f"{state.base_ref}^{{commit}}",
                   check=False)
    if base.returncode != 0:
        blocking.append(Blocking(
            CODE_BASE_REF_MISSING, state.name, state.base_ref,
            f"{state.base_ref} does not resolve to exactly one commit in this "
            f"repository"))
        return blocking
    state.base = base.stdout.decode("ascii", "replace").strip()

    merge_base = git.run("merge-base", state.base, "HEAD", check=False)
    if merge_base.returncode != 0:
        blocking.append(Blocking(
            CODE_BASE_REF_MISSING, state.name, state.base_ref,
            f"HEAD and {state.base_ref} have no merge base (unrelated histories)"))
        return blocking
    state.merge_base = merge_base.stdout.decode("ascii", "replace").strip()

    counts = git.run("rev-list", "--left-right", "--count",
                     f"{state.base}...HEAD", check=False)
    if counts.returncode == 0:
        parts = counts.stdout.decode("ascii", "replace").split()
        if len(parts) == 2:
            state.behind, state.ahead = int(parts[0]), int(parts[1])

    # Rename evidence.  -M100% is a PROOF (identical blob ids); the second,
    # looser pass is recorded for the human table only and never classifies.
    exact = git.run("diff", "--name-status", "-z", "-M100%", "--diff-filter=R",
                    state.merge_base, state.base, "--", check=False)
    loose = git.run("diff", "--name-status", "-z", "-M", "--diff-filter=R",
                    state.merge_base, state.base, "--", check=False)
    try:
        state.renames = CD.renames_from_diff(exact.stdout) if exact.returncode == 0 else ()
        all_renames = CD.renames_from_diff(loose.stdout) if loose.returncode == 0 else ()
    except CD.ClassificationError as error:
        blocking.append(Blocking(
            CODE_UNSAFE_PATH_NAME, state.name, "<git diff>", str(error)))
        return blocking
    state.similarity_renames = tuple(r for r in all_renames if not r.exact)
    rename_map = CD.exact_rename_map(state.renames)
    state.prefix_pairs = CD.derive_prefix_pairs(rename_map)

    # ``--ignored=traditional`` WITH ``--untracked-files=all`` is what lists the
    # individual FILES inside an ignored directory.  The design named
    # ``--ignored=matching``; that mode reports the ignored DIRECTORY instead
    # (``companies/<k>/research/`` rather than the dossier inside it), which is
    # precisely the file a cutover has to copy — so it cannot be the mode used.
    status = git.run("status", "--porcelain=v2", "--branch",
                     "--untracked-files=all", "--ignored=traditional", "-z",
                     check=False)
    if status.returncode != 0:
        detail = status.stderr.decode("utf-8", "replace").strip()
        blocking.append(Blocking(
            CODE_UNSAFE_PATH_NAME, state.name, "<git status>",
            f"git status exited {status.returncode}: {detail}"))
        return blocking
    try:
        _, entries = CD.parse_status_v2(status.stdout)
        state.dirty = CD.classify_entries(
            entries, git=git, base=state.base, merge_base=state.merge_base,
            renames=rename_map, prefix_pairs=state.prefix_pairs,
            similarity={r.old: r for r in state.similarity_renames})
    except (CD.ClassificationError, CD.GitError) as error:
        blocking.append(Blocking(
            CODE_UNSAFE_PATH_NAME, state.name, "<dirty path>", str(error)))
        return blocking
    state.inventoried_dirty = True

    for path in state.dirty:
        for code, message in path.blocking:
            blocking.append(Blocking(code, state.name, path.path, message))
    return blocking


def _inventory_worktrees(state: RepoState) -> tuple[list[dict], list[Blocking]]:
    """List every registered worktree; refuse when another one owns live state."""
    blocking: list[Blocking] = []
    listed = state.git.run("worktree", "list", "--porcelain", check=False)
    if listed.returncode != 0:
        return [], blocking
    records = _parse_worktree_list(listed.stdout.decode("utf-8", "replace"))
    locked_paths = _locked_worktree_paths(state.git)
    root = state.root.resolve()
    out: list[dict] = []
    for record in records:
        path = Path(record["path"])
        try:
            resolved = path.resolve()
        except OSError:  # pragma: no cover - unreadable path
            resolved = path
        is_current = resolved == root
        branch = record["branch"]
        short = branch.rsplit("/", 1)[-1] if branch else None
        dirty = None if is_current else _worktree_is_dirty(path)
        locked = bool(record["locked"]) or str(resolved) in locked_paths
        entry = {
            "branch": short,
            "detached": bool(record["detached"]),
            "dirty": bool(dirty) if dirty is not None else None,
            "is_current": is_current,
            "locked": locked,
            "path": str(path),
            "prunable": bool(record["prunable"]),
        }
        out.append(entry)
        if is_current or record["prunable"]:
            # A prunable worktree's directory is gone; it holds no live state.
            continue
        if state.branch is not None and short == state.branch:
            blocking.append(Blocking(
                CODE_WORKTREE_OWNED_STATE, state.name, str(path),
                f"another registered worktree has {state.branch} checked out"))
        if locked:
            blocking.append(Blocking(
                CODE_WORKTREE_OWNED_STATE, state.name, str(path),
                "another registered worktree is locked"))
        if dirty:
            blocking.append(Blocking(
                CODE_WORKTREE_OWNED_STATE, state.name, str(path),
                "another registered worktree has uncommitted changes"))
    out.sort(key=lambda w: w["path"])
    return out, blocking


# ── configuration + destination gates ────────────────────────────────────────
def config_blockers(scope: Sequence[str]) -> tuple[list[Blocking], Path | None]:
    """Resolve config; refuse before any repository is touched.

    Validating (or planning against) the fictional example candidate while a real
    overlay is the subject is the worst possible outcome of this command, so the
    example fallback is a refusal whenever ``private`` is in scope.
    """
    try:
        active = config.config_path()
    except Exception as error:  # ConfigNotFound/ConfigError and anything they wrap
        return [Blocking(CODE_CONFIG_UNRESOLVED, None, "config.yaml", str(error))], None

    if "private" not in scope:
        return [], None

    if active == config.EXAMPLE_CONFIG:
        return [Blocking(
            CODE_CONFIG_EXAMPLE, "private", str(active),
            "config resolved to the tracked example persona while the private "
            "overlay is in scope; planning the fake candidate's overlay would "
            "produce a confidently wrong plan")], None

    if not config.overlay_mounted():
        return [Blocking(
            CODE_OVERLAY_NOT_MOUNTED, "private", str(config.overlay_root()),
            "config.overlay_mounted() is false; there is no private overlay to "
            "plan")], None

    overlay = config.overlay_root()
    if not (overlay / ".git").exists():
        return [Blocking(
            CODE_OVERLAY_NOT_A_REPO, "private", str(overlay),
            "the overlay root has no .git entry; it is not a repository")], None
    return [], overlay


def overlay_gitlink_blockers(public_root: Path, overlay: Path) -> list[Blocking]:
    """Refuse when the public repo TRACKS the overlay as a gitlink/submodule."""
    try:
        relative = overlay.resolve().relative_to(public_root.resolve())
    except ValueError:
        return []
    listed = CD.ReadOnlyGit(public_root).run(
        "ls-files", "--stage", "-z", "--", str(relative), check=False)
    if listed.returncode != 0:
        return []
    for record in listed.stdout.split(b"\0"):
        if record.startswith(b"160000"):
            return [Blocking(
                CODE_OVERLAY_IS_GITLINK, "public", str(relative),
                "the public repository tracks the overlay path as a gitlink; two "
                "repositories claim the same tree and ownership is ambiguous")]
    return []


def resolve_json_out(requested: str | None, public_root: Path,
                     run_id: str) -> tuple[Path | None, list[Blocking]]:
    """Default under the git-ignored ``local/``; refuse a tracked destination."""
    default = public_root / "local" / "cutover" / run_id / "plan.json"
    if requested is None:
        return default, []
    target = Path(requested).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    else:
        target = target.resolve()
    try:
        inside = target.relative_to(public_root.resolve())
    except ValueError:
        return target, []
    if inside.parts and inside.parts[0] == "local":
        return target, []
    return None, [Blocking(
        CODE_JSON_OUT_TRACKED, None, str(target),
        "the plan names real overlay paths and application slugs; it may only be "
        "written outside the public repository or under its git-ignored local/")]


# ── prerequisites ────────────────────────────────────────────────────────────
def check_prerequisites(specs: Sequence[str],
                        states: dict[str, RepoState]) -> tuple[list[dict], list[Blocking]]:
    records: list[dict] = []
    blocking: list[Blocking] = []
    for spec in specs:
        repo, _, rev = spec.partition(":")
        state = states.get(repo)
        if state is None or state.base is None:
            blocking.append(Blocking(
                CODE_PREREQ_UNREACHABLE, repo or None, rev or spec,
                f"{spec}: repository {repo!r} was not inventoried, so reachability "
                f"cannot be proven"))
            records.append({"oid": None, "reachable_from_base": False, "repo": repo,
                            "rev": rev, "subject": None})
            continue
        resolved = state.git.run("rev-parse", "--verify", "--quiet",
                                 f"{rev}^{{commit}}", check=False)
        if resolved.returncode != 0:
            blocking.append(Blocking(
                CODE_PREREQ_UNREACHABLE, repo, rev,
                f"{rev} does not resolve to a commit in {repo}"))
            records.append({"oid": None, "reachable_from_base": False, "repo": repo,
                            "rev": rev, "subject": None})
            continue
        oid = resolved.stdout.decode("ascii", "replace").strip()
        subject = state.git.run("log", "-1", "--format=%s", oid, check=False)
        text = subject.stdout.decode("utf-8", "replace").strip().splitlines()
        summary = text[-1] if text else ""
        ancestor = state.git.run("merge-base", "--is-ancestor", oid, state.base,
                                 check=False)
        reachable = ancestor.returncode == 0
        records.append({"oid": oid, "reachable_from_base": reachable, "repo": repo,
                        "rev": rev, "subject": summary})
        if not reachable:
            blocking.append(Blocking(
                CODE_PREREQ_UNREACHABLE, repo, rev,
                f"{rev} is not reachable from {state.base_ref}; the workflow's own "
                f"premise (the prerequisites merged) is false"))
    return records, blocking


# ── steps ────────────────────────────────────────────────────────────────────
def build_steps(run_id: str, states: dict[str, RepoState]) -> list[dict]:
    """Propose the mechanical work, in the order an agent performs it.

    Nothing in this repository executes these steps: the AGENT performs them,
    guided by the plan.  ``argv`` is therefore documentation of the exact command,
    not a call site.
    """
    steps: list[dict] = []
    next_id = 1

    def add(step: dict) -> None:
        nonlocal next_id
        step["id"] = next_id
        next_id += 1
        steps.append(step)

    for name in REPO_NAMES:
        state = states.get(name)
        if state is None:
            continue
        ref_root = f"refs/cutover/{run_id}/{name}"
        replayable = [d for d in state.dirty
                      if d.action in (CD.ACTION_REPLAY, CD.ACTION_AGENT_RESOLVE)]
        copyable = [d for d in state.dirty if d.action == CD.ACTION_COPY]
        divergent = [d for d in state.dirty
                     if d.verdict == CD.VERDICT_CONTENT_DIVERGENT]
        preconditions = _preconditions(state)
        mutating = False

        if replayable:
            mutating = True
            branch = f"cutover/checkpoint-{run_id}"
            add({
                "argv": [["git", "switch", "-c", branch],
                         ["git", "add", "-A"],
                         ["git", "commit", "-m", f"Checkpoint before cutover {run_id}"]],
                "kind": KIND_MECHANICAL,
                "mutates": [f"refs/heads/{branch}"],
                "op": OP_CHECKPOINT,
                "preconditions": preconditions,
                "recovery_argv": ["git", "reset", "--hard", f"{ref_root}/pre-checkpoint"],
                "recovery_ref": f"{ref_root}/pre-checkpoint",
                "repo": name,
                "resumable": True,
                "summary": f"commit the dirty tree on {branch}",
            })
        if state.behind > 0 and replayable:
            mutating = True
            add({
                "argv": [["git", "rebase", state.base_ref]],
                "kind": KIND_MECHANICAL,
                "mutates": [f"refs/heads/cutover/checkpoint-{run_id}"],
                "op": OP_REPLAY,
                "preconditions": preconditions,
                "recovery_argv": ["git", "reset", "--hard", f"{ref_root}/pre-replay"],
                "recovery_ref": f"{ref_root}/pre-replay",
                "repo": name,
                "resumable": True,
                "summary": (f"rebase the checkpoint onto {state.base_ref} "
                            f"({(state.base or '')[:7]})"),
            })
        for path in divergent:
            proof = (
                "residual after link-rebase is EMPTY (upstream delta proven "
                "path-only)"
                if path.residual_after_link_rebase == CD.RESIDUAL_EMPTY
                else f"residual after link-rebase: {path.residual_after_link_rebase}"
                     f" ({path.residual_lines} line(s))"
            )
            add({
                "argv": None,
                "kind": KIND_AGENT,
                "mutates": [path.merged_path or path.path],
                "op": OP_RESOLVE,
                "preconditions": preconditions,
                "recovery_argv": None,
                "recovery_ref": f"{ref_root}/pre-replay",
                "repo": name,
                "resumable": True,
                "summary": f"{path.path} — {proof}",
            })
        if copyable:
            mutating = True
            manifest = f"local/cutover/{run_id}/copied.txt"
            argv = [
                ["python", "automation/cutover/verify_copy.py", "--copy",
                 "--from", str(state.root / d.path),
                 "--to", str(state.root / (d.merged_path or d.path)),
                 "--manifest", manifest]
                for d in copyable
            ]
            add({
                "argv": argv,
                "kind": KIND_MECHANICAL,
                "mutates": [str(state.root / (d.merged_path or d.path)) for d in copyable],
                "op": OP_COPY_IGNORED,
                "preconditions": [
                    {"kind": "destination-absent",
                     "value": str(state.root / (d.merged_path or d.path))}
                    for d in copyable
                ],
                "recovery_argv": None,
                "recovery_note": (
                    "nothing is overwritten or deleted; "
                    f"{manifest} lists exactly the destinations created"),
                "recovery_ref": None,
                "repo": name,
                "resumable": True,
                "summary": (f"copy {len(copyable)} git-ignored file(s) to their merged "
                            f"destination; create-only"),
            })
        if mutating:
            add({
                "argv": [["python", "automation/cutover/validate_cutover.py",
                          "--profile", VALIDATION_PROFILE, "--jobs", "4"]],
                "kind": KIND_MECHANICAL,
                "mutates": [],
                "op": OP_VALIDATE,
                "preconditions": [],
                "recovery_argv": None,
                "recovery_ref": None,
                "repo": name,
                "resumable": True,
                "summary": f"run the {VALIDATION_PROFILE} validation profile (read-only)",
            })
        add({
            "argv": None,
            "handoff": {"runbook": PUBLICATION_RUNBOOK, "skill": PUBLICATION_SKILL},
            "kind": KIND_HANDOFF,
            "mutates": [],
            "op": OP_PUBLISH,
            "preconditions": [],
            "recovery_argv": None,
            "recovery_ref": None,
            "repo": name,
            "resumable": True,
            "summary": "publication is the github-workflow runbook, not this tool",
        })
    return steps


def _preconditions(state: RepoState) -> list[dict]:
    worktree_digest = _digest(json.dumps(state.worktrees, sort_keys=True))
    dirty_digest = _digest(json.dumps(
        sorted((d.path, (d.blobs or {}).get("worktree")) for d in state.dirty)))
    return [
        {"kind": "head-oid", "value": state.head},
        {"kind": "no-in-progress-op"},
        {"kind": "worktree-set-digest", "value": worktree_digest},
        {"kind": "dirty-blob-digest", "value": dirty_digest},
    ]


# ── plan assembly ────────────────────────────────────────────────────────────
def build_plan(*, run_id: str, generated_at: datetime.datetime, session_id: str | None,
               argv: list[str], git_version: str, states: dict[str, RepoState],
               blocking: Sequence[Blocking], prerequisites: Sequence[dict],
               fetched: bool, full_json: bool = False) -> dict:
    steps = build_steps(run_id, states)
    planned = [s for s in states.values()]
    fresh = fetched and bool(planned) and all(s.fetched for s in planned)
    remote_state = "fresh" if fresh else "stale"
    if blocking:
        exit_code = 3
    elif remote_state != "fresh" or any(s["kind"] == KIND_AGENT for s in steps):
        exit_code = 1
    else:
        exit_code = 0
    return {
        "blocking": [b.to_json() for b in blocking],
        "exit_code": exit_code,
        "executable": exit_code == 0,
        "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {"argv": argv, "git_version": git_version, "tool": TOOL},
        "handoff": {"publication_runbook": PUBLICATION_RUNBOOK,
                    "publication_skill": PUBLICATION_SKILL},
        "prerequisites": list(prerequisites),
        "remote_knowledge": {
            "fetched": fetched,
            "per_repo": {
                name: {"age_seconds": state.fetch_age_seconds,
                       "remote": (state.remote or {}).get("name")}
                for name, state in sorted(states.items())
            },
            "state": remote_state,
        },
        "renames": {
            name: [{"from": r.old, "score": r.score, "to": r.new}
                   for r in state.renames]
            for name, state in sorted(states.items())
        },
        "repos": {name: state.to_json(full_json)
                  for name, state in sorted(states.items())},
        "run_id": run_id,
        "schema": SCHEMA,
        "session_id": session_id,
        # Decision 7 records similarity renames for the human table but never lets
        # one classify a path.  The design's schema block omitted the key; without
        # it the decision has nowhere to live.
        "similarity_renames": {
            name: [{"from": r.old, "score": r.score, "to": r.new}
                   for r in state.similarity_renames]
            for name, state in sorted(states.items())
        },
        "steps": steps,
        "validation_profile": VALIDATION_PROFILE,
    }


def dump_plan(plan: dict) -> str:
    return json.dumps(plan, indent=2, sort_keys=True) + "\n"


# ── human table ──────────────────────────────────────────────────────────────
TABLE_DIRTY_ROWS = 40

_KIND_LABEL = {KIND_MECHANICAL: "MECH", KIND_AGENT: "AGENT", KIND_HANDOFF: "HANDOFF"}

# Table ordering: the rows a human must act on first, then the merely reported.
_TABLE_RANK = {
    CD.VERDICT_UNSAFE: 0,
    CD.VERDICT_UNKNOWN: 1,
    CD.VERDICT_CONTENT_DIVERGENT: 2,
    CD.VERDICT_RENAMED: 3,
    CD.VERDICT_IGNORED: 4,
    CD.VERDICT_UNCHANGED: 5,
}


def _rank_for_table(dirty: Sequence[CD.DirtyPath]) -> list[CD.DirtyPath]:
    return sorted(dirty, key=lambda d: (0 if d.blocking else 1,
                                        _TABLE_RANK.get(d.verdict, 9), d.path))


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[:max(0, width - 1)] + "…"


def _row(cells: Sequence[tuple[str, int]]) -> str:
    return "  ".join(_truncate(value, width).ljust(width)
                     for value, width in cells).rstrip()


def print_table(plan: dict, states: dict[str, RepoState], out) -> None:
    run_id = plan["run_id"]
    print(f"cutover plan  run {run_id}   ({TABLE_PRIVACY_WARNING})", file=out)
    print(DISAMBIGUATION_LINE, file=out)
    remote = plan["remote_knowledge"]
    if remote["state"] == "fresh":
        ages = [str(v["age_seconds"]) for v in remote["per_repo"].values()
                if v["age_seconds"] is not None]
        print(f"remote knowledge: FRESH (fetched {'/'.join(ages) or '0'}s ago)", file=out)
    else:
        print("remote knowledge: STALE (no --fetch, or a fetch did not cover every "
              "planned repo) — no plan built on it is executable", file=out)
    print("", file=out)

    print(_row([("REPO", 8), ("BRANCH", 38), ("BASE", 14), ("AHEAD", 6),
                ("BEHIND", 7), ("WORKTREES", 10), ("DIRTY", 6)]), file=out)
    for name, state in sorted(states.items()):
        others = sum(1 for w in state.worktrees if not w["is_current"])
        worktrees = f"{len(state.worktrees)} ({others} other)" if others else str(len(state.worktrees))
        print(_row([
            (name, 8),
            (state.branch or "(detached)", 38),
            (state.base_ref, 14),
            (str(state.ahead), 6),
            (str(state.behind), 7),
            (worktrees, 10),
            (str(len(state.dirty)), 6),
        ]), file=out)

    if plan["prerequisites"]:
        print("", file=out)
        print("PREREQUISITES", file=out)
        for record in plan["prerequisites"]:
            verdict = ("REACHABLE" if record["reachable_from_base"] else "UNREACHABLE")
            oid = (record["oid"] or "-")[:7]
            print("  " + _row([
                (str(record["repo"]), 8), (oid, 8),
                (record["subject"] or "", 40),
                (f"{verdict} from {record['rev']}", 34),
            ]), file=out)

    for name, state in sorted(states.items()):
        if not state.dirty:
            continue
        print("", file=out)
        print(f"DIRTY PATHS — {name} ({len(state.dirty)})", file=out)
        print(_row([("VERDICT", 26), ("PATH", 34), ("MERGED PATH", 34),
                    ("EVIDENCE", 46)]), file=out)
        # ``--ignored=matching`` lists every ignored file individually — that is
        # what surfaces the ones that must be copied, and it is also what makes a
        # real checkout report thousands of them.  The TABLE is capped; the JSON
        # always carries every path, exactly as long paths are truncated here and
        # never there.
        shown = _rank_for_table(state.dirty)
        for path in shown[:TABLE_DIRTY_ROWS]:
            print(_row([
                (path.verdict, 26),
                (path.path, 34),
                (path.merged_path or "—", 34),
                (path.verdict_reason, 46),
            ]), file=out)
        if len(shown) > TABLE_DIRTY_ROWS:
            print(f"  … {len(shown) - TABLE_DIRTY_ROWS} more in the plan json "
                  f"(the table is capped; the json is not)", file=out)

    for name, state in sorted(states.items()):
        if not state.similarity_renames:
            continue
        print("", file=out)
        print(f"SIMILARITY RENAMES — {name} ({len(state.similarity_renames)}) — "
              f"recorded only; never classify a path", file=out)
        for rename in state.similarity_renames:
            print("  " + _row([(f"R{rename.score:03d}", 6), (rename.old, 40),
                               (rename.new, 40)]), file=out)

    steps = plan["steps"]
    if steps:
        counts = {kind: sum(1 for s in steps if s["kind"] == kind) for kind in STEP_KINDS}
        print("", file=out)
        print(f"PROPOSED STEPS ({len(steps)}) — {counts[KIND_MECHANICAL]} mechanical · "
              f"{counts[KIND_AGENT]} agent · {counts[KIND_HANDOFF]} handoff", file=out)
        print("  the mechanical steps are performed by the AGENT, guided by this plan; "
              "no executor ships in this repository", file=out)
        print(_row([("#", 3), ("KIND", 9), ("OP", 14), ("REPO", 8), ("SUMMARY", 50),
                    ("RECOVERY REF", 44)]), file=out)
        for step in steps:
            print(_row([
                (str(step["id"]), 3),
                (_KIND_LABEL[step["kind"]], 9),
                (step["op"], 14),
                (step["repo"], 8),
                (step["summary"], 50),
                (step.get("recovery_ref") or "—", 44),
            ]), file=out)

    blocking = plan["blocking"]
    print("", file=out)
    if blocking:
        print(f"BLOCKING ({len(blocking)})", file=out)
        for item in blocking:
            print(f"  {item['code']}  {item['repo'] or '-'}  {item['subject']}",
                  file=out)
            print(f"      {item['message']}", file=out)
        print(f"REFUSED: {len(blocking)} blocking condition(s). No plan is executable.",
              file=out)
    elif plan["exit_code"] == 1:
        print("NEEDS JUDGEMENT: the plan is safe to read, but at least one step needs "
              "an agent, or remote knowledge is stale.", file=out)
    else:
        print("EXECUTABLE: every proposed step is mechanical and the state is fresh.",
              file=out)


def print_explanation(path: str, states: dict[str, RepoState], out) -> int:
    for name, state in sorted(states.items()):
        for dirty in state.dirty:
            if dirty.path != path:
                continue
            print(f"{DISAMBIGUATION_LINE}", file=out)
            print(f"explain: {name}:{dirty.path}", file=out)
            print(f"  verdict          {dirty.verdict}", file=out)
            print(f"  reason           {dirty.verdict_reason}", file=out)
            print(f"  action           {dirty.action}", file=out)
            print(f"  merged path      {dirty.merged_path or '—'}", file=out)
            print(f"  rename           {dirty.rename or '—'}", file=out)
            print(f"  blob fork        {dirty.blobs.get('fork') or '—'}   "
                  f"({state.merge_base or '?'}:{dirty.path})", file=out)
            print(f"  blob merged      {dirty.blobs.get('merged') or '—'}   "
                  f"({state.base_ref}:{dirty.merged_path or '—'})", file=out)
            print(f"  blob worktree    {dirty.blobs.get('worktree') or '—'}   "
                  f"(git hash-object, no -w)", file=out)
            print(f"  residual         {dirty.residual_after_link_rebase} "
                  f"({dirty.residual_lines} line(s))", file=out)
            print(f"  destination      exists={dirty.destination_exists} "
                  f"bytes_equal={dirty.destination_bytes_equal}", file=out)
            if dirty.blocking:
                for code, message in dirty.blocking:
                    print(f"  BLOCKING         {code}: {message}", file=out)
            print(f"  prefix pairs     {list(state.prefix_pairs) or '—'}", file=out)
            return 0
    print(f"explain: {path} is not a dirty path in any inventoried repository",
          file=out)
    return 3


# ── CLI ──────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            f"{DISAMBIGUATION_LINE}  Plan — read-only — how to bring local "
            f"work onto a layout that just merged. It never mutates: the mechanical "
            f"steps it proposes are performed by the agent, guided by the plan."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", choices=("public", "private", "both"), default="both",
                        help="which mounted repositories to inventory (default: both)")
    parser.add_argument("--fetch", action="store_true",
                        help="authorise network: fetch both remotes (writes only "
                             "remote-tracking refs). Without it remote facts are "
                             "stamped stale and no plan can be executable.")
    parser.add_argument("--base", default="origin/main", metavar="REF",
                        help="the merged base each repo is brought onto "
                             "(default: origin/main)")
    parser.add_argument("--prereq", action="append", default=[], metavar="REPO:REV",
                        help="a prerequisite commit that must be reachable from that "
                             "repo's resolved base (repeatable)")
    parser.add_argument("--json-out", metavar="PATH",
                        help="machine-readable plan (default: "
                             "local/cutover/<run-id>/plan.json). Refused inside the "
                             "public repo outside local/.")
    parser.add_argument("--explain", metavar="PATH",
                        help="print the full evidence chain for one dirty path and exit")
    parser.add_argument("--session-id", default=os.environ.get("JOBHUNT_SESSION_ID"),
                        metavar="ID",
                        help="correlation id matching the metrics collector's "
                             "session_id (default: $JOBHUNT_SESSION_ID)")
    parser.add_argument("--full-json", action="store_true",
                        help="emit every dirty path individually instead of "
                             "rolling up git-ignored paths that have no "
                             "counterpart in the merged layout. Against the real "
                             "repositories that is a ~72 MB plan; the rollup keeps "
                             "every actionable entry, including every ignored path "
                             "that DOES need copying.")
    parser.add_argument("--no-color", action="store_true",
                        help="never emit ANSI escapes (the table is plain either way "
                             "when stdout is not a terminal)")
    # Test seam, same convention as automation/ci/classify_changes.py --repository:
    # the planner must be pointable at a throwaway checkout so its own suite never
    # inventories the developer's live tree.
    parser.add_argument("--public-root", type=Path, default=REPO_ROOT,
                        help=argparse.SUPPRESS)
    return parser


def canonical_argv(args: argparse.Namespace) -> list[str]:
    """The flags a run used — never the --json-out path (it names owner data)."""
    argv = ["--repo", args.repo, "--base", args.base]
    if args.fetch:
        argv.append("--fetch")
    for prereq in args.prereq:
        argv.extend(["--prereq", prereq])
    if args.full_json:
        argv.append("--full-json")
    if args.no_color:
        argv.append("--no-color")
    return argv


def main(argv: Sequence[str] | None = None, out=None) -> int:
    """Fail closed on a crash.

    An unhandled exception would otherwise reach ``raise SystemExit(main())``
    and exit **1** — which in this tool's contract means "the plan is safe to
    read but needs agent judgement". A crash is not a plan, and a caller that
    branches on ``3 == refused`` would read a traceback as a readable one.
    Worker exceptions re-raised out of the thread pool are the live case.
    """
    out = out or sys.stdout
    try:
        return _plan(argv, out)
    except SystemExit:
        raise  # argparse's own exit 2, and any deliberate exit
    except BaseException as exc:  # deliberate catch-all: refusing beats guessing
        print(f"REFUSED  crashed: {type(exc).__name__}: {exc}", file=out)
        traceback.print_exc(file=sys.stderr)
        return 3


def _plan(argv: Sequence[str] | None, out) -> int:
    args = build_parser().parse_args(argv)
    run_id = make_run_id()
    generated_at = _utc_now()
    scope = REPO_NAMES if args.repo == "both" else (args.repo,)
    public_root = Path(args.public_root).resolve()

    blocking: list[Blocking] = []
    json_out, json_blocking = resolve_json_out(args.json_out, public_root, run_id)
    blocking.extend(json_blocking)

    config_blocking, overlay = config_blockers(scope)
    blocking.extend(config_blocking)
    if overlay is not None:
        blocking.extend(overlay_gitlink_blockers(public_root, overlay))

    states: dict[str, RepoState] = {}
    if "public" in scope:
        states["public"] = RepoState("public", public_root,
                                     CD.ReadOnlyGit(public_root, allow_fetch=args.fetch),
                                     base_ref=args.base)
    if "private" in scope and overlay is not None:
        states["private"] = RepoState("private", overlay,
                                      CD.ReadOnlyGit(overlay, allow_fetch=args.fetch),
                                      base_ref=args.base)

    # Both repositories are inventoried concurrently: they share no state, and a
    # --fetch run is dominated by two independent network round trips.
    if states:
        with ThreadPoolExecutor(max_workers=max(1, len(states))) as pool:
            futures = {name: pool.submit(inventory_repo, state, fetch=args.fetch)
                       for name, state in states.items()}
            for name in sorted(futures):
                blocking.extend(futures[name].result())

    prerequisites, prereq_blocking = check_prerequisites(args.prereq, states)
    blocking.extend(prereq_blocking)

    blocking.sort(key=lambda b: (BLOCKING_CODES.index(b.code)
                                 if b.code in BLOCKING_CODES else len(BLOCKING_CODES),
                                 b.repo or "", b.subject))

    if args.explain:
        rc = print_explanation(args.explain, states, out)
        # --explain is a narrower VIEW of the same inventory, never a lighter
        # contract. A blocking condition found while building that inventory
        # still refuses: exit 0 asserts "blocking is empty", and returning it
        # here with blocking non-empty would report a refusal as executable.
        return 3 if blocking else rc

    git_version = CD.ReadOnlyGit(public_root).version()
    plan = build_plan(run_id=run_id, generated_at=generated_at,
                      session_id=args.session_id, argv=canonical_argv(args),
                      git_version=git_version, states=states, blocking=blocking,
                      prerequisites=prerequisites, fetched=args.fetch,
                      full_json=args.full_json)

    print_table(plan, states, out)
    if json_out is not None:
        try:
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(dump_plan(plan), encoding="utf-8")
            print(f"plan json: {json_out}", file=out)
        except OSError as error:
            print(f"plan json: could not be written ({error})", file=out)
    else:
        print("plan json: NOT WRITTEN (the requested destination was refused)",
              file=out)
    return int(plan["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
