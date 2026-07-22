"""Scan applications/ status folders and print a summary table.

The per-job `status` field in each meta.yaml (drafted|applied|in_progress|rejected|
ignored) is the fine-grained source of truth; the overall status — the folder an
application lives in — is the DERIVED ROLLUP of its jobs' statuses (precedence
in_progress > applied > drafted > rejected > ignored). The physical folders are
numbered so a file browser lists the whole applications/ tree in a stable order; the
bare status LABEL stays the user-facing name (STATUS_DIRS maps label -> on-disk
folder):

    applications/6_drafted/<slug>/      -> drafted     (tailored, not yet submitted)
    applications/5_applied/<slug>/      -> applied      (submitted)
    applications/4_in_progress/<slug>/  -> in_progress  (heard back / interviewing)
    applications/3_rejected/<slug>/     -> rejected     (rejected at any stage)
    applications/2_ignored/<slug>/      -> ignored      (decided not to submit)

Scripts keep the two in sync: `--update` and `--update-job` write per-job `status`
in meta.yaml and then move the folder to match the recomputed rollup. `meta.yaml`
holds the rest of the metadata (company, dates, `channel` = how the lead was found,
referrer, next_action, notes; and per-posting role/workplace/sponsorship/level/YOE/
salary plus the structured per-job `progress` summary under `jobs:`).
Generation inputs (JD-<job-title>.md files, tailored.yaml, DOCX) live in each
folder's source/ subfolder; the final resume/cover-letter PDFs, the bundled
application .txt, and meta.yaml stay at the folder root. A single resume can target
several roles at one company: those applications carry a `jobs:` list in meta.yaml
and one JD-<job-title>.md file per posting. Non-application folders under
applications/ (0_profile/, 1_discoveries/) are skipped.

Schema v5 adds a structured per-job ``progress`` summary ({phase, state,
label?, calendar_item?}) and ONE private calendar/todo file resolved by
``config.calendar_path()``. This tracker is the only writer that updates
metadata and calendar together — transactionally, both or neither. Changing
only phase/state NEVER moves an application between status folders.

Usage:
    python skills/application-tracker/scripts/status.py
    python skills/application-tracker/scripts/status.py --json
    python skills/application-tracker/scripts/status.py --update google-ml-engineer-20260416 applied
    python skills/application-tracker/scripts/status.py --update-job <slug> "Backend Engineer" in_progress
    python skills/application-tracker/scripts/status.py --update-job <slug> 2 rejected
    python skills/application-tracker/scripts/status.py --update-progress <slug> <role-match> --phase technical_interview --state booking_required [--label TEXT]
    python skills/application-tracker/scripts/status.py --check-calendar
    python skills/application-tracker/scripts/status.py --sync-calendar [--write]
    python skills/application-tracker/scripts/status.py --enrich-metadata <slug>
    python skills/application-tracker/scripts/status.py --check-metadata
    python skills/application-tracker/scripts/status.py --sync-log
    python skills/application-tracker/scripts/status.py --log-search "Acme Corp" --outcome no_suitable [--date YYYY-MM-DD]
"""

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

# Self-contained skill: this script lives in the application-tracker skill's
# scripts/ folder alongside its _vendor/ copies of the pure toolkit modules. Put
# both the script folder and its _vendor/ on sys.path and import ONLY from those
# vendored modules (config, layout, location) — no check/cover_letter dependency.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

import config
from backfill_job_metadata import process_application
from calendar_todos import (
    CALENDAR_TEMPLATE,
    CHECKED_BOX_TRANSITIONS,
    STATE_SECTIONS,
    parse_calendar,
    plan_calendar_update,
    default_entry_text,
    generate_entry_id,
    record_cancellation,
    record_reschedule,
)
from job_metadata import (
    APPLICATION_SCHEMA_VERSION,
    PROGRESS_ACTION_STATES,
    PROGRESS_PHASES,
    PROGRESS_SCHEDULING_STATES,
    PROGRESS_STATES,
    PROGRESS_WAITING_STATES,
    default_progress_for_status,
    derive_status,
    validate_meta,
)
from layout import (
    STATUS_DIRS,
    STATUS_FOLDERS,
    application_dir,
    find_jd_files,
    source_dir,
    status_label_for_dir,
    tailored_path,
)
from location import assess_location, extract_jd_locations
from metadata_editor import (
    MetadataChecksumMismatchError,
    atomic_write_bytes,
    plan_field_updates,
)

# Output filename stems are candidate-identity-derived, so they come from config
# (kept under their historical module-level names for the file-presence globs).
RESUME_STEM = config.resume_stem()
APPLICATION_STEM = config.application_stem()


# Applications root comes from config (config.yaml holds the real path, so the
# scanned folders — and thus behavior — are unchanged).
APPLICATIONS_DIR = config.applications_root()

# STATUS_DIRS (label -> on-disk numbered folder) and STATUS_FOLDERS (labels in
# pipeline order) are the shared source of truth; they are imported from the
# vendored `layout` module. These are the only folders scanned as applications;
# anything else under applications/ (0_profile/, 1_discoveries/) is ignored.


def _status_dir(status: str) -> Path:
    """On-disk folder for a status label (e.g. 'applied' -> applications/5_applied)."""
    return APPLICATIONS_DIR / STATUS_DIRS[status]


def _resolve_statuses(args) -> list[str]:
    """Resolve the status scope shared by the metadata/location subcommands.

    Default scope is the full fleet (every status folder) — the whole fleet is
    uniformly schema v5. ``--statuses`` selects an explicit comma-separated subset.
    Exits non-zero on an unknown status label.
    """
    if args.statuses:
        statuses = [s.strip() for s in args.statuses.split(",") if s.strip()]
    else:
        statuses = list(STATUS_FOLDERS)
    unknown = [s for s in statuses if s not in STATUS_FOLDERS]
    if unknown:
        print(f"Error: invalid statuses: {', '.join(unknown)}", file=sys.stderr)
        sys.exit(1)
    return statuses


# The application log job-search reads to skip postings already generated/considered.
APPLICATIONS_LOG = APPLICATIONS_DIR / "0_profile" / "applications-log.yaml"
COMPANY_SEARCH_LOG = APPLICATIONS_DIR / "0_profile" / "company-search-log.yaml"

COMPANY_SEARCH_LOG_HEADER = (
    "# Auto-maintained log of the last SUCCESSFUL job search per company.\n"
    "# Successful search = queried ALL of a company's available jobs AND made an application\n"
    "# decision (created folder(s) OR decided no suitable role). Browsing-only or an\n"
    "# unreachable board does NOT count. job-search skips a company whose last successful\n"
    "# search is within `skip_within_days` (default 7) unless overridden.\n"
    "#\n"
    "# `created` rows are upserted by `skills/application-tracker/scripts/status.py --sync-log` from application\n"
    "# folders. Record `no_suitable` with `--log-search`. Re-run --sync-log after new drafts.\n\n"
)


def load_application(app_dir: Path, status: str) -> dict | None:
    """Load application metadata from a folder; status comes from the parent folder."""
    meta = app_dir / "meta.yaml"

    info = {
        "slug": app_dir.name,
        "company": "",
        "role": "",
        "date": "",
        "status": status,
        "channel": "",
        "referrer": "",
        "next_action": "",
        "has_jd": bool(find_jd_files(app_dir)),
        # DOCX inputs live in source/; the final PDFs and the bundled application
        # .txt stay at the folder root. Glob so target-position-labeled filenames
        # (e.g. ..._Resume_Frontend_Engineer.pdf) still register.
        "has_resume": bool(list(source_dir(app_dir).glob(f"{RESUME_STEM}*.docx"))
                           or list(app_dir.glob(f"{RESUME_STEM}*.docx"))),
        "has_pdf": bool(list(app_dir.glob(f"{RESUME_STEM}*.pdf"))),
        # Match any cover-letter PDF regardless of the role-label suffix.
        "has_cover_letter": bool(list(app_dir.glob("*Cover_Letter*.pdf"))),
        "has_app_txt": bool(list(app_dir.glob(f"{APPLICATION_STEM}*.txt"))),
        "notes": "",
    }

    # Parse slug: company-role-YYYYMMDD
    parts = app_dir.name.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
        info["date"] = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]}"
        info["company"] = parts[0].replace("-", " ").title()

    if meta.exists():
        try:
            with open(meta) as f:
                meta_data = yaml.safe_load(f) or {}
            # The folder is the derived overall status; pull everything else from
            # meta.yaml. Structured job facts (job_level/required_yoe/salary_range)
            # and the per-job status/stage/status_date live per posting under
            # `jobs`, so they are read from there, not the top level. The top-level
            # retired `stage` field was replaced by the structured per-job `progress`.
            for key in ["company", "role", "research_date", "posted_date",
                        "channel", "referrer", "next_action", "notes", "location",
                        "recruiter_email", "comp_notes", "url", "jobs",
                        "job_metadata_schema_version"]:
                if meta_data.get(key):
                    info[key] = meta_data[key]
        except Exception:
            pass

    # An application is "mixed" when its postings do not all share one per-job
    # status (e.g. one role rejected while another is still in progress). The
    # folder shows the derived rollup; the [mixed] tag flags that the roles differ.
    jobs_list = info.get("jobs")
    if isinstance(jobs_list, list) and jobs_list:
        job_statuses = {
            str(j.get("status") or "").strip()
            for j in jobs_list
            if isinstance(j, dict) and str(j.get("status") or "").strip()
        }
        info["mixed"] = len(job_statuses) > 1

    # research_date is the canonical creation date; fall back to the
    # slug-derived date (parsed above).
    if info.get("research_date"):
        info["date"] = info["research_date"]

    # Multi-JD applications: one resume covering several roles at one company.
    # Derive a display role/url from the jobs list when no top-level value is set.
    jobs = info.get("jobs")
    if isinstance(jobs, list) and jobs:
        first = jobs[0] if isinstance(jobs[0], dict) else {}
        if not info["role"]:
            first_role = first.get("role", "") or "Multiple roles"
            info["role"] = (f"{first_role} (+{len(jobs) - 1} more)"
                            if len(jobs) > 1 else first_role)
        if not info.get("url"):
            info["url"] = first.get("url", "")

    # Fallback: try to get role from tailored.yaml
    if not info["role"]:
        tailored = tailored_path(app_dir)
        if tailored.exists():
            try:
                with open(tailored) as f:
                    td = yaml.safe_load(f) or {}
                info["role"] = td.get("title", td.get("name", ""))
            except Exception:
                pass

    return info


def app_locations(info: dict, app_dir: Path) -> list[str]:
    """Gather every posting-location string for an application.

    Prefers the `location` recorded in meta.yaml (top-level for a single role,
    per-entry under `jobs:` for a multi-role application). Falls back to the
    `Location:` line(s) in the JD file(s) when meta.yaml has none recorded yet.
    """
    locs: list[str] = []
    top = str(info.get("location") or "").strip()
    if top:
        locs.append(top)
    jobs = info.get("jobs")
    if isinstance(jobs, list):
        for j in jobs:
            if isinstance(j, dict) and str(j.get("location") or "").strip():
                locs.append(str(j["location"]).strip())
    if locs:
        return locs
    for jd in find_jd_files(app_dir):
        try:
            locs.extend(extract_jd_locations(jd.read_text()))
        except OSError:
            continue
    return locs


def app_location_assessment(info: dict, app_dir: Path):
    """Assess every posting with its exact JD/workplace evidence; best match wins."""
    assessments = []
    jobs = info.get("jobs")
    if isinstance(jobs, list) and jobs:
        for job in jobs:
            if not isinstance(job, dict):
                continue
            jd_text = ""
            jd_file = str(job.get("jd_file") or "").strip()
            if jd_file:
                jd_path = source_dir(app_dir) / jd_file
                try:
                    jd_text = jd_path.read_text()
                except OSError:
                    pass
            assessments.append(assess_location(
                job.get("location"),
                config.location_policy(),
                title=job.get("role"),
                description=jd_text,
                workplace_hint=job.get("workplace"),
            ))
    else:
        jd_texts = []
        for jd_path in find_jd_files(app_dir):
            try:
                jd_texts.append(jd_path.read_text())
            except OSError:
                continue
        assessments.append(assess_location(
            info.get("location"),
            config.location_policy(),
            title=info.get("role"),
            description="\n".join(jd_texts),
        ))

    for assessment in assessments:
        if assessment.decision == "match":
            return assessment
    for assessment in assessments:
        if assessment.decision == "review":
            return assessment
    return assessments[0] if assessments else assess_location(
        "", config.location_policy())


def _resolve_application_target(target: str | Path) -> Path | None:
    """Resolve a slug or application-folder path."""
    p = Path(target)
    if p.exists():
        return application_dir(p)
    return find_application(str(target))


def enrich_application_metadata(target: str | Path, *, overwrite: bool = False) -> Path:
    """Safely insert missing schema-v5 job metadata into one ``meta.yaml``."""
    if overwrite:
        raise ValueError(
            "overwrite is disabled: the formatting-preserving editor only inserts "
            "missing metadata and preserves manual values"
        )
    result = process_application(target, write=True)
    if result["error"]:
        raise ValueError(result["error"])
    return Path(result["path"])


def backfill_metadata(
    statuses: list[str],
    *,
    write: bool = False,
    overwrite: bool = False,
    as_json: bool = False,
) -> bool:
    """Preview or safely insert metadata using the formatting-preserving editor."""
    if overwrite:
        message = (
            "overwrite is disabled: bulk metadata editing may only insert missing "
            "schema-v5 fields"
        )
        if as_json:
            print(json.dumps({"mode": "error", "rows": [], "failures": [message]}, indent=2))
        else:
            print(f"ERROR: {message}")
        return False
    rows = []
    for status in statuses:
        status_dir = _status_dir(status)
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            if not app_dir.is_dir() or app_dir.name.startswith("."):
                continue
            row = process_application(app_dir, write=write)
            row["status"] = status
            rows.append(row)

    failures = [row for row in rows if row["error"]]
    changed = [row for row in rows if row["changed_fields"]]
    if as_json:
        print(json.dumps({
            "mode": "write" if write else "dry_run",
            "rows": rows,
            "changed": changed,
            "failures": failures,
        }, indent=2))
        return not failures
    mode = "WRITE" if write else "DRY RUN"
    print(f"Metadata backfill ({mode})")
    for row in rows:
        if row["error"]:
            print(f"ERROR   {row['slug']}: {row['error']}")
        elif row["changed_fields"]:
            action = "updated" if write else "would update"
            print(f"{action:<12} {row['slug']}: "
                  f"{', '.join(row['changed_fields'])}")
    print(
        f"Scanned {len(rows)} applications; {len(changed)} "
        f"{'updated' if write else 'would change'}; {len(failures)} failed.")
    if not write and changed:
        print("Re-run with --write-metadata to persist this backfill.")
    return not failures


def check_metadata(statuses: list[str], as_json: bool = False) -> bool:
    """Validate structured level/YOE/compensation metadata for applications."""
    rows = []
    for status in statuses:
        status_dir = _status_dir(status)
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            if not app_dir.is_dir() or app_dir.name.startswith("."):
                continue
            meta_path = app_dir / "meta.yaml"
            meta = {}
            try:
                meta = yaml.safe_load(meta_path.read_text()) or {}
                if isinstance(meta, dict):
                    errors = validate_meta(meta, app_dir=app_dir)
                else:
                    errors = ["meta.yaml must contain a mapping"]
            except (OSError, yaml.YAMLError) as exc:
                errors = [f"could not read meta.yaml: {exc}"]
            rows.append({
                "slug": app_dir.name,
                "company": (meta.get("company", "") if isinstance(meta, dict) else ""),
                "status": status,
                "valid": not errors,
                "errors": errors,
            })

    invalid = [row for row in rows if not row["valid"]]
    if as_json:
        print(json.dumps({"rows": rows, "invalid": invalid}, indent=2))
        return not invalid
    if not rows:
        print(f"No applications found under: {', '.join(statuses)}")
        return True
    for row in rows:
        mark = "ok" if row["valid"] else "INVALID"
        print(f"{mark:<7} {row['slug']}")
        for error in row["errors"]:
            print(f"          - {error}")
    print(f"Checked {len(rows)} applications; {len(invalid)} invalid.")
    return not invalid


def check_locations(statuses: list[str], as_json: bool = False) -> bool:
    """Flag applications whose posting location is outside the configured location policy.

    A row is a *mismatch* (hard failure) only when its location is a definite place
    outside the policy — a foreign location or a non-preferred US office. An
    *unknown* row (blank or unrecognized location) is surfaced for manual review
    but is NOT a policy violation, so it does not fail the check. Returns True when
    there are no mismatches (unknown/review rows do not flip the result).
    """
    rows = []
    for status in statuses:
        status_dir = _status_dir(status)
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            if not app_dir.is_dir() or app_dir.name.startswith("."):
                continue
            info = load_application(app_dir, status)
            locs = app_locations(info, app_dir)
            assessment = app_location_assessment(info, app_dir)
            rows.append({
                "slug": app_dir.name,
                "company": info.get("company", ""),
                "status": status,
                "category": assessment.category,
                "match": assessment.matched,
                "decision": assessment.decision,
                "workplace": assessment.workplace,
                "evidence": list(assessment.evidence),
                "review_reasons": list(assessment.review_reasons),
                "locations": locs,
            })

    non_matching = [r for r in rows if not r["match"]]
    # Split non-matching rows into definite policy violations (foreign / non-preferred
    # US office) and "unknown" rows (blank / unrecognized location). Only the former
    # fail the check; the latter are surfaced for manual review.
    mismatches = [r for r in non_matching if r["decision"] == "no_match"]
    review = [r for r in non_matching if r["decision"] == "review"]

    if as_json:
        print(json.dumps({
            "rows": rows,
            "non_matching": non_matching,
            "mismatches": mismatches,
            "review": review,
        }, indent=2))
        return not mismatches

    if not rows:
        print(f"No applications found under: {', '.join(statuses)}")
        return True

    width = max((len(r["slug"]) for r in rows), default=4)
    print("\u2500" * (width + 40))
    print(f"{'SLUG':<{width}}  {'MATCH':<5}  {'CATEGORY':<13}  LOCATIONS")
    print("\u2500" * (width + 40))
    for r in sorted(rows, key=lambda x: (x["match"], x["slug"])):
        mark = "ok" if r["match"] else "NO"
        loc = " | ".join(r["locations"]) if r["locations"] else "(none recorded)"
        print(f"{r['slug']:<{width}}  {mark:<5}  {r['category']:<13}  {loc}")
    print("\u2500" * (width + 40))
    print(f"Total: {len(rows)}  |  match: {len(rows) - len(non_matching)}  "
          f"|  mismatch: {len(mismatches)}  |  review: {len(review)}")
    if mismatches:
        print("\nMismatches (outside the configured location policy):")
        for r in mismatches:
            print(f"  - {r['slug']}  [{r['category']}]  "
                  f"{' | '.join(r['locations']) or '(none recorded)'}")
    if review:
        print("\nReview (blank / unrecognized location \u2014 not a policy failure):")
        for r in review:
            print(f"  - {r['slug']}  [{r['category']}]  "
                  f"{' | '.join(r['locations']) or '(none recorded)'}")
    return not mismatches


def find_application(slug: str) -> Path | None:
    """Return the current path of an application by slug, searching status folders."""
    for status in STATUS_FOLDERS:
        candidate = _status_dir(status) / slug
        if candidate.is_dir():
            return candidate
    return None


def _load_v5_meta(meta_path: Path) -> tuple[dict, bytes]:
    """Load a meta.yaml, failing loud (exit non-zero) unless it is parseable v5."""
    if not meta_path.is_file():
        print(f"Error: {meta_path} not found; cannot update per-job status",
              file=sys.stderr)
        sys.exit(1)
    raw = meta_path.read_bytes()
    try:
        meta = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        print(f"Error: could not parse {meta_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if (not isinstance(meta, dict)
            or meta.get("job_metadata_schema_version") != APPLICATION_SCHEMA_VERSION):
        print(f"Error: {meta_path} is not schema v{APPLICATION_SCHEMA_VERSION}; "
              "run migrate_to_v5.py before updating status", file=sys.stderr)
        sys.exit(1)
    jobs = meta.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        print(f"Error: {meta_path} has no jobs list", file=sys.stderr)
        sys.exit(1)
    return meta, raw


# --------------------------------------------------------------------------- #
# Calendar (the single private calendar/todo file) + transactional writes
# --------------------------------------------------------------------------- #
def _calendar_path() -> Path:
    return config.calendar_path()


def _read_calendar_raw(*, create: bool = False) -> bytes | None:
    """Current calendar bytes; optionally create the template file first."""
    path = _calendar_path()
    if not path.is_file():
        if not create:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as handle:
            handle.write(CALENDAR_TEMPLATE.encode("utf-8"))
    return path.read_bytes()


def _entry_fields_for_progress(
    entry, *, slug: str, job: dict, progress: dict, company: str
) -> dict:
    """Merge a job's new progress summary into its calendar entry fields."""
    if entry is not None:
        fields = entry.fields()
    else:
        fields = {
            "id": progress.get("calendar_item"),
            "application": slug,
            "role": str(job.get("role") or ""),
            "starts_at": None,
            "timezone": None,
            "follow_up_at": None,
            "source": "manual",
            "reschedule_to": None,
            "reschedule_timezone": None,
            "cancel": False,
            "history": [],
        }
    fields["phase"] = progress.get("phase")
    fields["state"] = progress.get("state")
    fields["label"] = progress.get("label")
    fields["_company"] = company
    return fields


def _commit_meta_and_calendar(
    meta_writes: list[tuple[Path, bytes, object]],
    calendar_plan,
) -> bool:
    """Apply meta plan(s) + one calendar plan as a transaction (all or none).

    ``meta_writes`` rows are ``(meta_path, pre_image_bytes, plan)``; every plan
    must already be error-free. Meta files are written first; the calendar
    write commits the transaction. If the calendar write fails (e.g. a checksum
    race with a concurrent human edit), every written meta file is rolled back
    to its pre-image and the command exits non-zero — a one-sided write never
    survives. Returns True when anything changed on disk.
    """
    import hashlib

    written: list[tuple[Path, bytes, object]] = []

    def rollback() -> None:
        for meta_path, pre_image, plan in reversed(written):
            try:
                atomic_write_bytes(
                    meta_path, pre_image,
                    expected_sha256=hashlib.sha256(plan.output_bytes).hexdigest())
            except (MetadataChecksumMismatchError, OSError) as exc:
                print(f"Error: rollback of {meta_path} failed: {exc}; restore "
                      "it manually from git", file=sys.stderr)

    changed = False
    for meta_path, pre_image, plan in meta_writes:
        if not plan.changed:
            continue
        try:
            atomic_write_bytes(meta_path, plan.output_bytes,
                               expected_sha256=plan.before_sha256)
        except (MetadataChecksumMismatchError, OSError) as exc:
            rollback()
            print(f"Error: could not write {meta_path}: {exc}", file=sys.stderr)
            sys.exit(1)
        written.append((meta_path, pre_image, plan))
        changed = True
    if calendar_plan is not None and calendar_plan.changed:
        try:
            atomic_write_bytes(_calendar_path(), calendar_plan.output_bytes,
                               expected_sha256=calendar_plan.before_sha256)
        except (MetadataChecksumMismatchError, OSError) as exc:
            rollback()
            print(f"Error: calendar write failed ({exc}); metadata changes were "
                  "rolled back — review calendar.md and retry", file=sys.stderr)
            sys.exit(1)
        changed = True
    return changed


def _move_application(slug: str, src: Path, new_status: str) -> bool:
    """Move an application folder to new_status's folder; return True if it moved."""
    current_label = status_label_for_dir(src.parent.name)
    if current_label == new_status:
        return False
    dest_dir = _status_dir(new_status)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / slug
    if dest.exists():
        print(f"Error: {dest} already exists — resolve the duplicate first",
              file=sys.stderr)
        sys.exit(1)
    shutil.move(str(src), str(dest))
    print(f"Moved {slug}: {current_label or src.parent.name} -> {new_status}")
    return True


def _sync_log_hint(changed: bool, moved: bool) -> None:
    """Remind to re-sync the postings log after any status write or folder move."""
    if changed or moved:
        print("Re-run `status.py --sync-log` to refresh the postings log.")


def _transition_calendar_plan(
    slug: str, company: str, jobs_progress: list[tuple[dict, dict]]
):
    """Plan the calendar updates for jobs whose progress references an entry.

    ``jobs_progress`` pairs each affected job dict with its NEW progress
    summary. Jobs without a ``calendar_item`` need no calendar change. Returns
    ``None`` when nothing references the calendar; exits non-zero on a missing
    file/entry or a plan error (the caller writes nothing in that case).
    """
    referencing = [
        (job, progress) for job, progress in jobs_progress
        if str((progress or {}).get("calendar_item") or "").strip()
    ]
    if not referencing:
        return None
    raw = _read_calendar_raw()
    if raw is None:
        print(f"Error: calendar file {_calendar_path()} not found but "
              f"{slug} references calendar entries; run --check-calendar",
              file=sys.stderr)
        sys.exit(1)
    doc = parse_calendar(raw.decode("utf-8"))
    if doc.errors:
        print(f"Error: calendar file {_calendar_path()} failed validation:",
              file=sys.stderr)
        for error in doc.errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    upserts: dict[str, dict] = {}
    for job, progress in referencing:
        item = progress["calendar_item"]
        entry = doc.entries.get(item)
        if entry is None:
            print(f"Error: {slug} references missing calendar entry '{item}'; "
                  "run --check-calendar", file=sys.stderr)
            sys.exit(1)
        upserts[item] = _entry_fields_for_progress(
            entry, slug=slug, job=job, progress=progress, company=company)
    plan = plan_calendar_update(raw, upserts)
    if plan.errors:
        print("Error: could not plan the calendar update (nothing written):",
              file=sys.stderr)
        for error in plan.errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    return plan


def update_status(slug: str, new_status: str):
    """Set every posting's status to new_status, stamp today, then move the folder.

    The per-job `status` fields are the source of truth, so a whole-application
    transition writes them all (stamping `status_date` and the deterministic
    `progress` summary for the new status) BEFORE moving the folder to match the
    derived rollup. Jobs whose progress references a calendar entry get that
    entry updated in the same transaction. Fails loud (no move, no partial
    write) if meta.yaml is missing, unparseable, or not schema v5.
    """
    if new_status not in STATUS_FOLDERS:
        print(f"Error: invalid status '{new_status}'. Must be one of: "
              f"{', '.join(STATUS_FOLDERS)}", file=sys.stderr)
        sys.exit(1)

    src = find_application(slug)
    if src is None:
        print(f"Error: application '{slug}' not found under any status folder "
              f"({', '.join(STATUS_FOLDERS)})", file=sys.stderr)
        sys.exit(1)

    meta_path = src / "meta.yaml"
    meta, raw = _load_v5_meta(meta_path)
    today = date.today().isoformat()
    updates: dict = {}
    jobs_progress: list[tuple[dict, dict]] = []
    for index, job in enumerate(meta["jobs"]):
        current = job.get("progress") if isinstance(job, dict) else None
        progress = default_progress_for_status(new_status, current=current)
        updates[("jobs", index)] = {
            "status": new_status, "status_date": today, "progress": progress,
        }
        jobs_progress.append((job if isinstance(job, dict) else {}, progress))

    plan = plan_field_updates(raw, updates)
    if plan.errors:
        _print_plan_errors(meta_path, plan)
        sys.exit(1)
    calendar_plan = _transition_calendar_plan(
        slug, str(meta.get("company") or ""), jobs_progress)
    changed = _commit_meta_and_calendar([(meta_path, raw, plan)], calendar_plan)
    if plan.changed:
        print(f"{slug}: set all {len(meta['jobs'])} posting(s) to '{new_status}' "
              f"(status_date {today})")

    moved = _move_application(slug, src, new_status)
    if not changed and not moved:
        print(f"{slug} is already fully '{new_status}' — nothing to do")
    _sync_log_hint(changed, moved)


def update_job_status(slug: str, role_match: str, status: str):
    """Set ONE posting's status, then re-derive the rollup & move the folder.

    `role_match` is a case-insensitive substring of `jobs[].role` or a 1-based
    integer index and must resolve to exactly one posting. `status` is one of
    the five status labels; the transition stamps that posting's `status_date`
    and resets its `progress` summary deterministically (phase/state details
    beyond the coarse status belong to --update-progress). After the edit the
    overall status is re-derived from all postings; if it differs from the
    current folder the app is moved.
    """
    if status not in STATUS_FOLDERS:
        print(f"Error: STATUS must be one of {', '.join(STATUS_FOLDERS)}; "
              f"got '{status}'", file=sys.stderr)
        sys.exit(1)

    src = find_application(slug)
    if src is None:
        print(f"Error: application '{slug}' not found under any status folder "
              f"({', '.join(STATUS_FOLDERS)})", file=sys.stderr)
        sys.exit(1)

    meta_path = src / "meta.yaml"
    meta, raw = _load_v5_meta(meta_path)
    jobs = meta["jobs"]
    index = _resolve_job_index(jobs, role_match)

    job = jobs[index] if isinstance(jobs[index], dict) else {}
    role = str(job.get("role") or "").strip() or f"job {index + 1}"
    old_status = str(job.get("status") or "").strip() or "(unset)"

    progress = default_progress_for_status(status, current=job.get("progress"))
    update = {
        "status": status,
        "status_date": date.today().isoformat(),
        "progress": progress,
    }
    plan = plan_field_updates(raw, {("jobs", index): update})
    if plan.errors:
        _print_plan_errors(meta_path, plan)
        sys.exit(1)
    calendar_plan = _transition_calendar_plan(
        slug, str(meta.get("company") or ""), [(job, progress)])
    changed = _commit_meta_and_calendar([(meta_path, raw, plan)], calendar_plan)

    detail = f"status {old_status} -> {status}"
    print(f"{slug} posting [{index + 1}] {role}: {detail}")
    if not changed:
        print(f"  (meta.yaml already matched — {detail})")

    # Recompute the rollup from the edited postings and move the folder to match.
    edited = yaml.safe_load(_read_after_edit(meta_path, raw, plan.changed))
    derived = derive_status(edited["jobs"])
    moved = _move_application(slug, src, derived)
    _sync_log_hint(changed, moved)


def _print_plan_errors(meta_path: Path, plan) -> None:
    print(f"Error: could not update {meta_path} (nothing written):",
          file=sys.stderr)
    for error in plan.errors:
        print(f"  - {error}", file=sys.stderr)


def _utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_progress(slug: str, role_match: str, *, phase: str, state: str,
                    label: str | None = None):
    """Set ONE posting's structured progress; never moves the status folder.

    Writes ``jobs[].progress`` (phase, state, optional label, tool-stamped
    ``updated_at``, ``source: manual``) and the calendar entry together,
    transactionally. Entering a scheduling state (booking/waiting/scheduled/
    reschedule) creates the calendar entry when the job has none — with a fresh
    stable id recorded as ``progress.calendar_item``. ``--state scheduled``
    requires the calendar entry to already carry the confirmed time + timezone
    (record it in calendar.md, then run --sync-calendar --write).
    """
    if phase not in PROGRESS_PHASES:
        print(f"Error: --phase must be one of {', '.join(PROGRESS_PHASES)}",
              file=sys.stderr)
        sys.exit(1)
    if state not in PROGRESS_STATES:
        print(f"Error: --state must be one of {', '.join(PROGRESS_STATES)}",
              file=sys.stderr)
        sys.exit(1)

    src = find_application(slug)
    if src is None:
        print(f"Error: application '{slug}' not found under any status folder "
              f"({', '.join(STATUS_FOLDERS)})", file=sys.stderr)
        sys.exit(1)

    meta_path = src / "meta.yaml"
    meta, raw = _load_v5_meta(meta_path)
    jobs = meta["jobs"]
    index = _resolve_job_index(jobs, role_match)
    job = jobs[index] if isinstance(jobs[index], dict) else {}
    role = str(job.get("role") or "").strip() or f"job {index + 1}"
    current = job.get("progress") if isinstance(job.get("progress"), dict) else {}

    progress: dict = {"phase": phase, "state": state}
    effective_label = label if label is not None else current.get("label")
    if str(effective_label or "").strip():
        progress["label"] = effective_label
    calendar_item = str(current.get("calendar_item") or "").strip()

    company = str(meta.get("company") or "")
    calendar_plan = None
    needs_entry = state in PROGRESS_SCHEDULING_STATES or calendar_item
    if needs_entry:
        raw_calendar = _read_calendar_raw(create=True)
        doc = parse_calendar(raw_calendar.decode("utf-8"))
        if doc.errors:
            print(f"Error: calendar file {_calendar_path()} failed validation "
                  "(fix it or run --check-calendar):", file=sys.stderr)
            for error in doc.errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)
        entry = doc.entries.get(calendar_item) if calendar_item else None
        if calendar_item and entry is None:
            print(f"Error: {slug} references missing calendar entry "
                  f"'{calendar_item}'; run --check-calendar", file=sys.stderr)
            sys.exit(1)
        if entry is None:
            calendar_item = generate_entry_id(doc.entries, slug)
        progress["calendar_item"] = calendar_item
        fields = _entry_fields_for_progress(
            entry, slug=slug, job=job, progress=progress, company=company)
        calendar_plan = plan_calendar_update(
            raw_calendar, {calendar_item: fields}, create_missing=entry is None)
        if calendar_plan.errors:
            print("Error: could not plan the calendar update (nothing written):",
                  file=sys.stderr)
            for error in calendar_plan.errors:
                print(f"  - {error}", file=sys.stderr)
            if state == "scheduled":
                print("Hint: a scheduled entry needs the confirmed exact time + "
                      "timezone. Record starts_at/timezone on the entry in "
                      f"{_calendar_path()} and run --sync-calendar --write.",
                      file=sys.stderr)
            sys.exit(1)
    elif str(current.get("calendar_item") or "").strip():
        progress["calendar_item"] = current["calendar_item"]

    progress["updated_at"] = _utc_now_stamp()
    progress["source"] = {"kind": "manual", "ref": ""}

    plan = plan_field_updates(raw, {("jobs", index): {"progress": progress}})
    if plan.errors:
        _print_plan_errors(meta_path, plan)
        if state == "closed":
            print("Hint: close a role with --update-job <slug> <role> "
                  "rejected|ignored — that sets state 'closed' with it.",
                  file=sys.stderr)
        sys.exit(1)
    _commit_meta_and_calendar([(meta_path, raw, plan)], calendar_plan)
    bits = [f"phase -> {phase}", f"state -> {state}"]
    if label is not None:
        bits.append(f"label -> {label!r}")
    print(f"{slug} posting [{index + 1}] {role}: {'; '.join(bits)}")
    if calendar_plan is not None and calendar_plan.changed:
        print(f"Updated calendar entry {progress['calendar_item']} -> "
              f"{_calendar_path()}")
    print("Progress-only update: the status folder is unchanged.")


# --------------------------------------------------------------------------- #
# Calendar verification + preview-first human-edit sync
# --------------------------------------------------------------------------- #
def _fleet_calendar_refs() -> dict[str, list[tuple[Path, dict, int, dict]]]:
    """calendar_item -> [(meta_path, meta, job_index, job)] across the fleet."""
    refs: dict[str, list[tuple[Path, dict, int, dict]]] = {}
    for status in STATUS_FOLDERS:
        status_dir = _status_dir(status)
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            meta_path = app_dir / "meta.yaml"
            if not app_dir.is_dir() or not meta_path.is_file():
                continue
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            jobs = meta.get("jobs") if isinstance(meta, dict) else None
            for index, job in enumerate(jobs if isinstance(jobs, list) else []):
                if not isinstance(job, dict):
                    continue
                progress = job.get("progress")
                item = str((progress or {}).get("calendar_item") or "").strip() \
                    if isinstance(progress, dict) else ""
                if item:
                    refs.setdefault(item, []).append((meta_path, meta, index, job))
    return refs


def check_calendar(as_json: bool = False) -> bool:
    """Verify calendar.md and its cross-links with per-job progress (read-only)."""
    path = _calendar_path()
    findings: list[str] = []
    refs = _fleet_calendar_refs()
    raw = _read_calendar_raw()
    doc = None
    if raw is None:
        if refs:
            findings.append(
                f"calendar file {path} is missing but "
                f"{len(refs)} progress entr{'y' if len(refs) == 1 else 'ies'} "
                "reference calendar items")
    else:
        doc = parse_calendar(raw.decode("utf-8"))
        findings.extend(doc.errors)

    entries = doc.entries if doc is not None else {}
    for item, holders in sorted(refs.items()):
        if len(holders) > 1:
            findings.append(
                f"calendar entry '{item}' is referenced by multiple jobs: "
                + ", ".join(h[0].parent.name for h in holders))
        entry = entries.get(item)
        if entry is None:
            if doc is not None:
                findings.append(
                    f"{holders[0][0].parent.name}: progress.calendar_item "
                    f"'{item}' has no calendar entry")
            continue
        meta_path, _meta, index, job = holders[0]
        slug = meta_path.parent.name
        progress = job.get("progress") or {}
        if entry.application != slug:
            findings.append(
                f"entry '{item}': application '{entry.application}' does not "
                f"match {slug}")
        if entry.role != str(job.get("role") or ""):
            findings.append(
                f"entry '{item}': role '{entry.role}' does not match "
                f"jobs[{index}].role of {slug}")
        for field in ("phase", "state"):
            if getattr(entry, field) != progress.get(field):
                findings.append(
                    f"entry '{item}': {field} '{getattr(entry, field)}' drifted "
                    f"from meta progress '{progress.get(field)}' "
                    "(run --sync-calendar)")
        expected_section = STATE_SECTIONS.get(entry.state)
        if expected_section and entry.section != expected_section:
            findings.append(
                f"entry '{item}': sits under '{entry.section}' but state "
                f"'{entry.state}' belongs under '{expected_section}'")
        if entry.checked and progress.get("state") in CHECKED_BOX_TRANSITIONS:
            findings.append(
                f"entry '{item}': box is checked — run --sync-calendar to fold "
                "it into progress")
        if entry.cancel or entry.reschedule_to:
            findings.append(
                f"entry '{item}': has a pending "
                f"{'cancellation' if entry.cancel else 'reschedule'} proposal — "
                "run --sync-calendar")
    for item, entry in sorted(entries.items()):
        if item not in refs:
            findings.append(
                f"entry '{item}': no job's progress.calendar_item references it "
                f"(application '{entry.application}', role '{entry.role}')")

    if as_json:
        print(json.dumps({"calendar": str(path), "findings": findings}, indent=2))
        return not findings
    if not findings:
        state = "absent (nothing references it)" if raw is None else "consistent"
        print(f"Calendar {path}: {state}; "
              f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}, "
              f"{len(refs)} referenced.")
        return True
    print(f"Calendar {path}: {len(findings)} finding(s)")
    for finding in findings:
        print(f"  - {finding}")
    return False


def _sync_proposals(doc, refs):
    """Compute (proposal_rows, errors) mapping owner calendar edits to progress.

    A proposal row is ``(entry_id, meta_path, job_index, new_progress,
    new_entry_fields, description)``. Meta stays canonical for phase/state, so
    entries that merely drifted are re-rendered from meta; the owner-edit
    surfaces (checked box, reschedule_to, cancel: true) win over drift repair.
    """
    proposals = []
    errors = []
    for item, entry in sorted(doc.entries.items()):
        holders = refs.get(item)
        if not holders:
            errors.append(
                f"entry '{item}' is not referenced by any job's progress; "
                "cannot sync it")
            continue
        if len(holders) > 1:
            errors.append(f"entry '{item}' is referenced by multiple jobs")
            continue
        meta_path, meta, index, job = holders[0]
        slug = meta_path.parent.name
        progress = dict(job.get("progress") or {})
        meta_state = progress.get("state")
        company = str(meta.get("company") or "")
        fields = entry.fields()
        fields["_company"] = company

        if meta_state == "closed":
            new_state = None  # never reopen a closed role from the calendar
        elif entry.cancel:
            fields = record_cancellation(fields)
            fields["_company"] = company
            new_state = fields["state"]
            description = (f"{slug} [{entry.role}]: cancellation recorded — "
                           f"occurrence kept in history, state -> {new_state}")
        elif entry.reschedule_to:
            fields = record_reschedule(
                fields, entry.reschedule_to, entry.reschedule_timezone)
            fields["_company"] = company
            new_state = "scheduled"
            description = (f"{slug} [{entry.role}]: confirmed reschedule to "
                           f"{fields['starts_at']} {fields['timezone']} — old "
                           "occurrence kept as superseded, state -> scheduled")
        elif entry.checked and meta_state in CHECKED_BOX_TRANSITIONS:
            new_state = CHECKED_BOX_TRANSITIONS[meta_state]
            fields["state"] = new_state
            description = (f"{slug} [{entry.role}]: checked box — state "
                           f"{meta_state} -> {new_state}")
        else:
            new_state = None

        if new_state is None:
            # Drift repair only: re-render the marker from canonical meta.
            if (entry.phase, entry.state) != (
                progress.get("phase"), progress.get("state")
            ):
                fields["phase"] = progress.get("phase")
                fields["state"] = progress.get("state")
                proposals.append((
                    item, meta_path, index, None, fields,
                    f"{slug} [{entry.role}]: re-render entry from meta progress "
                    f"({progress.get('phase')}/{progress.get('state')})"))
            continue

        new_progress = dict(progress)
        new_progress["state"] = new_state
        new_progress["phase"] = progress.get("phase")
        new_progress["updated_at"] = _utc_now_stamp()
        new_progress["source"] = {"kind": "manual", "ref": ""}
        fields["phase"] = new_progress["phase"]
        proposals.append((item, meta_path, index, new_progress, fields, description))
    return proposals, errors


def sync_calendar(write: bool = False, as_json: bool = False) -> bool:
    """Preview (default) or apply how owner edits to calendar.md map to progress.

    Owner-edit surfaces: a checked box (action done / interview happened), a
    filled ``reschedule_to`` + ``reschedule_timezone`` (confirmed replacement
    time — the old occurrence is preserved as superseded), and ``cancel: true``
    (occurrence cancelled, never auto-rejecting the role). ``--write`` applies
    every proposal transactionally (all meta files + the calendar, or nothing).
    """
    path = _calendar_path()
    raw = _read_calendar_raw()
    refs = _fleet_calendar_refs()
    if raw is None:
        if refs:
            print(f"Error: calendar file {path} is missing but progress "
                  "references calendar entries", file=sys.stderr)
            return False
        print(f"No calendar file at {path}; nothing to sync.")
        return True
    doc = parse_calendar(raw.decode("utf-8"))
    if doc.errors:
        print(f"Error: calendar file {path} failed validation; fix these "
              "before syncing:", file=sys.stderr)
        for error in doc.errors:
            print(f"  - {error}", file=sys.stderr)
        return False

    proposals, errors = _sync_proposals(doc, refs)
    if errors:
        print("Error: cannot sync (nothing written):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    if as_json:
        print(json.dumps({
            "mode": "write" if write else "dry_run",
            "proposals": [row[5] for row in proposals],
        }, indent=2))
    if not proposals:
        if not as_json:
            print(f"Calendar {path}: nothing to sync.")
        return True
    if not as_json:
        print(f"Calendar sync ({'WRITE' if write else 'DRY RUN'}):")
        for row in proposals:
            print(f"  - {row[5]}")
    if not write:
        if not as_json:
            print("No files written. Re-run with --sync-calendar --write to apply.")
        return True

    # Group meta updates per file, plan everything, then commit transactionally.
    upserts: dict[str, dict] = {}
    by_meta: dict[Path, dict] = {}
    for item, meta_path, index, new_progress, fields, _description in proposals:
        upserts[item] = fields
        if new_progress is not None:
            by_meta.setdefault(meta_path, {})[("jobs", index)] = {
                "progress": new_progress}
    meta_writes = []
    for meta_path, updates in sorted(by_meta.items()):
        pre_image = meta_path.read_bytes()
        plan = plan_field_updates(pre_image, updates)
        if plan.errors:
            _print_plan_errors(meta_path, plan)
            return False
        meta_writes.append((meta_path, pre_image, plan))
    calendar_plan = plan_calendar_update(raw, upserts)
    if calendar_plan.errors:
        print("Error: could not plan the calendar update (nothing written):",
              file=sys.stderr)
        for error in calendar_plan.errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    _commit_meta_and_calendar(meta_writes, calendar_plan)
    print(f"Applied {len(proposals)} proposal(s); calendar and metadata "
          "updated together.")
    return True


def _read_after_edit(meta_path: Path, raw: bytes, changed: bool) -> str:
    """Return the meta.yaml text reflecting the edit (re-read if it was written)."""
    if changed:
        return meta_path.read_text(encoding="utf-8")
    return raw.decode("utf-8")


def _resolve_job_index(jobs: list, role_match: str) -> int:
    """Resolve a role substring or 1-based index to exactly one job index.

    Lists the candidate postings and exits non-zero on no/ambiguous match.
    """
    token = str(role_match).strip()
    if token.isdigit():
        index = int(token) - 1
        if 0 <= index < len(jobs):
            return index
        print(f"Error: posting index {token} out of range (1..{len(jobs)})",
              file=sys.stderr)
        _list_job_candidates(jobs)
        sys.exit(1)

    needle = token.casefold()
    matches = [
        i for i, j in enumerate(jobs)
        if isinstance(j, dict) and needle in str(j.get("role") or "").casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        print(f"Error: no posting role matches {role_match!r}", file=sys.stderr)
    else:
        print(f"Error: {role_match!r} matches {len(matches)} postings; refine the "
              "text or pass a 1-based index", file=sys.stderr)
    _list_job_candidates(jobs)
    sys.exit(1)


def _list_job_candidates(jobs: list) -> None:
    """Print the postings (1-based index, role, status) for disambiguation."""
    print("Postings:", file=sys.stderr)
    for i, j in enumerate(jobs):
        if not isinstance(j, dict):
            continue
        role = str(j.get("role") or "").strip() or "(no role)"
        status = str(j.get("status") or "").strip() or "(unset)"
        print(f"  [{i + 1}] {role}  ({status})", file=sys.stderr)


def _role_cell(a: dict) -> str:
    """Role display cell; tag apps whose postings hold differing per-job statuses."""
    role = a.get("role", "")
    return f"{role} [mixed]" if a.get("mixed") else role


def print_table(apps: list[dict]):
    if not apps:
        print("No applications found under applications/ status folders "
              f"({', '.join(STATUS_FOLDERS)})")
        print("Use the resume-writer skill to create your first application.")
        return

    cols = {
        "Company": max(max((len(a["company"]) for a in apps), default=7), 7),
        "Role": max(max((len(_role_cell(a)) for a in apps), default=4), 4),
        "Date": 10,
        "Status": max(max((len(a["status"]) for a in apps), default=6), 11),
        "Channel": max(max((len(a.get("channel", "")) for a in apps), default=7), 7),
        "Files": 8,
    }

    header = "  ".join(f"{k:<{v}}" for k, v in cols.items())
    separator = "\u2500" * len(header)

    print(separator)
    print(header)
    print(separator)

    for a in sorted(apps, key=lambda x: x["date"], reverse=True):
        files = []
        if a["has_resume"]:
            files.append("docx")
        if a["has_pdf"]:
            files.append("pdf")
        if a.get("has_cover_letter"):
            files.append("cl")
        if a.get("has_app_txt"):
            files.append("txt")
        files_str = "+".join(files) if files else "\u2014"

        channel = a.get("channel", "")
        role_cell = _role_cell(a)
        print(f"{a['company']:<{cols['Company']}}  {role_cell:<{cols['Role']}}  {a['date']:<{cols['Date']}}  {a['status']:<{cols['Status']}}  {channel:<{cols['Channel']}}  {files_str}")

        # Show next_action if present
        if a.get("next_action"):
            print(f"  -> {a['next_action']}")

    print(separator)
    print(f"Total: {len(apps)} applications")

    # Funnel summary (ordered by the status-folder pipeline)
    status_counts = {}
    for a in apps:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
    if len(status_counts) > 1:
        funnel = " | ".join(f"{s}: {status_counts.get(s, 0)}"
                            for s in STATUS_FOLDERS if s in status_counts)
        print(f"Funnel: {funnel}")

    # Structured-progress health: "active with no action" is not the same as
    # "active and stuck scheduling" — surface who owes an action and which
    # bookings blew past their follow-up date.
    action, overdue = _progress_attention(apps)
    if action:
        print("Action needed (owner owes an action):")
        for line in action:
            print(f"  -> {line}")
    if overdue:
        print("Overdue waiting (past follow-up, no confirmation):")
        for line in overdue:
            print(f"  -> {line}")


def _progress_attention(apps: list[dict]) -> tuple[list[str], list[str]]:
    """(action-needed lines, overdue-waiting lines) from per-job progress.

    Overdue-waiting needs each entry's follow-up date, which lives in the
    calendar file; the calendar is read best-effort here (this is a read-only
    view — --check-calendar is the strict gate).
    """
    follow_ups: dict[str, str] = {}
    raw = _read_calendar_raw()
    if raw is not None:
        try:
            doc = parse_calendar(raw.decode("utf-8"))
        except UnicodeDecodeError:
            doc = None
        if doc is not None:
            for entry in doc.entries.values():
                if entry.follow_up_at:
                    follow_ups[entry.entry_id] = str(entry.follow_up_at)
    today = date.today().isoformat()
    action: list[str] = []
    overdue: list[str] = []
    for a in apps:
        jobs = a.get("jobs")
        if not isinstance(jobs, list):
            continue
        for job in jobs:
            progress = job.get("progress") if isinstance(job, dict) else None
            if not isinstance(progress, dict):
                continue
            state = str(progress.get("state") or "")
            who = f"{a.get('company') or a.get('slug')} — {job.get('role')}"
            label = str(progress.get("label") or "").strip()
            suffix = f" ({label})" if label else ""
            if state in PROGRESS_ACTION_STATES:
                action.append(f"{who}: {state}{suffix}")
            elif state in PROGRESS_WAITING_STATES:
                follow = follow_ups.get(
                    str(progress.get("calendar_item") or ""), "")[:10]
                if follow and follow < today:
                    overdue.append(f"{who}: {state}, follow-up was {follow}")
    return action, overdue


def collect_apps() -> list[dict]:
    """Scan every status folder for applications."""
    apps = []
    for status in STATUS_FOLDERS:
        status_dir = _status_dir(status)
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            if app_dir.is_dir() and not app_dir.name.startswith("."):
                info = load_application(app_dir, status)
                if info:
                    apps.append(info)
    return apps


def build_log(apps: list[dict]) -> dict:
    """Flatten applications into a postings log (one row per posting/role).

    job-search reads this to skip postings we've already generated or considered
    (dedup by URL, else by company+role). New roles at the same company still
    surface because each posting is listed individually.
    """
    postings = []
    for a in sorted(apps, key=lambda x: (x.get("company", ""), x.get("slug", ""))):
        folder_status = a.get("status", "")
        common = {
            "company": a.get("company", ""),
            "slug": a.get("slug", ""),
            "date": a.get("date", ""),
        }
        jobs = a.get("jobs")
        if isinstance(jobs, list) and jobs:
            for j in jobs:
                if not isinstance(j, dict):
                    continue
                # Each posting carries its OWN per-job status (not the folder's
                # derived rollup), falling back to the folder only if unset.
                postings.append({**common,
                                 "status": str(j.get("status") or "").strip()
                                 or folder_status,
                                 "role": j.get("role", ""),
                                 "url": j.get("url", "")})
        else:
            postings.append({**common,
                             "status": folder_status,
                             "role": a.get("role", ""),
                             "url": a.get("url", "")})
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(postings),
        "postings": postings,
    }


def _default_aliases(name: str) -> list[str]:
    low = name.strip().lower()
    return [low] if low else []


def _load_company_search_log_raw() -> dict:
    if not COMPANY_SEARCH_LOG.exists():
        return {"skip_within_days": 7, "companies": []}
    with open(COMPANY_SEARCH_LOG) as f:
        return yaml.safe_load(f) or {"skip_within_days": 7, "companies": []}


def _company_entry_key(name: str) -> str:
    return name.strip().lower()


def build_created_search_entries(apps: list[dict]) -> list[dict]:
    """One row per company with an application folder (latest folder date)."""
    latest: dict[str, str] = {}
    for a in apps:
        company = (a.get("company") or "").strip()
        day = (a.get("date") or "").strip()
        if not company or not day:
            continue
        prev = latest.get(company)
        if not prev or day > prev:
            latest[company] = day
    return [
        {
            "name": name,
            "aliases": _default_aliases(name),
            "last_successful_search": latest[name],
            "outcome": "created",
            "note": "",
        }
        for name in sorted(latest, key=str.lower)
    ]


def merge_company_search_log(existing: list[dict], created: list[dict]) -> list[dict]:
    """Upsert `created` from folders; keep `no_suitable` when it is strictly newer."""
    by_key: dict[str, dict] = {}
    for row in existing or []:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if name:
            by_key[_company_entry_key(name)] = dict(row)

    for entry in created:
        key = _company_entry_key(entry["name"])
        new_date = entry.get("last_successful_search") or ""
        if key not in by_key:
            by_key[key] = dict(entry)
            continue
        old = by_key[key]
        old_date = old.get("last_successful_search") or ""
        if new_date >= old_date:
            merged = dict(entry)
        elif old.get("outcome") == "no_suitable":
            continue
        else:
            merged = dict(old)
            merged["aliases"] = sorted(
                {str(a).strip().lower() for a in (old.get("aliases") or [])}
                | {str(a).strip().lower() for a in (entry.get("aliases") or [])}
                - {key})
            by_key[key] = merged
            continue
        merged["aliases"] = sorted(
            {str(a).strip().lower() for a in (old.get("aliases") or [])}
            | {str(a).strip().lower() for a in (merged.get("aliases") or [])}
            - {key})
        if old.get("note") and not merged.get("note"):
            merged["note"] = old["note"]
        by_key[key] = merged

    return sorted(by_key.values(), key=lambda x: (x.get("name") or "").lower())


def write_company_search_log(data: dict) -> Path:
    COMPANY_SEARCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "skip_within_days": data.get("skip_within_days", 7),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "companies": data.get("companies") or [],
    }
    COMPANY_SEARCH_LOG.write_text(
        COMPANY_SEARCH_LOG_HEADER
        + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=100))
    return COMPANY_SEARCH_LOG


def sync_company_search_log(apps: list[dict]) -> Path:
    """Upsert `created` entries from application folders into company-search-log.yaml."""
    raw = _load_company_search_log_raw()
    merged = merge_company_search_log(
        raw.get("companies") or [], build_created_search_entries(apps))
    raw["companies"] = merged
    return write_company_search_log(raw)


def log_company_search(
    company: str,
    outcome: str,
    *,
    search_date: str | None = None,
    note: str = "",
) -> Path:
    """Record a successful company search (`created` or `no_suitable`)."""
    if outcome not in ("created", "no_suitable"):
        print(f"Error: outcome must be 'created' or 'no_suitable', got '{outcome}'",
              file=sys.stderr)
        sys.exit(1)
    name = company.strip()
    if not name:
        print("Error: company name required", file=sys.stderr)
        sys.exit(1)
    day = search_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    raw = _load_company_search_log_raw()
    companies = list(raw.get("companies") or [])
    key = _company_entry_key(name)
    idx = next(
        (i for i, c in enumerate(companies)
         if _company_entry_key((c.get("name") or "")) == key),
        None,
    )
    row = {
        "name": name,
        "aliases": _default_aliases(name),
        "last_successful_search": day,
        "outcome": outcome,
        "note": note or "",
    }
    if idx is None:
        companies.append(row)
    else:
        old = companies[idx]
        old_date = old.get("last_successful_search") or ""
        if day >= old_date:
            row["aliases"] = sorted(
                {str(a).strip().lower() for a in (old.get("aliases") or [])}
                | set(_default_aliases(name))
                - {key})
            if not note and old.get("note"):
                row["note"] = old["note"]
            companies[idx] = row
        elif outcome == "created" and old.get("outcome") == "no_suitable":
            pass
        else:
            companies[idx] = old
    raw["companies"] = sorted(companies, key=lambda x: (x.get("name") or "").lower())
    return write_company_search_log(raw)


def sync_log() -> tuple[Path, Path]:
    """Regenerate applications-log.yaml and upsert company-search-log from folders."""
    apps = collect_apps()
    log = build_log(apps)
    APPLICATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Auto-generated by `skills/application-tracker/scripts/status.py --sync-log` from every application\n"
        "# folder across all status folders. Do not edit by hand — re-run --sync-log\n"
        "# after adding or moving applications.\n"
        "#\n"
        "# job-search skips a posting already listed here (matched by URL, else by\n"
        "# company + role). New roles at the same company are still surfaced.\n\n"
    )
    APPLICATIONS_LOG.write_text(
        header + yaml.safe_dump(log, sort_keys=False, allow_unicode=True, width=100))
    search_path = sync_company_search_log(apps)
    return APPLICATIONS_LOG, search_path


def main():
    parser = argparse.ArgumentParser(description="Application status tracker")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--update", nargs=2, metavar=("SLUG", "STATUS"),
                        help="Set EVERY posting's status to STATUS (stamping today's "
                             "status_date) and move the folder to match. Valid "
                             f"statuses: {', '.join(STATUS_FOLDERS)}")
    parser.add_argument("--update-job", nargs=3,
                        metavar=("SLUG", "ROLE_MATCH", "STATUS"),
                        help="Set ONE posting's status. ROLE_MATCH is a "
                             "case-insensitive substring of the role or a 1-based "
                             "index (must match exactly one posting). STATUS is one "
                             f"of {', '.join(STATUS_FOLDERS)}. Re-derives the "
                             "rollup and moves the folder if it changed.")
    parser.add_argument("--update-progress", nargs=2,
                        metavar=("SLUG", "ROLE_MATCH"),
                        help="Set ONE posting's structured progress (requires "
                             "--phase and --state; optional --label). Updates "
                             "meta.yaml and calendar.md together, transactionally; "
                             "NEVER moves the status folder.")
    parser.add_argument("--phase", default=None,
                        help=f"Hiring phase for --update-progress: "
                             f"{', '.join(PROGRESS_PHASES)}.")
    parser.add_argument("--state", default=None,
                        help=f"Workflow state for --update-progress: "
                             f"{', '.join(PROGRESS_STATES)}.")
    parser.add_argument("--label", default=None, metavar="TEXT",
                        help="Employer-specific wording to keep alongside the "
                             "normalized phase (required when --phase other; "
                             "omit to keep the current label, pass '' to clear).")
    parser.add_argument("--check-calendar", action="store_true",
                        help="Verify calendar.md (markers, duplicate ids, "
                             "scheduled time+timezone) and its cross-links with "
                             "per-job progress. Read-only.")
    parser.add_argument("--sync-calendar", action="store_true",
                        help="Preview how owner edits to calendar.md (checked "
                             "boxes, reschedule_to, cancel) map back to progress. "
                             "Add --write to apply transactionally.")
    parser.add_argument("--write", action="store_true",
                        help="With --sync-calendar: apply the previewed proposals.")
    parser.add_argument("--sync-log", action="store_true",
                        help="Regenerate applications/0_profile/applications-log.yaml "
                             "(the postings job-search skips) from all folders, and upsert "
                             "company-search-log.yaml created entries.")
    parser.add_argument("--enrich-metadata", metavar="SLUG_OR_PATH",
                        help="Safely insert missing schema-v5 per-posting metadata "
                             "(workplace, sponsorship, job level, YOE, salary).")
    parser.add_argument("--backfill-metadata", action="store_true",
                        help="Preview metadata enrichment across --statuses without "
                             "writing. Defaults to all status folders.")
    parser.add_argument("--write-metadata", action="store_true",
                        help="With --backfill-metadata, atomically persist verified "
                             "insert-only edits.")
    parser.add_argument("--check-metadata", action="store_true",
                        help="Validate structured job metadata. Defaults to all "
                             "status folders.")
    parser.add_argument("--log-search", metavar="COMPANY",
                        help="Record a successful company search for COMPANY.")
    parser.add_argument("--outcome", choices=["created", "no_suitable"],
                        help="Outcome for --log-search (required with --log-search).")
    parser.add_argument("--date", dest="search_date", metavar="YYYY-MM-DD",
                        help="Search date for --log-search (default: today UTC).")
    parser.add_argument("--check-locations", action="store_true",
                        help="Flag applications whose posting location is outside the "
                             "configured location policy (respects the search "
                             "criteria). Defaults to all status folders.")
    parser.add_argument("--statuses", default=None,
                        help="Comma-separated status folders for --check-locations, "
                             "--check-metadata, or --backfill-metadata "
                             f"(default: all). Options: {', '.join(STATUS_FOLDERS)}.")
    args = parser.parse_args()

    if args.update:
        update_status(args.update[0], args.update[1])
        return

    if args.update_job:
        update_job_status(args.update_job[0], args.update_job[1],
                          args.update_job[2])
        return

    if args.update_progress:
        if not args.phase or not args.state:
            print("Error: --update-progress requires --phase and --state",
                  file=sys.stderr)
            sys.exit(1)
        update_progress(args.update_progress[0], args.update_progress[1],
                        phase=args.phase, state=args.state, label=args.label)
        return

    if args.check_calendar:
        sys.exit(0 if check_calendar(as_json=args.json) else 1)

    if args.sync_calendar:
        sys.exit(0 if sync_calendar(write=args.write, as_json=args.json) else 1)

    if args.write:
        print("Error: --write requires --sync-calendar", file=sys.stderr)
        sys.exit(1)

    if args.enrich_metadata:
        try:
            path = enrich_application_metadata(
                args.enrich_metadata)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"Enriched job metadata -> {path}")
        return

    if args.backfill_metadata:
        statuses = _resolve_statuses(args)
        ok = backfill_metadata(
            statuses,
            write=args.write_metadata,
            as_json=args.json,
        )
        sys.exit(0 if ok else 1)

    if args.write_metadata:
        print("Error: --write-metadata requires --backfill-metadata",
              file=sys.stderr)
        sys.exit(1)

    if args.check_metadata:
        statuses = _resolve_statuses(args)
        ok = check_metadata(statuses, as_json=args.json)
        sys.exit(0 if ok else 1)

    if args.check_locations:
        statuses = _resolve_statuses(args)
        ok = check_locations(statuses, as_json=args.json)
        sys.exit(0 if ok else 1)

    if args.log_search:
        if not args.outcome:
            print("Error: --log-search requires --outcome created|no_suitable",
                  file=sys.stderr)
            sys.exit(1)
        path = log_company_search(
            args.log_search, args.outcome, search_date=args.search_date)
        print(f"Updated company search log -> {path}")
        return

    if args.sync_log:
        app_path, search_path = sync_log()
        print(f"Wrote application log -> {app_path}")
        print(f"Updated company search log -> {search_path}")
        return

    if not APPLICATIONS_DIR.exists():
        APPLICATIONS_DIR.mkdir(parents=True)

    apps = collect_apps()

    if args.json:
        print(json.dumps(apps, indent=2))
    else:
        print_table(apps)


if __name__ == "__main__":
    main()
