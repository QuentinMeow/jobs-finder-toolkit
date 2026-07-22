"""Safely preview or insert schema-v4 job metadata into application meta.yaml files.

The default is a dry run. ``--write`` is required to persist targeted,
formatting-preserving edits. Every application carries a uniform ``jobs`` list
and each entry must name an existing ``jd_file``; positional or sorted-filename
fallbacks are deliberately forbidden.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE / "_vendor"):
    if str(_path) not in sys.path and _path.is_dir():
        sys.path.insert(0, str(_path))

import config
from job_metadata import analyze_job_metadata, load_company_levels
from layout import STATUS_DIRS, application_dir, source_dir
from metadata_editor import atomic_write_bytes, plan_metadata_edit


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


def _read_exact_jd(app_dir: Path, record: dict) -> str:
    """Read the exact JD file a jobs entry names (no positional fallback)."""
    named = str(record.get("jd_file") or "").strip()
    if not named:
        raise ValueError(
            f"role {record.get('role')!r} has no jd_file; "
            "schema-v4 metadata requires an exact JD association"
        )
    if Path(named).name != named:
        raise ValueError(f"jd_file must be a filename, not a path: {named!r}")
    candidates = [source_dir(app_dir) / named]
    if source_dir(app_dir) == app_dir:
        candidates.append(app_dir / named)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text()
    raise ValueError(
        f"role {record.get('role')!r} references missing jd_file {named!r}"
    )


def generated_metadata_by_path(app_dir: Path, meta: dict) -> dict[tuple, dict]:
    """Generate metadata for every posting using only exact JD associations.

    Schema v4 is uniform: every application carries a ``jobs`` list (one entry
    per posting), so there is no single-role top-level fallback.
    """
    reference = load_company_levels(config.company_levels_path())
    company = str(meta.get("company") or "")
    jobs = meta.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError(
            "schema-v4 metadata requires a non-empty jobs list (one entry per posting)"
        )
    generated = {}
    for index, record in enumerate(jobs):
        if not isinstance(record, dict):
            raise ValueError(f"jobs[{index}] must be a mapping")
        description = _read_exact_jd(app_dir, record)
        generated[("jobs", index)] = analyze_job_metadata(
            company=company,
            title=str(record.get("role") or ""),
            description=description,
            location=str(record.get("location") or ""),
            company_levels=reference,
        )
    return generated


def plan_application(target: str | Path):
    """Return ``(meta_path, plan)`` without writing."""
    app_dir = _resolve_target(target)
    meta_path = app_dir / "meta.yaml"
    if not meta_path.is_file():
        raise ValueError(f"meta.yaml not found: {meta_path}")
    raw = meta_path.read_bytes()
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"could not parse {meta_path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError(f"{meta_path} must contain a YAML mapping")
    generated = generated_metadata_by_path(app_dir, meta)
    return meta_path, plan_metadata_edit(raw, generated)


def process_application(target: str | Path, *, write: bool = False) -> dict:
    app_dir = _resolve_target(target)
    result = {
        "slug": app_dir.name,
        "path": str(app_dir / "meta.yaml"),
        "changed_fields": [],
        "written": False,
        "error": "",
    }
    try:
        meta_path, plan = plan_application(app_dir)
        if plan.errors:
            result["error"] = "; ".join(plan.errors)
            return result
        result["changed_fields"] = [
            _path_text(path) for path in plan.changed_field_paths
        ]
        if write and plan.changed:
            atomic_write_bytes(
                meta_path,
                plan.output_bytes,
                expected_sha256=plan.before_sha256,
            )
            result["written"] = True
    except (OSError, RuntimeError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def _path_text(path: tuple) -> str:
    rendered = ""
    for part in path:
        rendered += f"[{part}]" if isinstance(part, int) \
            else ("." if rendered else "") + str(part)
    return rendered


def _applications(statuses: list[str], slug: str = ""):
    if slug:
        yield _resolve_target(slug)
        return
    root = config.applications_root()
    for status in statuses:
        folder = root / STATUS_DIRS[status]
        if not folder.is_dir():
            continue
        for app_dir in sorted(folder.iterdir()):
            if app_dir.is_dir() and not app_dir.name.startswith("."):
                yield app_dir


def run_backfill(
    statuses: list[str],
    *,
    slug: str = "",
    write: bool = False,
) -> list[dict]:
    return [
        process_application(app_dir, write=write)
        for app_dir in _applications(statuses, slug)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--statuses",
        default=None,
        help="Comma-separated status labels (default: all status folders — the "
             "fleet is uniformly schema v4). Options: "
             f"{', '.join(STATUS_DIRS)}.",
    )
    parser.add_argument("--slug", default="", help="Preview one application slug/path.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist verified edits. Without this flag the command is dry-run only.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args()

    statuses = (
        [value.strip() for value in args.statuses.split(",") if value.strip()]
        if args.statuses else list(STATUS_DIRS)
    )
    unknown = [value for value in statuses if value not in STATUS_DIRS]
    if unknown:
        parser.error(f"invalid status labels: {', '.join(unknown)}")

    try:
        rows = run_backfill(statuses, slug=args.slug, write=args.write)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    failures = [row for row in rows if row["error"]]
    changed = [row for row in rows if row["changed_fields"]]
    if args.json:
        print(json.dumps({
            "mode": "write" if args.write else "dry_run",
            "rows": rows,
            "changed": len(changed),
            "failures": len(failures),
        }, indent=2))
    else:
        print(f"Job metadata backfill ({'WRITE' if args.write else 'DRY RUN'})")
        for row in rows:
            if row["error"]:
                print(f"ERROR        {row['slug']}: {row['error']}")
            elif row["changed_fields"]:
                action = "updated" if row["written"] else "would update"
                print(
                    f"{action:<12} {row['slug']}: "
                    f"{', '.join(row['changed_fields'])}"
                )
        print(
            f"Scanned {len(rows)} applications; {len(changed)} "
            f"{'updated' if args.write else 'would change'}; "
            f"{len(failures)} need manual attention."
        )
        if changed and not args.write:
            print("No files written. Re-run with --write only after reviewing this preview.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
