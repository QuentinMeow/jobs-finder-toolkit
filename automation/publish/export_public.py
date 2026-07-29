"""Allowlist-based exporter: produce a clean PUBLIC checkout of this toolkit.

This exporter seeded the public toolkit repo from the pre-split combined repo
(fresh, PII-free history) and remains useful post-split: the leak-guard test
suite drives it end-to-end, and it can produce a sanitized copy of any checkout
(e.g. one that still holds an in-place overlay). It copies ONLY known-public
paths (an explicit ALLOWLIST) into a fresh destination directory, applies a
denylist to scrub anything personal that slipped inside an allowlisted tree,
ships this repo's tracked ``.gitignore``, regenerates the ``.claude/skills`` /
``.cursor/skills`` compat symlinks for the PUBLIC skills, and (optionally)
``git init`` + runs the leak guard (``check_public.py``) before committing.

Design rules:
  * The ALLOWLIST wins: nothing is ever copied unless it lives under an
    allowlisted path. When in doubt, exclude.
  * The tree is enumerated through ``git ls-files``, never ``os.walk``: only
    TRACKED files can ship. A scratch file, a scraped JD, or a personal profile
    symlink dropped into an allowlisted directory is git-ignored/untracked and
    therefore invisible to the export by construction.
  * An allowlisted path that resolves to nothing is REPORTED, never silently
    skipped — a renamed or typo'd entry used to ship zero files and say nothing.
    ``--strict`` turns those warnings into a refusal, before ``--force`` touches
    the destination.
  * Which ``skills/<name>`` trees ship is DERIVED from each SKILL.md's
    ``visibility:`` frontmatter (``sync_skill_manifests``), never restated here.
  * The DENYLIST is applied AFTER the allowlist, per file: ``__pycache__``,
    ``*.pyc``, ``.DS_Store``, the owner's personal job-search profiles, and any
    file whose PATH or (text) CONTENT trips the personal-identity token screen
    shared with ``check_public.py``.
  * The leak guard is the final gate under ``--git-init``: if it FAILS the export
    is NOT committed and the exporter exits nonzero.

Usage:
    .venv/bin/python automation/publish/export_public.py --dest <dir> [--git-init] [--force] [--strict]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Make the sibling leak guard importable so we reuse ONE source of truth for the
# personal-identity token list and the binary/text helpers, and the sibling
# manifest module so the PUBLIC skill list is derived from SKILL.md frontmatter
# instead of restated here (they disagreed for months; search-recall-audit
# existed but had never shipped).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_public  # noqa: E402
import sync_skill_manifests  # noqa: E402

# automation/publish/export_public.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Allowlisted individual files (repo-root-relative). Must be TRACKED.
ALLOWLIST_FILES = [
    "AGENTS.md",
    # The root shim that makes Claude Code load AGENTS.md (a one-line @-import).
    # Without it a fresh public clone silently boots with no agent contract.
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "config.example.yaml",
    # The one-shot "make my checkout work" step README.md / CONTRIBUTING.md /
    # handbook/private-overlay.md all tell a new user to run.
    "automation/bootstrap_overlay.py",
]

# Allowlisted directory trees (every TRACKED file under them, denylist-filtered).
# The public skills are appended at call time by ``allowlist_dirs()`` — see
# ``public_skills()``.
ALLOWLIST_DIRS = [
    "examples",
    "automation/shared",
    "automation/vendoring",
    "automation/maintenance",
    "automation/metrics",
    "automation/publish",
    "automation/store",
    "evals",
    "automation/hooks",
    "automation/reconcile",
    "templates",
    ".github",
    ".claude-plugin",
    "handbook",
    "design",
]


def public_skills() -> list[str]:
    """The PUBLIC skills that ship, from ``skills/*/SKILL.md`` frontmatter."""
    return sync_skill_manifests.public_skills(REPO_ROOT)


def allowlist_dirs() -> list[str]:
    """Allowlisted trees + one ``skills/<name>`` entry per PUBLIC skill."""
    return ALLOWLIST_DIRS + [f"skills/{skill}" for skill in public_skills()]

# The job-search profiles folder is allowlisted, but only these generic profile
# files are PUBLIC. Any OTHER file directly under it is a personal profile and is
# kept OUT — expressed as an allowlist so this exporter never has to spell out (and
# therefore never carries) an owner's personal filename/token.
PROFILES_DIR = "skills/job-search/profiles"
PUBLIC_PROFILE_FILES = {"example.yaml", "_TEMPLATE.yaml", "README.md"}

# Files exempt from the token-CONTENT screen because they legitimately carry the
# personal-token list itself (the leak-guard config). Their PATHS are still
# screened. Mirrors ``check_public.GUARD_REL_PATH`` so the guard we ship is copied
# even though it embeds the token list; every other file (this exporter included)
# must be token-free so both the exporter and the guard agree.
TOKEN_CONTENT_EXEMPT = {check_public.GUARD_REL_PATH}

# The public .gitignore shipped into <dest> is this repo's OWN tracked ``.gitignore``
# — a single source of truth, so the exported mirror and this checkout can never
# drift. (The tracked file already contains only public/overlay-continuity rules.)
GITIGNORE_REL = ".gitignore"


def _deny_reason(rel: str, tokens: list[str]) -> str | None:
    """Return why ``rel`` (repo-root-relative, posix) is excluded, or None.

    Applied AFTER the allowlist. Order: mechanical junk -> per-skill
    references_private -> explicit personal profiles -> personal-identity token in
    PATH -> personal-identity token in CONTENT (text files scanned line by line;
    document binaries have their extracted text/metadata scanned; the guard file
    is content-exempt).
    """
    parts = Path(rel).parts
    name = parts[-1]

    if name == ".DS_Store":
        return "junk:.DS_Store"
    if name.endswith(".pyc"):
        return "junk:*.pyc"
    if "__pycache__" in parts:
        return "junk:__pycache__"
    if "references_private" in parts:
        return "references_private"
    if rel.startswith(PROFILES_DIR + "/") and name not in PUBLIC_PROFILE_FILES:
        return "personal-profile"

    rel_lower = rel.lower()
    for tok in tokens:
        if tok.lower() in rel_lower:
            return f"token-in-path:{tok!r}"

    if rel not in TOKEN_CONTENT_EXEMPT:
        suffix = Path(rel).suffix.lower()
        if suffix in check_public.BINARY_EXTENSIONS:
            blob = check_public._binary_text(REPO_ROOT / rel, suffix)
            if blob is not None:
                blob_lower = blob.lower()
                for tok in tokens:
                    if tok.lower() in blob_lower:
                        return f"token-in-binary:{tok!r}"
        else:
            lines = check_public._read_text(REPO_ROOT / rel)
            if lines is not None:
                for lineno, line in enumerate(lines, start=1):
                    line_lower = line.lower()
                    for tok in tokens:
                        if tok.lower() in line_lower:
                            return f"token-in-content:{tok!r}@L{lineno}"
    return None


def _copy_one(rel: str, dest_root: Path, copied: list[str],
              skipped: list[tuple[str, str]], tokens: list[str]) -> None:
    reason = _deny_reason(rel, tokens)
    if reason is not None:
        skipped.append((rel, reason))
        return
    src = REPO_ROOT / rel
    dst = dest_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(rel)


def tracked_files() -> list[str]:
    """Every TRACKED path in this checkout (repo-root-relative, posix, sorted).

    ``git ls-files`` — not ``os.walk`` — is the enumerator, so an untracked file
    sitting inside an allowlisted directory can never be exported. That closes
    the hole that used to ship scratch files and the owner's personal job-search
    profile symlinks (git-ignored, but on disk and inside an allowlisted tree).
    """
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed in {REPO_ROOT} (exit {proc.returncode}): "
            f"{proc.stderr.strip()}\nThe exporter enumerates TRACKED files, so it "
            "must run inside a git checkout."
        )
    return sorted(p for p in proc.stdout.split("\0") if p)


def _tracked_under(rel_dir: str, tracked: list[str]) -> list[str]:
    prefix = rel_dir.rstrip("/") + "/"
    return [p for p in tracked if p.startswith(prefix)]


def preflight(tracked: list[str]) -> list[str]:
    """Warn about every allowlisted path that would contribute nothing.

    A renamed or misspelled allowlist entry used to export zero files in total
    silence. Each of these is a warning by default and a refusal under
    ``--strict``. Run BEFORE the destination is touched so a strict refusal
    costs the caller nothing (same rule as the arming gate).
    """
    warnings: list[str] = []
    tracked_set = set(tracked)
    for rel in ALLOWLIST_FILES:
        if rel not in tracked_set:
            reason = "not tracked by git" if (REPO_ROOT / rel).exists() else "does not exist"
            warnings.append(f"allowlisted file contributes nothing: {rel} ({reason})")
    for rel_dir in allowlist_dirs():
        if not (REPO_ROOT / rel_dir).is_dir():
            warnings.append(f"allowlisted directory does not exist: {rel_dir}")
        elif not _tracked_under(rel_dir, tracked):
            warnings.append(f"allowlisted directory holds no tracked files: {rel_dir}")
    return warnings


def _copy_tree(rel_dir: str, dest_root: Path, copied: list[str],
               skipped: list[tuple[str, str]], tokens: list[str],
               tracked: list[str]) -> None:
    """Copy every TRACKED file under ``rel_dir`` (denylist applied per file).

    Symlinks are followed (``shutil.copy2``), matching the previous behaviour:
    git stores a symlink as a blob holding its target, but the export wants the
    CONTENT (e.g. the tracked ``design/CLAUDE.md -> AGENTS.md`` shim must be a
    real file in a checkout that may not support symlinks). A tracked path whose
    worktree file is missing is skipped with a reason rather than crashing.
    """
    for rel in _tracked_under(rel_dir, tracked):
        if not (REPO_ROOT / rel).exists():
            skipped.append((rel, "tracked but missing from the worktree"))
            continue
        _copy_one(rel, dest_root, copied, skipped, tokens)


def _regenerate_symlinks(dest_root: Path, skills: list[str]) -> list[str]:
    """Recreate .claude/skills + .cursor/skills compat symlinks for PUBLIC skills.

    Mirrors the source checkout: ``<host>/<skill> -> ../../skills/<skill>``. The
    trees are REGENERATED rather than copied, because git records a symlink as a
    blob holding its target and the source trees may also hold links for skills
    that are not part of this repo. ``skills`` comes from the SKILL.md
    frontmatter, so the private coding-interview skills are excluded by
    construction rather than by a hand-maintained exception.
    """
    created: list[str] = []
    for host in sync_skill_manifests.SYMLINK_HOSTS:
        base = dest_root / host
        base.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            link = base / skill
            target = f"{sync_skill_manifests.SYMLINK_TARGET_PREFIX}{skill}"
            if link.is_symlink() or link.exists():
                link.unlink()
            os.symlink(target, link)
            created.append(f"{host}/{skill} -> {target}")
    return created


def _run_guard(dest_root: Path, tokens: list[str]) -> int:
    """git init + add -A in <dest>, then run the leak guard against the copied tree.

    The guard enumerates TRACKED files, so we initialize a repo + stage everything
    first (independent of whether we will commit). The freshly copied tree has no
    ``config.yaml`` of its own, so we forward the resolved REAL token set via
    ``JOBHUNT_PERSONAL_TOKENS`` — otherwise the guard (falling back to the fictional
    example identity) would screen against no real tokens. Returns the guard's exit
    code (0 = clean).
    """
    subprocess.run(["git", "init"], cwd=dest_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "-A"], cwd=dest_root, check=True, capture_output=True, text=True)

    env = dict(os.environ)
    env[check_public.TOKENS_ENV_VAR] = "\n".join(tokens)
    # Keep the freshly copied tree byte-for-byte what the allowlist produced: the
    # guard imports sibling/shared modules, and CPython would otherwise leave
    # __pycache__/*.pyc behind INSIDE the export (git-ignored, so invisible to the
    # guard's tracked-file scan, but still not something an export should carry).
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    print("\n=== Leak guard (check_public.py) ===")
    guard = subprocess.run(
        [sys.executable, "automation/publish/check_public.py"],
        cwd=dest_root,
        capture_output=True,
        text=True,
        env=env,
    )
    if guard.stdout:
        print(guard.stdout, end="" if guard.stdout.endswith("\n") else "\n")
    if guard.stderr:
        print(guard.stderr, end="", file=sys.stderr)
    return guard.returncode


def _commit(dest_root: Path) -> int:
    """Commit the (already staged) export. Returns the git exit code."""
    commit = subprocess.run(
        ["git", "commit", "-m", "Initial public release of the job-hunting toolkit"],
        cwd=dest_root,
        capture_output=True,
        text=True,
    )
    if commit.stdout:
        print(commit.stdout, end="" if commit.stdout.endswith("\n") else "\n")
    if commit.returncode != 0:
        if commit.stderr:
            print(commit.stderr, end="", file=sys.stderr)
        print(f"git commit failed (exit {commit.returncode}).")
    return commit.returncode


def _print_manifest(dest_root: Path, copied: list[str], skipped: list[tuple[str, str]],
                    symlinks: list[str]) -> None:
    top_level = sorted(p.name for p in dest_root.iterdir())
    print("=== Public export manifest ===")
    print(f"  destination:   {dest_root}")
    print(f"  files copied:  {len(copied)}")
    print(f"  files skipped: {len(skipped)} (denylist)")
    print(f"  symlinks:      {len(symlinks)}")
    print(f"  top-level entries ({len(top_level)}):")
    for name in top_level:
        marker = "/" if (dest_root / name).is_dir() and not (dest_root / name).is_symlink() else ""
        print(f"    - {name}{marker}")
    if skipped:
        print("  skipped (denylist):")
        for rel, reason in skipped:
            print(f"    - {rel}  [{reason}]")


def export(dest: Path, git_init: bool, force: bool, strict: bool = False) -> int:
    # Refuse to export from an UNARMED checkout. FIRST — before --force deletes
    # the destination — so a refusal costs the caller nothing.
    #
    # The guard we run against the copied tree is armed through
    # ``JOBHUNT_PERSONAL_TOKENS``, which we set from the UNION below. A checkout
    # holding private/leak_tokens.txt but no real config.yaml therefore forwards a
    # NON-EMPTY set, so that guard run would look armed while knowing none of the
    # owner's name, email, or handles — the export's final gate would pass without
    # ever screening for the identity. Gate on the identity set, exactly as
    # ``check_public.main`` does.
    if not check_public.identity_tokens():
        print("error: refusing to export — the leak guard is UNARMED in this checkout.\n"
              "       Zero identity tokens resolved, so the export's final guard run would\n"
              "       screen against no real identity and report the tree safe to publish.",
              file=sys.stderr)
        for line in check_public.unarmed_report():
            print(line, file=sys.stderr)
        print("       Export only from a maintainer checkout whose config.yaml carries the\n"
              f"       real candidate identity, or set ${check_public.TOKENS_ENV_VAR}.",
              file=sys.stderr)
        return 2

    # Enumerate TRACKED files once, then report every allowlist entry that
    # contributes nothing — also BEFORE --force deletes the destination, so a
    # --strict refusal costs the caller nothing.
    tracked = tracked_files()
    warnings = preflight(tracked)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if warnings and strict:
        print(f"error: refusing to export — {len(warnings)} allowlist warning(s) "
              "under --strict.\n"
              "       Fix or remove the allowlist entries above, or drop --strict.",
              file=sys.stderr)
        return 2

    dest = dest.resolve()
    if dest == REPO_ROOT or dest in REPO_ROOT.parents:
        print(f"error: refusing to export into the repo root or an ancestor: {dest}",
              file=sys.stderr)
        return 2
    if dest.exists():
        if not force:
            print(f"error: destination exists: {dest}\n"
                  "       pass --force to overwrite it.", file=sys.stderr)
            return 2
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    # Resolve the REAL personal-identity tokens once (from the source checkout's
    # config.yaml + private/leak_tokens.txt); used for the copy-time denylist AND
    # forwarded to the guard run against the copied tree.
    tokens = check_public.personal_tokens()

    copied: list[str] = []
    skipped: list[tuple[str, str]] = []
    tracked_set = set(tracked)

    for rel in ALLOWLIST_FILES:
        if rel in tracked_set and (REPO_ROOT / rel).is_file():
            _copy_one(rel, dest, copied, skipped, tokens)
    for rel_dir in allowlist_dirs():
        _copy_tree(rel_dir, dest, copied, skipped, tokens, tracked)

    (dest / ".gitignore").write_text(
        (REPO_ROOT / GITIGNORE_REL).read_text(encoding="utf-8"), encoding="utf-8")

    skills = public_skills()
    symlinks = _regenerate_symlinks(dest, skills)

    _print_manifest(dest, copied, skipped, symlinks)
    print(f"  public skills: {len(skills)} (skills/*/SKILL.md `visibility: public`)")
    print(f"  active tokens: {len(tokens)} (from config identity + overlay + env)")

    # The leak guard ALWAYS runs against the copied tree (it is the final gate) —
    # git_init only controls whether we also commit the clean export.
    rc = _run_guard(dest, tokens)
    if rc != 0:
        print("\nLEAK GUARD FAILED (exit "
              f"{rc}) — export NOT committed. Fix the violations above (genericize "
              "the offending file, move personal content into references_private/ or "
              "the overlay, or extend the token list) and re-run.")
        return rc

    print("Leak guard PASSED.")
    if not git_init:
        print("export committed: no (re-run with --git-init to commit the clean export)")
        return 0
    return _commit(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dest", required=True, help="destination directory for the public export")
    parser.add_argument("--git-init", action="store_true",
                        help="git init + add -A, run the leak guard, and commit only if it passes")
    parser.add_argument("--force", action="store_true",
                        help="overwrite --dest if it already exists")
    parser.add_argument("--strict", action="store_true",
                        help="refuse to export when any allowlisted path contributes "
                             "nothing (missing directory, untracked/absent file)")
    args = parser.parse_args(argv)
    return export(Path(args.dest), args.git_init, args.force, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
