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
  * The DENYLIST is applied AFTER the allowlist, per file: ``__pycache__``,
    ``*.pyc``, ``.DS_Store``, the owner's personal job-search profiles, and any
    file whose PATH or (text) CONTENT trips the personal-identity token screen
    shared with ``check_public.py``.
  * The leak guard is the final gate under ``--git-init``: if it FAILS the export
    is NOT committed and the exporter exits nonzero.

Usage:
    .venv/bin/python scripts/publish/export_public.py --dest <dir> [--git-init] [--force]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Make the sibling leak guard importable so we reuse ONE source of truth for the
# personal-identity token list and the binary/text helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_public  # noqa: E402

# scripts/publish/export_public.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# The PUBLIC skills that ship in the toolkit (coding-interview is PRIVATE).
PUBLIC_SKILLS = [
    "ask-me-anything",
    "job-search",
    "resume-writer",
    "application-tracker",
    "behavioral-interview-prep",
    "company-research",
    "gardener",
]

# Allowlisted individual files (repo-root-relative). Copied only if present.
ALLOWLIST_FILES = [
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "config.example.yaml",
]

# Allowlisted directory trees (copied recursively, then denylist-filtered).
# Copied only if present.
ALLOWLIST_DIRS = [
    "examples",
    "scripts/shared",
    "scripts/vendoring",
    "scripts/maintenance",
    "scripts/metrics",
    "scripts/publish",
    "evals",
    "hooks",
    ".github",
    ".claude-plugin",
    "docs",
] + [f".agents/skills/{skill}" for skill in PUBLIC_SKILLS]

# The job-search profiles folder is allowlisted, but only these generic profile
# files are PUBLIC. Any OTHER file directly under it is a personal profile and is
# kept OUT — expressed as an allowlist so this exporter never has to spell out (and
# therefore never carries) an owner's personal filename/token.
PROFILES_DIR = ".agents/skills/job-search/profiles"
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


def _copy_tree(rel_dir: str, dest_root: Path, copied: list[str],
               skipped: list[tuple[str, str]], tokens: list[str]) -> None:
    src_dir = REPO_ROOT / rel_dir
    if not src_dir.is_dir():
        return
    for root, dirs, files in os.walk(src_dir):
        # Prune junk + per-skill private references so we never descend into them.
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "references_private")]
        for fname in files:
            abs_path = Path(root) / fname
            rel = abs_path.relative_to(REPO_ROOT).as_posix()
            _copy_one(rel, dest_root, copied, skipped, tokens)


def _regenerate_symlinks(dest_root: Path) -> list[str]:
    """Recreate .claude/skills + .cursor/skills compat symlinks for PUBLIC skills.

    Mirrors the source checkout: ``<host>/<skill> -> ../../.agents/skills/<skill>``.
    coding-interview (PRIVATE) is intentionally skipped.
    """
    created: list[str] = []
    for host in (".claude/skills", ".cursor/skills"):
        base = dest_root / host
        base.mkdir(parents=True, exist_ok=True)
        for skill in PUBLIC_SKILLS:
            link = base / skill
            target = f"../../.agents/skills/{skill}"
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

    print("\n=== Leak guard (check_public.py) ===")
    guard = subprocess.run(
        [sys.executable, "scripts/publish/check_public.py"],
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


def export(dest: Path, git_init: bool, force: bool) -> int:
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

    for rel in ALLOWLIST_FILES:
        if (REPO_ROOT / rel).is_file():
            _copy_one(rel, dest, copied, skipped, tokens)
    for rel_dir in ALLOWLIST_DIRS:
        _copy_tree(rel_dir, dest, copied, skipped, tokens)

    (dest / ".gitignore").write_text(
        (REPO_ROOT / GITIGNORE_REL).read_text(encoding="utf-8"), encoding="utf-8")

    symlinks = _regenerate_symlinks(dest)

    _print_manifest(dest, copied, skipped, symlinks)
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
    args = parser.parse_args(argv)
    return export(Path(args.dest), args.git_init, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
