"""Vendor pure shared modules into self-contained skills, and verify no drift.

Approach 2 (self-contained skills). A skill that must run standalone — outside
this repo, or in a no-network sandbox — may not import repo-root Python. Instead,
the pure module it needs has ONE canonical home in the repo toolkit and a
byte-identical COPY ("vendored") under that skill's own ``scripts/_vendor/``. This
script is the single tool that (re)generates those copies and checks they never
silently diverge from their source.

Canonical source -> vendored copy targets are declared in ``TARGETS`` below (paths
are relative to the repo root). Editing a shared module = edit the canonical file,
then run this script to regenerate the copies.

Usage:
    # Regenerate every vendored copy from its canonical source
    .venv/bin/python scripts/vendoring/sync_vendored.py

    # Verify only — exit 1 if any copy drifted (used by the pre-commit hook)
    .venv/bin/python scripts/vendoring/sync_vendored.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

# scripts/vendoring/sync_vendored.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Canonical SOURCE (relative to repo root) -> list of vendored COPY targets.
# Each copy is kept byte-identical to its source; the "generated, do not edit"
# notice lives in the copy's sibling _vendor/README.md.
TARGETS: dict[str, list[str]] = {
    "scripts/shared/config.py": [
        ".agents/skills/resume-writer/scripts/_vendor/config.py",
        ".agents/skills/application-tracker/scripts/_vendor/config.py",
        ".agents/skills/job-search/scripts/_vendor/config.py",
        ".agents/skills/outlook-email-assistant/scripts/_vendor/config.py",
    ],
    "scripts/shared/layout.py": [
        ".agents/skills/resume-writer/scripts/_vendor/layout.py",
        ".agents/skills/application-tracker/scripts/_vendor/layout.py",
        ".agents/skills/job-search/scripts/_vendor/layout.py",
        ".agents/skills/outlook-email-assistant/scripts/_vendor/layout.py",
    ],
    "scripts/shared/location.py": [
        ".agents/skills/resume-writer/scripts/_vendor/location.py",
        ".agents/skills/application-tracker/scripts/_vendor/location.py",
        ".agents/skills/job-search/scripts/_vendor/location.py",
    ],
    "scripts/shared/job_metadata.py": [
        ".agents/skills/resume-writer/scripts/_vendor/job_metadata.py",
        ".agents/skills/application-tracker/scripts/_vendor/job_metadata.py",
        ".agents/skills/job-search/scripts/_vendor/job_metadata.py",
    ],
    "scripts/shared/metadata_editor.py": [
        ".agents/skills/application-tracker/scripts/_vendor/metadata_editor.py",
        ".agents/skills/job-search/scripts/_vendor/metadata_editor.py",
    ],
}

# Canonical SOURCE DIRECTORY -> list of vendored COPY directory targets. Each copy
# is kept byte-identical PER FILE, and the drift check also fails on any file added
# to or removed from the source (not just content changes). ``__pycache__`` and
# compiled ``*.pyc`` artifacts are excluded from both copy and comparison.
DIR_TARGETS: dict[str, list[str]] = {
    "scripts/shared/store": [
        ".agents/skills/job-search/scripts/_vendor/store",
    ],
}

# Files/dirs never vendored (build artifacts).
_EXCLUDE_DIRS = {"__pycache__"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dir_files(root: Path) -> dict[str, Path]:
    """Map of ``relative-posix-path -> absolute Path`` for a vendored dir tree.

    Excludes ``__pycache__`` directories and compiled Python artifacts so the
    comparison is over source files only.
    """
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix in _EXCLUDE_SUFFIXES:
            continue
        out[path.relative_to(root).as_posix()] = path
    return out


def _sync_dir(src: str, dst: str) -> None:
    """Mirror a source directory into a vendored copy (byte-identical per file)."""
    src_root = REPO_ROOT / src
    dst_root = REPO_ROOT / dst
    src_files = _dir_files(src_root)
    dst_files = _dir_files(dst_root)
    # Remove vendored files that no longer exist in the source.
    for rel in sorted(set(dst_files) - set(src_files)):
        dst_files[rel].unlink()
    # Copy every source file over its target.
    for rel, spath in sorted(src_files.items()):
        target = dst_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(spath, target)
    # Prune now-empty directories under the target (keep the tree tidy).
    for path in sorted(dst_root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    print(f"vendored dir {src}/ -> {dst}/ ({len(src_files)} files)")


def sync() -> None:
    """Copy every canonical source over its vendored targets (byte-identical)."""
    for src, dsts in TARGETS.items():
        src_path = REPO_ROOT / src
        if not src_path.exists():
            print(f"ERROR: canonical source missing: {src}", file=sys.stderr)
            raise SystemExit(2)
        for dst in dsts:
            dst_path = REPO_ROOT / dst
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_path, dst_path)
            print(f"vendored {src} -> {dst}")
    for src, dsts in DIR_TARGETS.items():
        src_path = REPO_ROOT / src
        if not src_path.is_dir():
            print(f"ERROR: canonical source dir missing: {src}", file=sys.stderr)
            raise SystemExit(2)
        for dst in dsts:
            _sync_dir(src, dst)


def _check_dir(src: str, dst: str) -> list[str]:
    """Return human-readable drift reasons for one vendored dir target (empty=OK)."""
    src_files = _dir_files(REPO_ROOT / src)
    dst_files = _dir_files(REPO_ROOT / dst)
    reasons: list[str] = []
    for rel in sorted(set(src_files) - set(dst_files)):
        reasons.append(f"{dst}/{rel} missing (added in source)")
    for rel in sorted(set(dst_files) - set(src_files)):
        reasons.append(f"{dst}/{rel} stale (removed from source)")
    for rel in sorted(set(src_files) & set(dst_files)):
        if _digest(src_files[rel]) != _digest(dst_files[rel]):
            reasons.append(f"{dst}/{rel} != {src}/{rel}")
    return reasons


def check() -> int:
    """Return 0 if every vendored copy matches its source, else 1 (with report)."""
    drift: list[tuple[str, str]] = []
    for src, dsts in TARGETS.items():
        src_path = REPO_ROOT / src
        if not src_path.exists():
            print(f"OUT OF SYNC: canonical source missing: {src}", file=sys.stderr)
            drift.append((src, "<missing source>"))
            continue
        for dst in dsts:
            dst_path = REPO_ROOT / dst
            if not dst_path.exists() or _digest(src_path) != _digest(dst_path):
                drift.append((src, dst))

    dir_drift: list[str] = []
    for src, dsts in DIR_TARGETS.items():
        src_path = REPO_ROOT / src
        if not src_path.is_dir():
            print(f"OUT OF SYNC: canonical source dir missing: {src}", file=sys.stderr)
            dir_drift.append(f"{src} <missing source dir>")
            continue
        for dst in dsts:
            dir_drift.extend(_check_dir(src, dst))

    for src, dst in drift:
        print(f"OUT OF SYNC: {dst} != {src}", file=sys.stderr)
    for reason in dir_drift:
        print(f"OUT OF SYNC: {reason}", file=sys.stderr)
    if drift or dir_drift:
        print("Run: .venv/bin/python scripts/vendoring/sync_vendored.py",
              file=sys.stderr)
        return 1
    print("vendored copies in sync")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="verify only; exit 1 if any vendored copy drifted")
    args = parser.parse_args()
    if args.check:
        return check()
    sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
