#!/usr/bin/env python3
"""Wire a fresh checkout after cloning: private-skill runtime links + git hooks.

Stdlib-only and idempotent — safe to re-run. Correct links are left untouched, a
foreign file or a foreign git hook is NEVER clobbered (it is warned about
instead). This is the one-shot "make my checkout work" step referenced by
``README.md``, ``handbook/private-overlay.md``, and ``CONTRIBUTING.md``.

It writes NOTHING into the public tree. It used to create eight INBOUND symlinks
that put overlay content at public-looking paths — ``skills/coding-interview*``,
each public skill's ``references_private/``, and one per personal job-search
profile (whose FILENAME was itself a personal token sitting under ``skills/``).
All eight are gone: the private skills are reached through the agent-host link
trees below, and the other two families through ``config.skill_references_dir()``
and ``config.search_profiles_dir()``. The rule now has no exceptions — if a path
does not start with ``private/``, what you write there is published.

What it does:
  (a) If the private overlay is mounted at ``private/``: link each private skill
      (``private/skills/<name>/SKILL.md``) into the git-ignored agent host trees
      ``.claude/skills/<name>`` and ``.cursor/skills/<name>``, so the runtime
      lists the private skills alongside the public ones. The links point
      STRAIGHT at ``private/skills/<name>`` — no public-tree hop.
  (b) Always: install the tracked git hooks (``automation/hooks/pre-commit`` /
      ``automation/hooks/pre-push``) into ``.git/hooks`` — only when missing or already
      pointing there; a foreign hook is left alone with a warning. When the overlay
      is mounted, its OWN ``.git/hooks`` gets ``automation/hooks/overlay-pre-commit``
      / ``overlay-pre-push`` the same way, so the overlay is guarded without having
      to track a single file of its own.
  (c) If ``config.yaml`` is missing while the overlay is mounted: print a reminder
      to create it (never auto-written).

Usage:
    python automation/bootstrap_overlay.py            # apply
    python automation/bootstrap_overlay.py --check     # report only; make no changes
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
UPDATE = "update"  # stale overlay symlink replaced (overlay-managed links only)
SKIP = "skip"
WARN = "warn"    # foreign file / hook left untouched, or missing prerequisite
NOTE = "note"    # informational reminder


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
    """Resolve ``.git/hooks`` for a normal repo, a worktree, or a submodule."""
    repo = REPO_ROOT if repo is None else repo
    git = repo / ".git"
    if git.is_dir():
        return git / "hooks"
    if git.is_file():  # worktree/submodule: ".git" is "gitdir: <path>"
        try:
            line = git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if line.startswith("gitdir:"):
            gitdir = Path(line[len("gitdir:"):].strip())
            if not gitdir.is_absolute():
                gitdir = (repo / gitdir).resolve()
            return gitdir / "hooks"
    return None


# hook filename in .git/hooks -> tracked source under automation/hooks/.
TOOLKIT_HOOKS = {"pre-commit": "pre-commit", "pre-push": "pre-push"}
OVERLAY_HOOKS = {"pre-commit": "overlay-pre-commit", "pre-push": "overlay-pre-push"}


def _install_hooks(hooks_dir: Path, sources: dict[str, str], label: str,
                   check: bool, results: list[tuple[str, str]]) -> None:
    """Symlink each tracked hook into ``hooks_dir``; never clobber a foreign one."""
    for name, source in sources.items():
        src = REPO_ROOT / "automation/hooks" / source
        if not src.is_file():
            results.append((SKIP, f"automation/hooks/{source} not present — skipping"))
            continue
        link = hooks_dir / name
        # Foreign hooks are never overwritten: only create-if-missing or no-op.
        status, msg, target = _plan_symlink(link, src, allow_replace_symlink=False)
        results.append((status, f"[{label}] {msg}"))
        if status == CREATE and not check:
            _apply_symlink(link, target, status)


# Agent host trees that list installed skills. Mirrors
# ``automation/publish/sync_skill_manifests.SYMLINK_HOSTS``: that tool owns the
# entries for PUBLIC skills (``-> ../../skills/<name>``, tracked); this one owns
# the entries for PRIVATE skills (``-> ../../private/skills/<name>``,
# git-ignored). Neither touches the other's entries — they are told apart by
# where the link points.
SKILL_HOSTS = (".claude/skills", ".cursor/skills")


def _private_skill_links(private: Path) -> list[tuple[Path, Path]]:
    """(link, dest) pairs putting each private skill into the agent host trees.

    A private skill is any ``private/skills/<name>/`` holding a ``SKILL.md`` —
    which excludes the sibling ``references_private/`` notes folder. A host is
    skipped when its agent root (``.claude`` / ``.cursor``) does not exist, so a
    checkout that uses only one editor gets only that one.
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


def _not_ignored(links: list[Path]) -> list[str]:
    """Which of ``links`` git does NOT ignore (repo-relative). Empty off-git.

    Every private-skill runtime link MUST be git-ignored: it names overlay
    content, and a ``git add -A`` that staged one would put a private path into
    the public index. Adding a private skill therefore needs its two ``.gitignore``
    lines; forgetting is silent, so it is reported here.
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
        for link, dest in planned:
            # Only a link we already own (one pointing into private/skills/) may
            # be re-pointed. An entry the manifest generator owns (a same-named
            # PUBLIC skill, -> ../../skills/<name>) or a third-party install is
            # foreign and is warned about, never clobbered.
            ours = (link.is_symlink()
                    and "private/skills/" in os.readlink(link).replace(os.sep, "/"))
            status, msg, target = _plan_symlink(link, dest, allow_replace_symlink=ours)
            if status in (CREATE, UPDATE) and not dest.exists():
                results.append((SKIP, f"{_disp(link)} (overlay target {_disp(dest)} missing; skipped)"))
                continue
            results.append((status, msg))
            if status in (CREATE, UPDATE) and not check:
                _apply_symlink(link, target, status)
        for rel in _not_ignored([link for link, _ in planned]):
            results.append((WARN, f"{rel} is NOT git-ignored — add a `/{rel}` line to "
                                  ".gitignore so a private skill can never be staged"))
    else:
        results.append((SKIP, "private/ overlay not mounted — no private skills to wire"))

    # (b) Git hooks — always for this repo, plus the overlay's own when mounted.
    hooks_dir = _git_hooks_dir()
    if hooks_dir is None:
        results.append((WARN, ".git not found — skipping git-hook install"))
    else:
        _install_hooks(hooks_dir, TOOLKIT_HOOKS, "toolkit", check, results)

    # The overlay is a separate git repo about to hold most of the owner's
    # commits, and it tracks no code of its own — so its hooks are these tracked
    # scripts, symlinked in. Installing a symlink into private/.git/hooks/ is hook
    # installation, not a write to owner data: nothing tracked in the overlay is
    # created, changed, or removed.
    if private.is_dir():
        overlay_hooks_dir = _git_hooks_dir(private)
        if overlay_hooks_dir is None:
            results.append((WARN, "private/.git not found — skipping overlay git-hook install"))
        else:
            _install_hooks(overlay_hooks_dir, OVERLAY_HOOKS, "overlay", check, results)

    # (c) config.yaml reminder (never auto-written).
    if private.is_dir() and not (REPO_ROOT / "config.yaml").exists():
        results.append((NOTE, "config.yaml is missing while private/ is mounted — copy "
                              "config.example.yaml to config.yaml and point paths.* at your "
                              "overlay data (not auto-created)."))

    mode = "CHECK (no changes)" if check else "APPLY"
    print(f"bootstrap_overlay [{mode}]  root={REPO_ROOT}")
    for status, msg in results:
        print(f"  [{status:>6}] {msg}")

    warns = [r for r in results if r[0] == WARN]
    pending = [r for r in results if r[0] in (CREATE, UPDATE)]
    if check and pending:
        print(f"\n{len(pending)} change(s) pending — re-run without --check to apply.")
    if warns:
        print(f"{len(warns)} warning(s) — foreign files/hooks left untouched (review above).")
    print("done." if not check else "check complete.")
    # A report/apply run only fails on a genuinely broken environment, never on
    # warnings (foreign hooks are expected) or pending work in --check.
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="report what would change and make no changes")
    args = parser.parse_args(argv)
    return bootstrap(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
