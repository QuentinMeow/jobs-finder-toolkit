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

``--check`` runs in BOTH directions. Outward: every declared copy still matches
its source. Inward (``undeclared_vendored_files``): every file sitting under a
``scripts/_vendor/`` root is declared somewhere here. Without the inward pass
the gate fails open — an undeclared copy is compared to nothing and drifts
forever while the check stays green.

Usage:
    # Regenerate every vendored copy from its canonical source
    .venv/bin/python automation/vendoring/sync_vendored.py

    # Verify only — exit 1 if any copy drifted (used by the pre-commit hook)
    .venv/bin/python automation/vendoring/sync_vendored.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

# automation/vendoring/sync_vendored.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Canonical SOURCE (relative to repo root) -> list of vendored COPY targets.
# Each copy is kept byte-identical to its source; the "generated, do not edit"
# notice lives in the copy's sibling _vendor/README.md.
TARGETS: dict[str, list[str]] = {
    "automation/shared/config.py": [
        "skills/resume-writer/scripts/_vendor/config.py",
        "skills/application-tracker/scripts/_vendor/config.py",
        "skills/job-search/scripts/_vendor/config.py",
        "skills/email-assistant/scripts/_vendor/config.py",
        "skills/behavioral-interview-prep/scripts/_vendor/config.py",
    ],
    # layout.py rides along with config.py everywhere: config imports it, so a
    # skill that vendors one and not the other cannot import config at all.
    "automation/shared/layout.py": [
        "skills/resume-writer/scripts/_vendor/layout.py",
        "skills/application-tracker/scripts/_vendor/layout.py",
        "skills/job-search/scripts/_vendor/layout.py",
        "skills/email-assistant/scripts/_vendor/layout.py",
        "skills/behavioral-interview-prep/scripts/_vendor/layout.py",
    ],
    "automation/shared/location.py": [
        "skills/resume-writer/scripts/_vendor/location.py",
        "skills/application-tracker/scripts/_vendor/location.py",
        "skills/job-search/scripts/_vendor/location.py",
    ],
    # ONE copy, on purpose. The profile's '## Skills' vocabulary is read by the
    # resume-writer's check.py / build_tailoring_card.py (this copy) and by
    # automation/gardener/skill_drift.py (the canonical file, imported directly
    # as repo-root maintenance tooling). Those two carried separate regexes whose
    # section boundaries had drifted apart; no other skill parses the profile.
    "automation/shared/profile_skills.py": [
        "skills/resume-writer/scripts/_vendor/profile_skills.py",
    ],
    "automation/shared/job_metadata.py": [
        "skills/resume-writer/scripts/_vendor/job_metadata.py",
        "skills/application-tracker/scripts/_vendor/job_metadata.py",
        "skills/job-search/scripts/_vendor/job_metadata.py",
    ],
    "automation/shared/metadata_editor.py": [
        "skills/application-tracker/scripts/_vendor/metadata_editor.py",
        "skills/job-search/scripts/_vendor/metadata_editor.py",
    ],
    "automation/shared/calendar_todos.py": [
        "skills/application-tracker/scripts/_vendor/calendar_todos.py",
    ],
    "automation/shared/skip_log.py": [
        "skills/application-tracker/scripts/_vendor/skip_log.py",
        "skills/job-search/scripts/_vendor/skip_log.py",
    ],
    # ONE copy, on purpose. Only the tracker's --company-keys report resolves a
    # company key; job_metadata restates the key REGEX instead of importing this
    # module (see its _COMPANY_KEY_RE comment), so resume-writer and job-search
    # need no copy and do not get one.
    "automation/shared/company_index.py": [
        "skills/application-tracker/scripts/_vendor/company_index.py",
    ],
}

# Canonical SOURCE DIRECTORY -> list of vendored COPY directory targets. Each copy
# is kept byte-identical PER FILE, and the drift check also fails on any file added
# to or removed from the source (not just content changes). ``__pycache__`` and
# compiled ``*.pyc`` artifacts are excluded from both copy and comparison.
DIR_TARGETS: dict[str, list[str]] = {
    "automation/shared/store": [
        "skills/job-search/scripts/_vendor/store",
        "skills/email-assistant/scripts/_vendor/store",
    ],
    # The send-less mail layer (contract + audited transport + isolated
    # providers + safety checker). The email-assistant skill consumes it only
    # through this vendored copy.
    "automation/shared/mail": [
        "skills/email-assistant/scripts/_vendor/mail",
    ],
}

# Files/dirs never vendored (build artifacts).
_EXCLUDE_DIRS = {"__pycache__"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}

# Where the reverse audit looks. Scoped to ``skills/`` on purpose: that is the
# only tree this manifest ever writes into, and a bare ``rglob("_vendor")``
# would sweep in unrelated third-party vendor dirs such as
# ``.venv/**/site-packages/pip/_vendor``.
_VENDOR_ROOT_GLOB = "skills/*/scripts/_vendor"

# The ONLY files allowed to sit directly in a ``scripts/_vendor/`` root without
# a ``TARGETS`` entry. Exempt by exact NAME AND POSITION, never by glob or
# suffix, so the same names deeper in the tree — where they would mean a file
# added to or removed from a ``DIR_TARGETS`` mirror — still fail the audit.
#   README.md    Documentation, not vendored code: the "generated, do not edit"
#                notice pointing a reader at this script. It is hand-written per
#                skill and has no canonical source to be byte-identical to.
#   __init__.py  Package marker, not vendored code: it makes ``_vendor`` an
#                importable package for that skill's own scripts. Structure.
# Matches the rule already stated in docs/handbook/skills-and-vendoring.md:
# "Everything in _vendor/ except __init__.py/README.md is generated".
_VENDOR_ROOT_EXEMPT = frozenset({"README.md", "__init__.py"})


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


def undeclared_vendored_files(
    repo_root: Path = REPO_ROOT,
    targets: dict[str, list[str]] | None = None,
    dir_targets: dict[str, list[str]] | None = None,
) -> list[str]:
    """Reverse audit: repo-relative files under a vendor root that nobody declared.

    Everything else in this module walks the manifest OUTWARD — for each
    declared target, does the copy still match its source? That direction alone
    is a gate that fails open: a module copied into
    ``skills/<skill>/scripts/_vendor/`` and never added to ``TARGETS`` is
    compared against nothing, so the check stays green forever while the copy
    rots away from ``automation/shared/``. This walks the tree INWARD instead
    and asks whether every file present is accounted for.

    A file is accounted for when it is a declared ``TARGETS`` copy, sits inside
    a declared ``DIR_TARGETS`` tree, or is one of the ``_VENDOR_ROOT_EXEMPT``
    shapes. ``__pycache__``/``*.pyc`` build artifacts are skipped, as everywhere
    else here.

    The dict arguments exist so tests can drive the audit over a synthetic tree
    with a synthetic manifest; production callers pass neither.
    """
    targets = TARGETS if targets is None else targets
    dir_targets = DIR_TARGETS if dir_targets is None else dir_targets
    declared_files = {dst for dsts in targets.values() for dst in dsts}
    declared_trees = tuple(f"{dst.rstrip('/')}/"
                           for dsts in dir_targets.values() for dst in dsts)

    undeclared: list[str] = []
    for vendor_root in sorted(repo_root.glob(_VENDOR_ROOT_GLOB)):
        if not vendor_root.is_dir():
            continue
        for rel, path in sorted(_dir_files(vendor_root).items()):
            if "/" not in rel and rel in _VENDOR_ROOT_EXEMPT:
                continue
            repo_rel = path.relative_to(repo_root).as_posix()
            if repo_rel in declared_files:
                continue
            if any(repo_rel.startswith(tree) for tree in declared_trees):
                continue
            undeclared.append(repo_rel)
    return undeclared


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

    undeclared = undeclared_vendored_files()

    for src, dst in drift:
        print(f"OUT OF SYNC: {dst} != {src}", file=sys.stderr)
    for reason in dir_drift:
        print(f"OUT OF SYNC: {reason}", file=sys.stderr)
    if drift or dir_drift:
        print("Run: .venv/bin/python automation/vendoring/sync_vendored.py",
              file=sys.stderr)

    for path in undeclared:
        print(f"UNDECLARED VENDORED FILE: {path}", file=sys.stderr)
    if undeclared:
        print(
            "Nothing in automation/vendoring/sync_vendored.py names the file(s) "
            "above, so this check compares them to no canonical source and they "
            "drift silently. Fix EACH one: either declare it — add its canonical "
            "source -> this path to TARGETS (or its directory to DIR_TARGETS) in "
            "automation/vendoring/sync_vendored.py, then re-run the script to "
            "regenerate it — or delete the file if nothing needs it. Re-running "
            "sync_vendored.py alone will NOT clear this.",
            file=sys.stderr)

    if drift or dir_drift or undeclared:
        return 1
    print("vendored copies in sync")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="verify only; exit 1 if any vendored copy drifted "
                             "or any file under a scripts/_vendor/ root is "
                             "undeclared")
    args = parser.parse_args()
    if args.check:
        return check()
    sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
