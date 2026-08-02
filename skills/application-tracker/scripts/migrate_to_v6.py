"""Migrate application meta.yaml files from schema v5 to schema v6.

Schema v6 replaces the single ``jobs[].progress.calendar_item`` reference with
an optional ordered ``calendar_items`` list. A present scalar becomes a
one-element list, preserving the exact calendar ID; progress records without a
calendar reference remain without one. No migration invents, removes, or
reorders calendar facts.

The edit is formatting-preserving and fails closed per file. DRY-RUN BY
DEFAULT: preview prints a unified diff for every affected file. Re-run with
``--write`` to persist checksum-guarded atomic writes.

Usage:
    .venv/bin/python skills/application-tracker/scripts/migrate_to_v6.py
    .venv/bin/python skills/application-tracker/scripts/migrate_to_v6.py --write
    .venv/bin/python skills/application-tracker/scripts/migrate_to_v6.py --slug <slug-or-path>
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from pathlib import Path

# Self-contained skill: import only from this folder and its _vendor/ copies.
_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE / "_vendor"):
    if str(_path) not in sys.path and _path.is_dir():
        sys.path.insert(0, str(_path))

import config
from layout import STATUS_DIRS, application_dir
from metadata_editor import (
    MetadataChecksumMismatchError,
    atomic_write_bytes,
    plan_v5_to_v6_migration,
)


def _resolve_target(target: str | Path) -> Path:
    candidate = Path(target)
    if candidate.exists():
        return application_dir(candidate)
    root = config.applications_root()
    for folder in STATUS_DIRS.values():
        match = root / folder / str(target)
        if match.is_dir():
            return match
    raise ValueError(f"application not found: {target}")


def _applications(slug: str = ""):
    if slug:
        yield _resolve_target(slug)
        return
    root = config.applications_root()
    for folder in STATUS_DIRS.values():
        status_dir = root / folder
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            if app_dir.is_dir() and not app_dir.name.startswith("."):
                yield app_dir


def migrate_application(app_dir: Path, *, write: bool) -> dict:
    """Plan (and optionally apply) the v5 -> v6 migration for one application."""
    meta_path = app_dir / "meta.yaml"
    result = {
        "slug": app_dir.name,
        "path": str(meta_path),
        "changed": False,
        "written": False,
        "error": "",
        "diff": "",
        "_plan": None,
        "_pre_image": b"",
    }
    if not meta_path.is_file():
        result["error"] = "meta.yaml not found"
        return result
    raw = meta_path.read_bytes()
    plan = plan_v5_to_v6_migration(raw)
    if plan.errors:
        result["error"] = "; ".join(plan.errors)
        return result
    result["changed"] = plan.changed
    result["_plan"] = plan
    result["_pre_image"] = raw
    if plan.changed:
        result["diff"] = "".join(difflib.unified_diff(
            raw.decode("utf-8").splitlines(keepends=True),
            plan.output_bytes.decode("utf-8").splitlines(keepends=True),
            fromfile=f"{app_dir.name}/meta.yaml (v5)",
            tofile=f"{app_dir.name}/meta.yaml (v6)",
        ))
        if write:
            atomic_write_bytes(
                meta_path,
                plan.output_bytes,
                expected_sha256=plan.before_sha256,
            )
            result["written"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--slug",
        default="",
        help="Migrate one application (slug or folder path) instead of the fleet.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist the migration. Without this flag the command is a dry-run preview.",
    )
    parser.add_argument(
        "--quiet-diff",
        action="store_true",
        help="Suppress per-file unified diffs (summary only).",
    )
    args = parser.parse_args()

    try:
        rows = [
            migrate_application(app_dir, write=False)
            for app_dir in _applications(args.slug)
        ]
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    mode = "WRITE" if args.write else "DRY RUN"
    print(f"meta.yaml v5 -> v6 migration ({mode})")
    changed = [row for row in rows if row["changed"]]
    failures = [row for row in rows if row["error"]]
    if args.write and not failures:
        written: list[dict] = []
        try:
            for row in changed:
                plan = row["_plan"]
                atomic_write_bytes(
                    Path(row["path"]),
                    plan.output_bytes,
                    expected_sha256=plan.before_sha256,
                )
                row["written"] = True
                written.append(row)
        except (MetadataChecksumMismatchError, OSError) as exc:
            print(f"Error: migration write failed: {exc}; rolling back", file=sys.stderr)
            rollback_errors: list[str] = []
            for row in reversed(written):
                plan = row["_plan"]
                try:
                    atomic_write_bytes(
                        Path(row["path"]),
                        row["_pre_image"],
                        expected_sha256=hashlib.sha256(plan.output_bytes).hexdigest(),
                    )
                    row["written"] = False
                except (MetadataChecksumMismatchError, OSError) as rollback_exc:
                    rollback_errors.append(f"{row['slug']}: {rollback_exc}")
            for error in rollback_errors:
                print(f"  rollback failed: {error}", file=sys.stderr)
            return 1
    for row in rows:
        if row["error"]:
            print(f"ERROR        {row['slug']}: {row['error']}")
        elif row["changed"]:
            action = "migrated" if row["written"] else "would migrate"
            print(f"{action:<12} {row['slug']}")
            if row["diff"] and not args.quiet_diff:
                print(row["diff"], end="")
    completed = sum(bool(row["written"]) for row in changed) if args.write else len(changed)
    print(
        f"Scanned {len(rows)} applications; {completed} "
        f"{'migrated' if args.write else 'would migrate'}; "
        f"{len(failures)} need manual attention."
    )
    if changed and not args.write:
        print("No files written. Re-run with --write after reviewing the diffs.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
