#!/usr/bin/env python3
"""Wire a fresh checkout after cloning: overlay-skill runtime links + git hooks.

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
  (b) Always: install the tracked git hooks (``automation/hooks/pre-commit`` /
      ``automation/hooks/pre-push``) into ``.git/hooks``. A missing hook is
      created and a BROKEN install of ours is repaired — see
      ``_hook_is_repairable``; a genuinely foreign hook is left alone with a
      warning. When the overlay is mounted, its OWN ``.git/hooks`` gets
      ``automation/hooks/overlay-pre-commit`` / ``overlay-pre-push`` the same way,
      so the overlay is guarded without having to track a single file of its own.
  (c) If ``config.yaml`` is missing while the overlay is mounted: print a reminder
      to create it (never auto-written).

Usage:
    python automation/bootstrap_overlay.py            # apply
    python automation/bootstrap_overlay.py --check     # report only; make no changes

Exit codes: an apply run exits 0 — it repairs what it owns, and a foreign hook it
must not clobber is a warning, not a failure it can act on. ``--check`` is a health
report and exits 1 when any of those hooks is not wired to its tracked source
(missing, dangling, mis-wired, or shadowed by a foreign hook), so a checkout whose
leak guard does not run fails a check instead of staying quiet.
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


LOCAL_EXCLUDE_BEGIN = "# BEGIN jobhunt overlay skill adapters (managed)"
LOCAL_EXCLUDE_END = "# END jobhunt overlay skill adapters (managed)"


def _render_local_excludes(existing: str, patterns: list[str]) -> str:
    """Replace this tool's block while preserving every user-owned exclude line."""
    lines = existing.splitlines()
    begin = [i for i, line in enumerate(lines) if line == LOCAL_EXCLUDE_BEGIN]
    end = [i for i, line in enumerate(lines) if line == LOCAL_EXCLUDE_END]
    if len(begin) != len(end) or len(begin) > 1 or (begin and begin[0] > end[0]):
        raise ValueError("managed overlay-skill marker block is malformed")
    if begin:
        del lines[begin[0]:end[0] + 1]
    while lines and not lines[-1]:
        lines.pop()
    if lines:
        lines.append("")
    lines.extend([LOCAL_EXCLUDE_BEGIN, *sorted(patterns), LOCAL_EXCLUDE_END])
    return "\n".join(lines) + "\n"


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
        patterns = [f"/{_disp(link)}" for link in links]
        desired = _render_local_excludes(existing, patterns)
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
HOOKS_SRC_DIR = "automation/hooks"


def _hook_is_repairable(link: Path, hooks_root: Path) -> bool:
    """Is this hook a BROKEN install of OURS rather than a third-party hook?

    Two shapes qualify, and under both git runs nothing — so retargeting the link
    cannot cost the checkout a hook it was actually using:

    * the target does not resolve. This is how moving ``hooks/`` to
      ``automation/hooks/`` disabled the leak guard on every checkout installed
      before the move: git skips a dangling hook without a word, so commits and
      pushes kept succeeding with no guard output at all.
    * the target resolves inside the tracked hooks directory but at the wrong
      name — ours, mis-wired.

    Anything else is foreign and is never clobbered: a real file, or a link into
    another tool's hook.
    """
    if not link.is_symlink():
        return False
    if not link.exists():  # exists() follows the link — False here means dangling
        return True
    try:
        return link.resolve().parent == hooks_root.resolve()
    except OSError:
        return False


def _install_hooks(hooks_dir: Path, sources: dict[str, str], label: str,
                   check: bool, results: list[tuple[str, str]]) -> list[str]:
    """Symlink each tracked hook into ``hooks_dir``; never clobber a foreign one.

    Returns one line per hook that is NOT wired to its tracked source once this
    returns — the input to the non-zero ``--check`` exit.
    """
    hooks_root = REPO_ROOT / HOOKS_SRC_DIR
    unwired: list[str] = []
    for name, source in sources.items():
        src = hooks_root / source
        if not src.is_file():
            results.append((SKIP, f"{HOOKS_SRC_DIR}/{source} not present — skipping"))
            continue
        link = hooks_dir / name
        repairable = _hook_is_repairable(link, hooks_root)
        status, msg, target = _plan_symlink(
            link, src, allow_replace_symlink=repairable)
        if status == UPDATE:
            msg += " — broken install of ours; git was running no hook here"
        results.append((status, f"[{label}] {msg}"))
        if status in (CREATE, UPDATE):
            if check:
                unwired.append(f"[{label}] {_disp(link)} is not wired to "
                               f"{HOOKS_SRC_DIR}/{source}")
            else:
                _apply_symlink(link, target, status)
        elif status == WARN:
            unwired.append(f"[{label}] {_disp(link)} is foreign, so "
                           f"{HOOKS_SRC_DIR}/{source} does not run here")
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


def _owned_private_skill_links() -> list[Path]:
    """Existing generated adapters whose targets point into overlay skills."""
    links: list[Path] = []
    for host in SKILL_HOSTS:
        host_dir = REPO_ROOT / host
        if not host_dir.is_dir():
            continue
        for entry in host_dir.iterdir():
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
        unwired_hooks += _install_hooks(
            hooks_dir, TOOLKIT_HOOKS, "toolkit", check, results)

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
            unwired_hooks += _install_hooks(
                overlay_hooks_dir, OVERLAY_HOOKS, "overlay", check, results)

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
    print("done." if not check else "check complete.")
    # An apply run repairs every hook it owns, so what is left is a foreign hook it
    # must not touch — a warning, not a failure it can act on. --check is a health
    # report: it fails whenever a hook that should be guarding this checkout is not.
    return 1 if (check and unwired_hooks) else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="report what would change and make no changes; exits 1 "
                             "when a tracked git hook is not wired to its source")
    args = parser.parse_args(argv)
    return bootstrap(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
