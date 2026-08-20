#!/usr/bin/env python3
"""Show all local Git work for the toolkit and its optional private overlay.

This command is deliberately local-only: it reads registered worktrees, refs,
and cached remote-tracking refs, but never fetches or writes Git state.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
RENAME_CODES = {"R", "C"}


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
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
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


def _worktrees(repo: Path) -> list[Worktree]:
    raw = _git(repo, "worktree", "list", "--porcelain", "-z").stdout
    worktrees = _parse_worktree_records(raw)
    for worktree in worktrees:
        if worktree.bare:
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


def _merged_state(repo: Path, ref: str, base_ref: str | None) -> str:
    if base_ref is None:
        return "main missing"
    if ref == base_ref:
        return "main"
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


def _divergence(repo: Path, local_ref: str, upstream_ref: str) -> tuple[int, int]:
    result = _git(repo, "rev-list", "--left-right", "--count", f"{local_ref}...{upstream_ref}")
    left, right = result.stdout.strip().split()
    return int(left), int(right)


def _branches(
    repo: Path,
    worktrees: Sequence[Worktree],
) -> tuple[list[Branch], int, int, str | None]:
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
    base_ref = _base_ref(repo)
    consumed: set[str] = set()
    branches: list[Branch] = []

    for ref in locals_:
        upstream = remotes.get(ref.upstream_ref) if ref.upstream_ref else None
        upstream_missing = bool(ref.upstream_ref and upstream is None)
        ahead = behind = None
        if upstream is not None:
            ahead, behind = _divergence(repo, ref.full_name, upstream.full_name)
            consumed.add(upstream.full_name)
        branches.append(
            Branch(
                scope="L+R" if upstream is not None else "L",
                name=ref.short_name,
                ref=ref,
                upstream=upstream,
                upstream_missing=upstream_missing,
                ahead=ahead,
                behind=behind,
                merged=_merged_state(repo, ref.full_name, base_ref),
                worktree_path=checked_out.get(ref.full_name),
            )
        )

    for ref in remotes.values():
        if ref.full_name in consumed:
            continue
        branches.append(
            Branch(
                scope="R",
                name=ref.short_name,
                ref=ref,
                upstream=None,
                upstream_missing=False,
                ahead=None,
                behind=None,
                merged=_merged_state(repo, ref.full_name, base_ref),
                worktree_path=None,
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


def inspect_repository(label: str, root: Path) -> Repository:
    worktrees = _worktrees(root)
    branches, local_count, remote_count, base_ref = _branches(root, worktrees)
    return Repository(
        label=label,
        root=root.resolve(),
        worktrees=worktrees,
        branches=branches,
        remotes=_remotes(root),
        local_ref_count=local_count,
        remote_ref_count=remote_count,
        base_ref=base_ref,
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


def render(
    repositories: Sequence[Repository],
    workspace_root: Path,
    verbose: bool,
    palette: Palette,
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

        branch_count = _count("row", len(repo.branches))
        lines.append(palette.paint(f"  BRANCHES ({branch_count})", palette.BOLD))
        name_width = max((len(branch.name) for branch in repo.branches), default=1)
        sync_width = max((len(branch.sync) for branch in repo.branches), default=1)
        for branch in repo.branches:
            marker = "*" if branch.worktree_path else " "
            scope_color = palette.CYAN if branch.scope == "L+R" else (
                palette.BLUE if branch.scope == "L" else palette.MAGENTA
            )
            scope = palette.paint(f"{branch.scope:<3}", scope_color)
            merged = palette.paint(branch.merged, _merged_style(branch.merged, palette))
            lines.append(
                f"    {marker} {scope}  {branch.name:<{name_width}}  "
                f"{branch.sync:<{sync_width}}  {merged}"
            )
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
                if details:
                    lines.append(palette.paint("        " + " · ".join(details), palette.DIM))

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
                "merged = contained by local main",
                palette.DIM,
            ),
        ]
    )
    return "\n".join(lines)


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_toolkit_root(REPO_ROOT)
        repositories = [
            inspect_repository(label, root)
            for label, root in discover_repositories(REPO_ROOT)
        ]
    except GitError as exc:
        print(f"workspace status: {exc}", file=sys.stderr)
        return 2

    color_mode = "never" if args.no_color or os.environ.get("NO_COLOR") is not None else args.color
    use_color = color_mode == "always" or (color_mode == "auto" and sys.stdout.isatty())
    print(render(repositories, REPO_ROOT, args.verbose, Palette(use_color)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
