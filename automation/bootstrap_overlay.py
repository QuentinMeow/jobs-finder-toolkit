#!/usr/bin/env python3
"""Wire a fresh checkout after cloning: local Git setup + overlay skill links.

Stdlib-only and idempotent — safe to re-run. Correct links are left untouched, a
foreign file or a foreign git hook is NEVER clobbered (it is warned about
instead). This is the one-shot "make my checkout work" step referenced by
``README.md``, ``docs/handbook/private-overlay.md``, and ``CONTRIBUTING.md``.

It writes NOTHING tracked into the public tree. Overlay-only skills are reached
through the agent-host link trees below, while the other private content families
use ``config.skill_references_dir()`` and ``config.search_profiles_dir()``. The
rule has no exceptions — if a path does not start with ``private/``, what you
write there is published unless it is runtime metadata explicitly managed here.

What it does:
  (a) If the private overlay is mounted at ``private/``: link each private skill
      (``private/skills/<name>/SKILL.md``) into the Codex, Claude Code, and Cursor
      agent-host trees, so every runtime lists it alongside the public skills.
      The links point STRAIGHT at ``private/skills/<name>`` — no public-tree hop.
      Their exact paths are written only to ``.git/info/exclude`` (repository-local
      Git metadata), never to the tracked ``.gitignore``.
  (b) Always: install managed dispatchers for the tracked toolkit hooks
      (``automation/hooks/pre-commit`` / ``pre-push``) into Git's active hook
      directory. A dispatcher resolves the invoking worktree at runtime, so every
      branch runs its own tracked hook body even though linked worktrees share hook
      metadata. Missing and non-running legacy installs are repaired. The overlay's
      active hook directory receives durable managed copies of
      ``overlay-pre-commit`` / ``overlay-pre-push``; those do not point back into a
      disposable public worktree. Runnable foreign hooks are always left untouched.
  (c) Always: install the repository-local ``git ws`` alias for the tracked
      workspace dashboard. A conflicting user-owned alias is left untouched.
  (d) If ``config.yaml`` is missing while the overlay is mounted: print a reminder
      to create it (never auto-written).

Usage:
    python automation/bootstrap_overlay.py            # apply
    python automation/bootstrap_overlay.py --check     # report only; make no changes

Exit codes: an apply run exits 0 — it repairs what it owns, and foreign Git setup
it must not clobber is a warning, not a failure it can act on. ``--check`` is a
health report and exits 1 when a managed hook or alias is missing, mis-wired, or
shadowed by foreign setup, so an incomplete checkout does not look ready.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# automation/bootstrap_overlay.py -> repo root is one parent up.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Status tags for the report.
OK = "ok"        # already correct — no-op
CREATE = "create"
UPDATE = "update"  # a link we own replaced (overlay adapters, broken hook installs)
REMOVE = "remove"  # obsolete generated adapter removed
SKIP = "skip"
WARN = "warn"    # foreign file / hook left untouched, or missing prerequisite
NOTE = "note"    # informational reminder

WORKSPACE_ALIAS_KEY = "alias.ws"
WORKSPACE_ALIAS_VALUE = "!./automation/workspace/status.py"


def _disp(p: Path) -> str:
    """Repo-root-relative path when possible, else the absolute path."""
    try:
        return p.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(p)


def _rel_target(link: Path, dest: Path) -> str:
    """Relative symlink target from ``link``'s own directory to ``dest``."""
    return os.path.relpath(dest, start=link.parent)


def _plan_symlink(link: Path, dest: Path, *, allow_replace_symlink: bool):
    """Classify making ``link`` -> ``dest``. Returns ``(status, message, target)``.

    missing -> CREATE; already-correct symlink -> OK; stale symlink -> UPDATE when
    ``allow_replace_symlink`` else WARN (foreign); a real (non-symlink) file/dir at
    ``link`` -> WARN (never clobbered).
    """
    target = _rel_target(link, dest)
    if link.is_symlink():
        cur = os.readlink(link)
        if cur == target or os.path.realpath(link) == os.path.realpath(dest):
            return OK, f"{_disp(link)} -> {target} (already correct)", target
        if allow_replace_symlink:
            return UPDATE, f"{_disp(link)} -> {target} (was: {cur})", target
        return WARN, f"{_disp(link)} is a foreign symlink -> {cur}; leaving it untouched", target
    if link.exists():
        return WARN, f"{_disp(link)} exists and is not a symlink; leaving it untouched", target
    return CREATE, f"{_disp(link)} -> {target}", target


def _apply_symlink(link: Path, target: str, status: str) -> None:
    if status == UPDATE and (link.is_symlink() or link.exists()):
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, link)


def _git_hooks_dir(repo: Path | None = None) -> Path | None:
    """Resolve the hook directory Git actually uses for ``repo``.

    ``.git`` is a file in a linked worktree, and its referenced administrative
    directory is *not* where Git reads hooks.  ``git rev-parse --git-path``
    resolves the shared common directory and also honours ``core.hooksPath``.
    """
    repo = REPO_ROOT if repo is None else repo
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    hooks = Path(raw)
    if not hooks.is_absolute():
        hooks = repo / hooks
    return hooks.resolve()


def _git_common_dir(repo: Path | None = None) -> Path | None:
    """Resolve Git's common metadata dir for a normal checkout or worktree."""
    repo = REPO_ROOT if repo is None else repo
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    common = Path(raw)
    if not common.is_absolute():
        common = repo / common
    return common.resolve()


def _install_workspace_alias(
        check: bool, results: list[tuple[str, str]]) -> list[str]:
    """Install ``git ws`` in this repository's local Git configuration.

    Local aliases are not cloned. Bootstrap owns only the missing value and
    never replaces a value the user already configured.
    """
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "config", "--local", "--get-all",
         WORKSPACE_ALIAS_KEY],
        capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        message = "cannot inspect repository-local git ws alias"
        results.append((WARN, message))
        return [message]

    values = proc.stdout.splitlines() if proc.returncode == 0 else []
    if values == [WORKSPACE_ALIAS_VALUE]:
        results.append((OK, "repository-local git ws alias already correct"))
        return []
    if values:
        rendered = ", ".join(repr(value) for value in values)
        message = ("repository-local git ws alias is user-owned "
                   f"({rendered}); leaving it untouched")
        results.append((WARN, message))
        return [message]

    results.append((CREATE, "repository-local git ws alias"))
    if check:
        return ["repository-local git ws alias is not installed"]
    write = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "config", "--local", "--add",
         WORKSPACE_ALIAS_KEY, WORKSPACE_ALIAS_VALUE],
        capture_output=True, text=True)
    if write.returncode != 0:
        message = "cannot install repository-local git ws alias"
        results.append((WARN, message))
        return [message]
    return []


LOCAL_EXCLUDE_BEGIN = "# BEGIN jobhunt overlay skill adapters (managed)"
LOCAL_EXCLUDE_END = "# END jobhunt overlay skill adapters (managed)"


def _git_worktree_paths(repo: Path | None = None) -> list[Path] | None:
    """Return every live worktree sharing ``repo``'s common Git metadata.

    A partial successful response is more dangerous than a command failure: it
    could make the shared exclude writer prune another checkout's private path.
    Validate every documented porcelain record and fail closed on any unknown or
    incomplete field.
    """
    repo = REPO_ROOT if repo is None else repo
    proc = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        return None

    records: list[list[str]] = []
    record: list[str] = []
    for line in [*proc.stdout.splitlines(), ""]:
        if line:
            record.append(line)
        elif record:
            records.append(record)
            record = []
    if not records:
        return None

    paths: list[Path] = []
    seen_paths: set[Path] = set()
    for fields in records:
        if not fields[0].startswith("worktree "):
            return None
        raw_path = fields[0].removeprefix("worktree ")
        if not raw_path or not Path(raw_path).is_absolute():
            return None

        seen: set[str] = set()
        head = False
        branch_state = False
        bare = False
        prunable = False
        for field in fields[1:]:
            key, separator, value = field.partition(" ")
            if key not in {"HEAD", "branch", "detached", "bare", "locked", "prunable"}:
                return None
            if key in seen:
                return None
            seen.add(key)
            if key == "HEAD":
                if (not separator or len(value) not in (40, 64)
                        or any(char not in "0123456789abcdefABCDEF" for char in value)):
                    return None
                head = True
            elif key == "branch":
                if not separator or not value.startswith("refs/heads/"):
                    return None
                if value == "refs/heads/" or branch_state:
                    return None
                branch_state = True
            elif key == "detached":
                if separator or branch_state:
                    return None
                branch_state = True
            elif key == "bare":
                if separator:
                    return None
                bare = True
            elif key == "locked":
                # An optional free-form reason follows the field name.
                pass
            elif key == "prunable":
                # A prunable registration is not a live checkout to inspect.
                prunable = True

        if bare:
            if head or branch_state:
                return None
        elif not head or not branch_state:
            return None
        try:
            path = Path(raw_path).resolve()
        except OSError:
            return None
        if path in seen_paths:
            return None
        seen_paths.add(path)
        if not bare and not prunable:
            paths.append(path)
    return paths


def _managed_exclude_patterns(existing: str) -> set[str]:
    """Extract this tool's current block, rejecting malformed markers."""
    lines = existing.splitlines()
    begin = [i for i, line in enumerate(lines) if line == LOCAL_EXCLUDE_BEGIN]
    end = [i for i, line in enumerate(lines) if line == LOCAL_EXCLUDE_END]
    if len(begin) != len(end) or len(begin) > 1 or (begin and begin[0] > end[0]):
        raise ValueError("managed overlay-skill marker block is malformed")
    if not begin:
        return set()
    return set(lines[begin[0] + 1:end[0]])


def _render_local_excludes(existing: str, patterns: list[str]) -> str:
    """Replace this tool's block while preserving every user-owned exclude line."""
    lines = existing.splitlines()
    _managed_exclude_patterns(existing)
    begin = [i for i, line in enumerate(lines) if line == LOCAL_EXCLUDE_BEGIN]
    end = [i for i, line in enumerate(lines) if line == LOCAL_EXCLUDE_END]
    if begin:
        del lines[begin[0]:end[0] + 1]
    while lines and not lines[-1]:
        lines.pop()
    if lines:
        lines.append("")
    lines.extend([LOCAL_EXCLUDE_BEGIN, *sorted(patterns), LOCAL_EXCLUDE_END])
    return "\n".join(lines) + "\n"


def _live_worktree_adapter_patterns() -> set[str] | None:
    """Collect generated adapter paths still present in any live worktree.

    ``info/exclude`` belongs to Git's common directory, so replacing its managed
    block from only the current checkout could expose another worktree's private
    adapters to ``git add``.  ``None`` means the inventory was incomplete and
    callers must conservatively retain the old managed rows.
    """
    worktrees = _git_worktree_paths()
    if worktrees is None:
        return None
    patterns: set[str] = set()
    try:
        for root in worktrees:
            for link in _owned_private_skill_links(root):
                patterns.add(f"/{link.relative_to(root).as_posix()}")
    except (OSError, ValueError):
        return None
    return patterns


def _sync_local_excludes(
        links: list[Path], *, check: bool,
        results: list[tuple[str, str]]) -> bool:
    """Keep exact overlay adapter names only in repository-local Git metadata.

    Returns True when the current checkout already has (or was just given) the
    required exclude block. False means callers must not create links: an
    unignored adapter path could otherwise be staged into the public index.
    """
    common = _git_common_dir()
    if common is None:
        results.append((WARN, ".git common dir not found — refusing to wire "
                              "overlay-only skill adapters"))
        return False
    path = common / "info" / "exclude"
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        patterns = {f"/{_disp(link)}" for link in links}
        live_patterns = _live_worktree_adapter_patterns()
        if live_patterns is None:
            # A partial inventory must never make another worktree's private
            # adapter stageable. Stale rows are harmless and can be pruned on a
            # later run after Git's worktree inventory is readable again.
            patterns.update(_managed_exclude_patterns(existing))
        else:
            patterns.update(live_patterns)
        desired = _render_local_excludes(existing, sorted(patterns))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        results.append((WARN, f"cannot manage repository-local skill excludes: {exc}"))
        return False
    if existing == desired:
        results.append((OK, "repository-local overlay skill excludes already correct"))
        return True
    status = UPDATE if path.exists() else CREATE
    results.append((status, "repository-local overlay skill excludes "
                            f"need {status}"))
    if check:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desired, encoding="utf-8")
    except OSError as exc:
        results.append((WARN, f"cannot write repository-local skill excludes: {exc}"))
        return False
    return True


# hook filename in .git/hooks -> tracked source under automation/hooks/.
TOOLKIT_HOOKS = {"pre-commit": "pre-commit", "pre-push": "pre-push"}
OVERLAY_HOOKS = {"pre-commit": "overlay-pre-commit", "pre-push": "overlay-pre-push"}
TOOLKIT_HOOK_MARKER = "# jobhunt-bootstrap managed toolkit dispatcher:"
OVERLAY_HOOK_MARKER = "# jobhunt-bootstrap managed overlay copy:"
HOOKS_SRC_DIR = "automation/hooks"


def _toolkit_dispatcher(source: str) -> str:
    """A stable shared hook that dispatches to the invoking worktree's code."""
    return f'''#!/bin/sh
{TOOLKIT_HOOK_MARKER} {source}
set -eu
root="$(git rev-parse --show-toplevel 2>/dev/null)" || {{
    echo "{source}: cannot resolve the invoking Git worktree; refusing." >&2
    exit 1
}}
hook="$root/automation/hooks/{source}"
if [ ! -x "$hook" ]; then
    echo "{source}: tracked hook missing or not executable at $hook; refusing." >&2
    exit 1
fi
exec "$hook" "$@"
'''


def _overlay_hook_copy(source: Path, source_name: str) -> str:
    """Render a durable managed copy of an overlay hook's tracked source."""
    text = source.read_text(encoding="utf-8")
    marker = f"{OVERLAY_HOOK_MARKER} {source_name}\n"
    if text.startswith("#!"):
        first, separator, rest = text.partition("\n")
        return first + "\n" + marker + (rest if separator else "")
    return marker + text


def _legacy_hook_symlink_is_repairable(link: Path) -> bool:
    """Recognise a non-running or toolkit-owned legacy hook symlink.

    A dangling symlink is safe to replace because Git cannot run it. A live
    symlink is repairable only when its target is inside the tracked hook
    directory of a registered worktree; live third-party hooks stay foreign.
    """
    if not link.is_symlink():
        return False
    if not link.exists():
        return True
    worktrees = _git_worktree_paths()
    if worktrees is None:
        return False
    resolved = link.resolve()
    return any(resolved.parent == (root / HOOKS_SRC_DIR).resolve()
               for root in worktrees)


def _plan_managed_hook(link: Path, payload: str, marker: str, source: str):
    """Classify a managed hook write without replacing a runnable foreign hook."""
    if link.is_symlink():
        target = os.readlink(link)
        dangling = not link.exists()
        if _legacy_hook_symlink_is_repairable(link):
            action = "repair non-running symlink" if dangling else "migrate managed symlink"
            return UPDATE, f"{_disp(link)} ({action}; was: {target})"
        return WARN, (f"{_disp(link)} is a foreign symlink -> {target}; "
                      "leaving it untouched")
    if link.exists():
        if not link.is_file():
            return WARN, (f"{_disp(link)} exists and is not a regular file; "
                          "leaving it untouched")
        try:
            current = link.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return WARN, f"cannot inspect {_disp(link)} ({exc}); leaving it untouched"
        if current == payload:
            return OK, f"{_disp(link)} (already correct)"
        if marker in current.splitlines()[:3]:
            return UPDATE, f"{_disp(link)} (managed hook needs update)"
        return WARN, f"{_disp(link)} is a foreign hook; leaving it untouched"
    return CREATE, f"{_disp(link)}"


def _apply_managed_hook(link: Path, payload: str) -> None:
    """Atomically create or update an executable managed hook file."""
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(f".{link.name}.jobhunt-{os.getpid()}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.chmod(0o755)
        os.replace(temporary, link)
    finally:
        if temporary.exists():
            temporary.unlink()


def _install_toolkit_hooks(hooks_dir: Path, sources: dict[str, str],
                           check: bool, results: list[tuple[str, str]]) -> list[str]:
    """Install branch-aware dispatchers in the toolkit's active hook path."""
    unwired: list[str] = []
    for name, source in sources.items():
        src = REPO_ROOT / HOOKS_SRC_DIR / source
        if not src.is_file():
            results.append((SKIP, f"{HOOKS_SRC_DIR}/{source} not present — skipping"))
            unwired.append(f"[toolkit] {_disp(hooks_dir / name)} has no tracked source")
            continue
        payload = _toolkit_dispatcher(source)
        marker = f"{TOOLKIT_HOOK_MARKER} {source}"
        link = hooks_dir / name
        status, msg = _plan_managed_hook(link, payload, marker, source)
        results.append((status, f"[toolkit] {msg}"))
        if status in (CREATE, UPDATE):
            if check:
                unwired.append(f"[toolkit] {_disp(link)} is not installed as a managed dispatcher")
            else:
                _apply_managed_hook(link, payload)
        elif status == WARN:
            unwired.append(f"[toolkit] {_disp(link)} is foreign, so the tracked guard does not run")
    return unwired


def _install_overlay_hooks(hooks_dir: Path, sources: dict[str, str],
                           check: bool, results: list[tuple[str, str]]) -> list[str]:
    """Install durable overlay-hook copies; never point at a public worktree."""
    unwired: list[str] = []
    for name, source in sources.items():
        src = REPO_ROOT / HOOKS_SRC_DIR / source
        if not src.is_file():
            results.append((SKIP, f"{HOOKS_SRC_DIR}/{source} not present — skipping"))
            unwired.append(f"[overlay] {_disp(hooks_dir / name)} has no tracked source")
            continue
        try:
            payload = _overlay_hook_copy(src, source)
        except (OSError, UnicodeDecodeError) as exc:
            results.append((WARN, f"cannot read {HOOKS_SRC_DIR}/{source}: {exc}"))
            unwired.append(f"[overlay] {_disp(hooks_dir / name)} source is unreadable")
            continue
        link = hooks_dir / name
        marker = f"{OVERLAY_HOOK_MARKER} {source}"
        status, msg = _plan_managed_hook(link, payload, marker, source)
        results.append((status, f"[overlay] {msg}"))
        if status in (CREATE, UPDATE):
            if check:
                unwired.append(f"[overlay] {_disp(link)} is not installed as a managed copy")
            else:
                _apply_managed_hook(link, payload)
        elif status == WARN:
            unwired.append(f"[overlay] {_disp(link)} is foreign, so the tracked guard does not run")
    return unwired


# Agent host trees that list installed skills. Mirrors
# ``automation/publish/sync_skill_manifests.SYMLINK_HOSTS``: that tool owns the
# entries for PUBLIC skills (``-> ../../skills/<name>``, tracked); this one owns
# the entries for PRIVATE skills (``-> ../../private/skills/<name>``,
# git-ignored). Neither touches the other's entries — they are told apart by
# where the link points.
SKILL_HOSTS = (".agents/skills", ".claude/skills", ".cursor/skills")


def _private_skill_links(private: Path) -> list[tuple[Path, Path]]:
    """(link, dest) pairs putting each private skill into the agent host trees.

    A private skill is any ``private/skills/<name>/`` holding a ``SKILL.md`` —
    which excludes the sibling ``references_private/`` notes folder. A host is
    skipped when its agent root does not exist, so a checkout that uses only a
    subset of the supported runtimes gets only those adapters.
    """
    skills_dir = private / "skills"
    if not skills_dir.is_dir():
        return []
    names = sorted(p.name for p in skills_dir.iterdir()
                   if p.is_dir() and (p / "SKILL.md").is_file())
    links: list[tuple[Path, Path]] = []
    for host in SKILL_HOSTS:
        host_dir = REPO_ROOT / host
        if not host_dir.parent.is_dir():
            continue
        for name in names:
            links.append((host_dir / name, skills_dir / name))
    return links


def _owned_private_skill_links(repo_root: Path | None = None) -> list[Path]:
    """Existing generated adapters whose targets point into overlay skills."""
    repo_root = REPO_ROOT if repo_root is None else repo_root
    links: list[Path] = []
    for host in SKILL_HOSTS:
        host_dir = repo_root / host
        try:
            entries = list(host_dir.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            continue
        for entry in entries:
            if not entry.is_symlink():
                continue
            target = os.readlink(entry).replace(os.sep, "/")
            if "private/skills/" in target:
                links.append(entry)
    return sorted(links)


def _not_ignored(links: list[Path]) -> list[str]:
    """Which of ``links`` git does NOT ignore (repo-relative). Empty off-git.

    Every private-skill runtime link MUST be git-ignored: its path names overlay
    content, and a ``git add -A`` that staged one would put a private path into
    the public index. The exact paths live only in the managed local exclude
    block; forgetting is silent, so it is reported here.
    """
    rels = [_disp(p) for p in links]
    if not rels:
        return []
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "--no-index", "--stdin"],
        input="\n".join(rels), capture_output=True, text=True)
    if proc.returncode not in (0, 1):  # 128 = not a git checkout
        return []
    ignored = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return [r for r in rels if r not in ignored]


def bootstrap(check: bool) -> int:
    results: list[tuple[str, str]] = []

    # (a) Private-skill runtime links — only when the overlay is mounted. These
    # land in the git-ignored agent host trees, never in the public tree.
    private = REPO_ROOT / "private"
    if private.is_dir():
        planned = _private_skill_links(private)
        wanted_links = {link for link, _ in planned}
        existing_owned = set(_owned_private_skill_links())
        protected_links = sorted(wanted_links | existing_owned)
        excludes_ready = _sync_local_excludes(
            protected_links, check=check, results=results)
        if excludes_ready:
            for link, dest in planned:
                # Only a link we already own (one pointing into private/skills/)
                # may be re-pointed. A same-named PUBLIC adapter or a third-party
                # install is foreign and is warned about, never clobbered.
                ours = (link.is_symlink()
                        and "private/skills/" in os.readlink(link).replace(os.sep, "/"))
                status, msg, target = _plan_symlink(
                    link, dest, allow_replace_symlink=ours)
                if status in (CREATE, UPDATE) and not dest.exists():
                    results.append((SKIP, f"{_disp(link)} (overlay target "
                                          f"{_disp(dest)} missing; skipped)"))
                    continue
                results.append((status, msg))
                if status in (CREATE, UPDATE) and not check:
                    _apply_symlink(link, target, status)
            stale = sorted(existing_owned - wanted_links)
            for link in stale:
                results.append((REMOVE, f"{_disp(link)} (overlay skill no longer present)"))
                if not check:
                    link.unlink()
            if stale and not check:
                # The first update protected stale paths until their generated
                # links were gone. Now prune those names from local metadata too.
                _sync_local_excludes(
                    sorted(wanted_links), check=False, results=results)
            for rel in _not_ignored([link for link, _ in planned]):
                results.append((WARN, f"{rel} is NOT git-ignored — re-run bootstrap "
                                      "to repair the repository-local exclude block"))
    else:
        results.append((SKIP, "private/ overlay not mounted — no private skills to wire"))

    # (b) Git hooks — always for this repo, plus the overlay's own when mounted.
    unwired_hooks: list[str] = []
    hooks_dir = _git_hooks_dir()
    if hooks_dir is None:
        results.append((WARN, ".git not found — skipping git-hook install"))
    else:
        unwired_hooks += _install_toolkit_hooks(
            hooks_dir, TOOLKIT_HOOKS, check, results)

    # The overlay is a separate git repo about to hold most of the owner's
    # commits, and it tracks no code of its own. Durable copies in its common
    # hook directory survive removal of the public worktree that ran bootstrap;
    # re-running bootstrap refreshes only copies bearing our ownership marker.
    # Hook installation changes Git metadata, never tracked owner data.
    if private.is_dir():
        overlay_hooks_dir = _git_hooks_dir(private)
        if overlay_hooks_dir is None:
            results.append((WARN, "private/.git not found — skipping overlay git-hook install"))
        else:
            unwired_hooks += _install_overlay_hooks(
                overlay_hooks_dir, OVERLAY_HOOKS, check, results)

    # (c) Repository-local command aliases — Git never clones these, so the
    # tracked bootstrap must install them on every device.
    incomplete_git_setup = _install_workspace_alias(check, results)

    # (d) config.yaml reminder (never auto-written).
    if private.is_dir() and not (REPO_ROOT / "config.yaml").exists():
        results.append((NOTE, "config.yaml is missing while private/ is mounted — copy "
                              "config.example.yaml to config.yaml and point paths.* at your "
                              "overlay data (not auto-created)."))

    mode = "CHECK (no changes)" if check else "APPLY"
    print(f"bootstrap_overlay [{mode}]  root={REPO_ROOT}")
    for status, msg in results:
        print(f"  [{status:>6}] {msg}")

    warns = [r for r in results if r[0] == WARN]
    pending = [r for r in results if r[0] in (CREATE, UPDATE, REMOVE)]
    if check and pending:
        print(f"\n{len(pending)} change(s) pending — re-run without --check to apply.")
    if warns:
        print(f"{len(warns)} warning(s) — foreign files/hooks left untouched (review above).")
    if unwired_hooks:
        print("\nGit hook(s) NOT wired to their tracked source — the leak guard does "
              "not run on commit or push here:")
        for line in unwired_hooks:
            print(f"  - {line}")
        print("Repair: run this script without --check. A FOREIGN hook is never "
              "clobbered — chain the tracked hook into it, or remove it, by hand.")
    if incomplete_git_setup:
        print("\nRepository-local Git command(s) NOT ready:")
        for line in incomplete_git_setup:
            print(f"  - {line}")
        print("Repair: run this script without --check. A conflicting user-owned "
              "alias is never overwritten; rename or remove it by hand first.")
    print("done." if not check else "check complete.")
    # An apply run repairs every hook it owns, so what is left is a foreign hook it
    # must not touch — a warning, not a failure it can act on. --check is a health
    # report: it fails whenever a hook that should be guarding this checkout is not.
    return 1 if (check and (unwired_hooks or incomplete_git_setup)) else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="report what would change and make no changes; exits 1 "
                             "when tracked local Git setup is incomplete")
    args = parser.parse_args(argv)
    return bootstrap(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
