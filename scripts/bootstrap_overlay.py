#!/usr/bin/env python3
"""Wire a fresh checkout after cloning: private-overlay symlinks + git hooks.

Stdlib-only and idempotent — safe to re-run. Correct links are left untouched, a
foreign file or a foreign git hook is NEVER clobbered (it is warned about
instead). This is the one-shot "make my checkout work" step referenced by
``README.md``, ``docs/PRIVATE_OVERLAY.md``, and ``CONTRIBUTING.md``.

What it does:
  (a) If the private overlay is mounted at ``private/``: symlink the private
      ``coding-interview`` skill, each ``private/job-search-profiles/*.yaml``, and
      each public skill's ``private/skills/references_private/<skill>/`` directory
      into their canonical toolkit paths.
  (b) Always: install the tracked git hooks (``hooks/pre-commit`` /
      ``hooks/pre-push``) into ``.git/hooks`` — only when missing or already
      pointing there; a foreign hook is left alone with a warning.
  (c) If ``config.yaml`` is missing while the overlay is mounted: print a reminder
      to create it (never auto-written).

Usage:
    python scripts/bootstrap_overlay.py            # apply
    python scripts/bootstrap_overlay.py --check     # report only; make no changes
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# scripts/bootstrap_overlay.py -> repo root is one parent up.
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


def _git_hooks_dir() -> Path | None:
    """Resolve ``.git/hooks`` for a normal repo, a worktree, or a submodule."""
    git = REPO_ROOT / ".git"
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
                gitdir = (REPO_ROOT / gitdir).resolve()
            return gitdir / "hooks"
    return None


def _overlay_links(private: Path) -> list[tuple[Path, Path]]:
    """(link, dest) pairs for the overlay symlinks, given a mounted ``private/``."""
    links = [
        (REPO_ROOT / ".agents/skills/coding-interview",
         private / "skills/coding-interview"),
    ]
    profiles = private / "job-search-profiles"
    if profiles.is_dir():
        for yaml_file in sorted(profiles.glob("*.yaml")):
            link = REPO_ROOT / ".agents/skills/job-search/profiles" / yaml_file.name
            links.append((link, yaml_file))
    private_references = private / "skills/references_private"
    if private_references.is_dir():
        for skill_dir in sorted(path for path in private_references.iterdir() if path.is_dir()):
            public_skill = REPO_ROOT / ".agents/skills" / skill_dir.name
            if public_skill.is_dir():
                links.append((public_skill / "references_private", skill_dir))
    return links


def bootstrap(check: bool) -> int:
    results: list[tuple[str, str]] = []

    # (a) Overlay symlinks — only when the overlay is mounted.
    private = REPO_ROOT / "private"
    if private.is_dir():
        for link, dest in _overlay_links(private):
            status, msg, target = _plan_symlink(link, dest, allow_replace_symlink=True)
            if status in (CREATE, UPDATE) and not dest.exists():
                results.append((SKIP, f"{_disp(link)} (overlay target {_disp(dest)} missing; skipped)"))
                continue
            results.append((status, msg))
            if status in (CREATE, UPDATE) and not check:
                _apply_symlink(link, target, status)
    else:
        results.append((SKIP, "private/ overlay not mounted — no overlay symlinks to wire"))

    # (b) Git hooks — always.
    hooks_dir = _git_hooks_dir()
    if hooks_dir is None:
        results.append((WARN, ".git not found — skipping git-hook install"))
    else:
        for name in ("pre-commit", "pre-push"):
            src = REPO_ROOT / "hooks" / name
            if not src.is_file():
                results.append((SKIP, f"hooks/{name} not present — skipping"))
                continue
            link = hooks_dir / name
            # Foreign hooks are never overwritten: only create-if-missing or no-op.
            status, msg, target = _plan_symlink(link, src, allow_replace_symlink=False)
            results.append((status, msg))
            if status == CREATE and not check:
                _apply_symlink(link, target, status)

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
