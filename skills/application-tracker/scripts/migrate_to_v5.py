"""Migrate application meta.yaml files from schema v4 to schema v5.

Schema v5 replaces the retired free-text per-job ``stage`` with the structured
``jobs[].progress`` summary ({phase, state, label?, calendar_item?,
updated_at?, source?}). The mapping is deterministic and never guesses
(design/application-progress-calendar §6):

- ``drafted``      -> phase ``application_prep``,   state ``action_required``
- ``applied``      -> phase ``application_review``, state ``waiting_employer``
- ``in_progress``  -> phase from a recognized legacy stage (else ``other``),
                      state ``unknown``; the exact old stage text becomes
                      ``label`` (the status literal when the stage was empty)
- ``rejected``     -> state ``closed``; phase from the stage, else
                      ``application_review``
- ``ignored``      -> state ``closed``; phase from the stage, else
                      ``application_prep``

No migration invents a calendar time, timezone, email source, or completion
event. The edit is formatting-preserving (comments, quoting, blank lines, and
newline style survive) and fails closed per file: a file that cannot retain
its existing facts is reported and left untouched.

DRY-RUN BY DEFAULT — the preview prints a unified diff per file. Re-run with
``--write`` to persist the checksum-guarded atomic writes. After the fleet is
converted, v5 is the only schema the validators accept.

Usage:
    .venv/bin/python skills/application-tracker/scripts/migrate_to_v5.py            # fleet preview
    .venv/bin/python skills/application-tracker/scripts/migrate_to_v5.py --write    # apply
    .venv/bin/python skills/application-tracker/scripts/migrate_to_v5.py --slug <slug-or-path>
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

# Self-contained skill: import only from this folder and its _vendor/ copies.
_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE / "_vendor"):
    if str(_path) not in sys.path and _path.is_dir():
        sys.path.insert(0, str(_path))

import config
from layout import STATUS_DIRS, application_dir
from metadata_editor import atomic_write_bytes, plan_v4_to_v5_migration


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
    """Plan (and optionally apply) the v4 -> v5 migration for one application."""
    meta_path = app_dir / "meta.yaml"
    result = {
        "slug": app_dir.name,
        "path": str(meta_path),
        "changed": False,
        "written": False,
        "error": "",
        "diff": "",
    }
    if not meta_path.is_file():
        result["error"] = "meta.yaml not found"
        return result
    raw = meta_path.read_bytes()
    plan = plan_v4_to_v5_migration(raw)
    if plan.errors:
        result["error"] = "; ".join(plan.errors)
        return result
    result["changed"] = plan.changed
    if plan.changed:
        result["diff"] = "".join(difflib.unified_diff(
            raw.decode("utf-8").splitlines(keepends=True),
            plan.output_bytes.decode("utf-8").splitlines(keepends=True),
            fromfile=f"{app_dir.name}/meta.yaml (v4)",
            tofile=f"{app_dir.name}/meta.yaml (v5)",
        ))
        if write:
            atomic_write_bytes(meta_path, plan.output_bytes,
                               expected_sha256=plan.before_sha256)
            result["written"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", default="",
                        help="Migrate one application (slug or folder path) "
                             "instead of the whole fleet.")
    parser.add_argument("--write", action="store_true",
                        help="Persist the migration. Without this flag the "
                             "command is a dry-run preview.")
    parser.add_argument("--quiet-diff", action="store_true",
                        help="Suppress the per-file unified diffs (summary only).")
    args = parser.parse_args()

    try:
        rows = [migrate_application(app_dir, write=args.write)
                for app_dir in _applications(args.slug)]
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    mode = "WRITE" if args.write else "DRY RUN"
    print(f"meta.yaml v4 -> v5 migration ({mode})")
    changed = [row for row in rows if row["changed"]]
    failures = [row for row in rows if row["error"]]
    for row in rows:
        if row["error"]:
            print(f"ERROR        {row['slug']}: {row['error']}")
        elif row["changed"]:
            action = "migrated" if row["written"] else "would migrate"
            print(f"{action:<12} {row['slug']}")
            if row["diff"] and not args.quiet_diff:
                print(row["diff"], end="")
    print(f"Scanned {len(rows)} applications; {len(changed)} "
          f"{'migrated' if args.write else 'would migrate'}; "
          f"{len(failures)} need manual attention.")
    if changed and not args.write:
        print("No files written. Re-run with --write after reviewing the diffs.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
