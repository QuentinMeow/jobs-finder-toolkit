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

Schema v6 adds a structured per-job ``progress`` summary ({phase, state,
label?, calendar_items?}) and ONE private calendar/todo file resolved by
``config.calendar_path()``. This tracker is the only writer that updates
metadata and calendar together — transactionally, both or neither. Changing
only phase/state NEVER moves an application between status folders. One role
may link several distinct calendar occurrences through the ordered
``calendar_items`` list.

Usage:
    python skills/application-tracker/scripts/status.py
    python skills/application-tracker/scripts/status.py --json
    python skills/application-tracker/scripts/status.py --update google-ml-engineer-20260416 applied
    python skills/application-tracker/scripts/status.py --update-job <slug> "Backend Engineer" in_progress
    python skills/application-tracker/scripts/status.py --update-job <slug> 2 rejected
    python skills/application-tracker/scripts/status.py --update-progress <slug> <role-match> --phase interview_loop --state scheduled --starts-at <ISO> --timezone <IANA>
    python skills/application-tracker/scripts/status.py --update-progress <slug> <role-match> --phase interview_loop --state scheduled --add-occurrence --starts-at <ISO> --timezone <IANA>
    python skills/application-tracker/scripts/status.py --check-calendar
    python skills/application-tracker/scripts/status.py --sync-calendar [--write]
    python skills/application-tracker/scripts/status.py --refresh-calendar [--write]
    python skills/application-tracker/scripts/status.py --enrich-metadata <slug>
    python skills/application-tracker/scripts/status.py --check-metadata
    python skills/application-tracker/scripts/status.py --sync-log
    python skills/application-tracker/scripts/status.py --backfill-log [--force]
    python skills/application-tracker/scripts/status.py --forget-log <posting-url>
    python skills/application-tracker/scripts/status.py --forget-log <company> <role>
    python skills/application-tracker/scripts/status.py --log-search "Example Corp" --outcome no_suitable [--date YYYY-MM-DD]
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple

import yaml

# Self-contained skill: this script lives in the application-tracker skill's
# scripts/ folder alongside its _vendor/ copies of the pure toolkit modules. Put
# both the script folder and its _vendor/ on sys.path and import ONLY from those
# vendored modules (config, layout, location) — no check/cover_letter dependency.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

import company_index
import config
import skip_log
from backfill_job_metadata import process_application
from calendar_todos import (
    CALENDAR_TEMPLATE,
    CHECKED_BOX_TRANSITIONS,
    STATE_SECTIONS,
    parse_calendar,
    plan_calendar_update,
    generate_entry_id,
    record_cancellation,
    record_completion,
    record_reschedule,
    render_company_view,
    render_company_view_html,
)
from job_metadata import (
    APPLICATION_SCHEMA_VERSION,
    PROGRESS_ACTION_STATES,
    PROGRESS_CALENDAR_STATES,
    PROGRESS_PHASES,
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
    atomic_write_text,
    plan_field_updates,
)

# Output filename stems are candidate-identity-derived, so they come from config
# (kept under their historical module-level names for the file-presence globs).
RESUME_STEM = config.resume_stem()
_NEUTRAL_EMAIL_REF_RE = re.compile(r"^acct-\d+/[0-9a-f]{64}$")
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
    uniformly at the current metadata schema. ``--statuses`` selects an explicit subset.
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
#
# APPLICATIONS_JSONL is the live one: an APPEND-ONLY event log, folded last-wins.
# Nothing rewrites it, so deleting an application folder no longer deletes its row
# and job-search will not re-surface a posting the owner already dealt with. That
# also makes it authoritative rather than derived — recovery from loss or
# corruption is git history, never a rebuild.
#
# APPLICATIONS_LOG is the retired YAML projection. It is still resolved because
# `--backfill-log` seeds from it once and names it in its output; nothing else in
# this file reads it and NOTHING writes it any more. It is not deleted or renamed
# — agents never delete owner data.
APPLICATIONS_LOG = config.applications_log_path()
APPLICATIONS_JSONL = config.applications_jsonl_path()
COMPANY_SEARCH_LOG = config.company_search_log_path()

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


_YAML_STREAM_NAME_RE = re.compile(r'\s*in "[^"]*",')


def _read_failure(filename: str, exc: BaseException) -> str:
    """One-line ``<file>: <reason>`` for a metadata file that could not be read.

    PyYAML's errors run to several lines (the offending snippet plus a caret) and
    name the stream, which would break every line-per-application table this module
    prints and repeat a path the row already carries. Collapse to one line, drop the
    stream name, keep the reason and the line/column.
    """
    message = _YAML_STREAM_NAME_RE.sub(" at", str(exc))
    return f"{filename}: {' '.join(message.split())}"


#: meta.yaml keys whose value is a calendar day. `yaml.safe_load` resolves an
#: UNQUOTED `research_date: 2026-07-02` to a `datetime.date`, not a string — the
#: file is valid YAML and says exactly the right day, but the loaded TYPE differs
#: from every other application's (theirs comes from the slug parse, or from a
#: quoted value). Every consumer in this module assumes `str`.
_DAY_FIELDS = ("research_date", "posted_date")


def _iso_day(value: object) -> str:
    """One meta.yaml day field as a ``YYYY-MM-DD`` string, whatever YAML made of it.

    ``skip_log.posting_row`` already stringifies non-string scalars for exactly
    this reason (its docstring names the unquoted ``research_date:``), which is
    why the skip-log write survives the value while the table and the company
    search log do not. Normalizing at the READ point instead means the coercion
    happens once, before anything derives from it, rather than once per consumer
    that remembers to. ``datetime`` is checked first because it subclasses
    ``date``.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def load_application(app_dir: Path, status: str) -> dict | None:
    """Load application metadata from a folder; status comes from the parent folder.

    A metadata file this function cannot parse is recorded as ``info["meta_error"]``
    — **never** silently treated as an absent or empty one. That distinction is the
    whole point: an unparseable ``meta.yaml`` still has a company, a location and a
    posting URL in it, and every consumer that treats the file as empty answers a
    question it has not actually looked at. The folder walk keeps going (one broken
    file must not blind the operator to the rest of the pipeline), so the caller
    decides what the error means:

    * a gate that claims to have inspected the application FAILS on it
      (``check_locations``);
    * anything that would DERIVE A WRITE from it refuses (``build_log`` and
      ``build_created_search_entries``, feeding the append-only skip-log and the
      company search log);
    * a read-only view marks the row and carries on (``print_table``).
    """
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
        meta_data = None
        try:
            with open(meta) as f:
                meta_data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            info["meta_error"] = _read_failure("meta.yaml", exc)
        if meta_data is not None and not isinstance(meta_data, dict):
            # `.get` on a list/scalar used to raise AttributeError straight into the
            # bare `except Exception`, so a meta.yaml holding a sequence looked
            # exactly like one holding nothing. check_metadata already calls this a
            # hard error; say the same thing here.
            info["meta_error"] = "meta.yaml: must contain a mapping"
        elif isinstance(meta_data, dict):
            # The folder is the derived overall status; pull everything else from
            # meta.yaml. Structured job facts (job_level/required_yoe/salary_range)
            # and the per-job status/stage/status_date live per posting under
            # `jobs`, so they are read from there, not the top level. The top-level
            # retired `stage` field was replaced by the structured per-job `progress`.
            # `company_key` is surfaced beside `company`, never instead of it: the
            # grouping and skip paths keep comparing the free-text company string.
            for key in ["company", "company_key", "role", "research_date",
                        "posted_date",
                        "channel", "referrer", "next_action", "notes", "location",
                        "recruiter_email", "comp_notes", "url", "jobs",
                        "job_metadata_schema_version"]:
                if meta_data.get(key):
                    info[key] = (_iso_day(meta_data[key]) if key in _DAY_FIELDS
                                 else meta_data[key])

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
    # slug-derived date (parsed above). Already normalized to a `YYYY-MM-DD`
    # string by `_iso_day`, so `info["date"]` is a `str` for EVERY application —
    # the invariant `print_table`'s sort key and `build_created_search_entries`'
    # `.strip()` both assume, and which an unquoted YAML date used to break for
    # one row out of forty.
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

    # Fallback: try to get role from tailored.yaml. Reached only when meta.yaml
    # supplied neither a `jobs` list nor a top-level `role`, so the role this
    # branch finds is the ONLY role the application has — and `build_log` folds a
    # URL-less posting by (company, role), which makes it part of a skip-log
    # identity. An unparseable file here is therefore recorded exactly like an
    # unparseable meta.yaml rather than left as an empty role.
    if not info["role"] and not info.get("meta_error"):
        tailored = tailored_path(app_dir)
        if tailored.exists():
            try:
                with open(tailored) as f:
                    td = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError) as exc:
                info["meta_error"] = _read_failure("source/tailored.yaml", exc)
            else:
                if isinstance(td, dict):
                    info["role"] = td.get("title", td.get("name", ""))
                else:
                    info["meta_error"] = (
                        "source/tailored.yaml: must contain a mapping")

    return info


def job_location_strings(job: dict, app_dir: Path) -> list[str]:
    """ONE posting's location string(s): its own ``location``, else its own JD's.

    The tracker's copy of ``handoff.job_locations``, and deliberately the same
    two-step chain rather than a wider one. ``jobs[].jd_file`` is the exact
    one-to-one mapping from a posting to the verbatim JD saved for it, so a
    posting that recorded no ``location`` is still assessed from the
    ``Location:`` line sitting in its own JD — not skipped because a SIBLING
    posting in the same folder happened to record one.

    There is no fall-back to the folder's top-level ``location``: for a posting
    that says nothing about where it is, the folder's summary line is a guess,
    and a guess here is what this whole change exists to stop. An unlocatable
    posting comes back with no strings, is classified ``unknown``, and lands in
    ``review`` — which never fails the check.
    """
    loc = str(job.get("location") or "").strip()
    if loc:
        return [loc]
    name = str(job.get("jd_file") or "").strip()
    # Reject a path, not just a missing name: `jd_file` is a bare filename by
    # schema, and joining an arbitrary one would read outside the application.
    if not name or Path(name).name != name:
        return []
    for directory in (source_dir(app_dir), app_dir):
        try:
            return extract_jd_locations((directory / name).read_text())
        except OSError:
            continue
    return []


def app_locations(info: dict, app_dir: Path) -> list[str]:
    """Every posting-location string for an application, in ``jobs:`` order.

    For a ``jobs:`` application this is the per-posting gather above, so a
    blank-``location`` posting contributes its own JD's location instead of
    being invisible in the LOCATIONS column. The pre-``jobs`` shape (a top-level
    ``location``, else the pooled ``Location:`` lines of whatever JD files are in
    the folder) is unchanged — there is no posting to attribute a location to.
    """
    jobs = info.get("jobs")
    if isinstance(jobs, list) and jobs:
        locs: list[str] = []
        for job in jobs:
            if isinstance(job, dict):
                locs.extend(job_location_strings(job, app_dir))
        return locs
    top = str(info.get("location") or "").strip()
    if top:
        return [top]
    locs = []
    for jd in find_jd_files(app_dir):
        try:
            locs.extend(extract_jd_locations(jd.read_text()))
        except OSError:
            continue
    return locs


#: Worst-first ordering of a posting's location decision. `no_match` is a
#: definite policy violation, `review` is "we could not tell", `match` clears.
_LOCATION_DECISION_RANK = {"no_match": 0, "review": 1, "match": 2}


class AppLocationRollup(NamedTuple):
    """One application's location verdict, and the postings that decided it."""

    #: The WORST posting's assessment — the folder's verdict.
    assessment: object
    #: ``(role, locations, assessment)`` per posting, in ``jobs:`` order.
    postings: tuple

    def _by_decision(self, decision: str) -> list[tuple]:
        return [(role, locs) for role, locs, a in self.postings
                if a.decision == decision]

    @property
    def offending(self) -> list[tuple]:
        """``(role, locations)`` for each posting outside the location policy."""
        return self._by_decision("no_match")

    @property
    def unclassified(self) -> list[tuple]:
        """``(role, locations)`` for each posting whose location could not be read."""
        return self._by_decision("review")


def app_location_assessment(info: dict, app_dir: Path) -> AppLocationRollup:
    """Assess EVERY posting with its own evidence; the WORST verdict wins.

    This used to roll the per-posting assessments up best-match-wins — the first
    ``match`` returned, then the first ``review``. That answers "could I take
    SOME job at this employer?", which is the right question for a single-role
    folder and the wrong one for the multi-role folder ``handoff.py`` now builds
    by default: one Springfield posting made a London sibling in the same folder
    report ``ok / metro``, and ``--check-locations`` — the command AGENTS.md names
    as the way to verify the location guardrail — exited 0 over it.

    AGENTS.md's policy governs a POSTING ("only draft a role whose ``location``
    matches"); a folder is just the container one resume covers. So each posting
    is assessed from its own ``location``/``jd_file``/``workplace`` and the
    folder takes the worst verdict, mirroring ``handoff.check_location_policy``,
    which settled this rule at creation time. ``review`` still ranks above
    ``no_match`` and still does not fail the check — a genuinely unknown location
    blocking legitimate work is the expensive direction.
    """
    policy = config.location_policy()
    postings: list[tuple] = []
    jobs = info.get("jobs")
    if isinstance(jobs, list) and jobs:
        for job in jobs:
            if not isinstance(job, dict):
                continue
            jd_text = ""
            jd_file = str(job.get("jd_file") or "").strip()
            if jd_file and Path(jd_file).name == jd_file:
                try:
                    jd_text = (source_dir(app_dir) / jd_file).read_text()
                except OSError:
                    pass
            locs = job_location_strings(job, app_dir)
            postings.append((
                str(job.get("role") or "").strip() or "(unnamed posting)",
                locs,
                assess_location(
                    # A posting with no `location` of its own is assessed from
                    # the location line in its OWN JD, the same string
                    # `job_location_strings` reports in the table.
                    job.get("location") or (locs[0] if locs else ""),
                    policy,
                    title=job.get("role"),
                    description=jd_text,
                    workplace_hint=job.get("workplace"),
                ),
            ))
    else:
        jd_texts = []
        for jd_path in find_jd_files(app_dir):
            try:
                jd_texts.append(jd_path.read_text())
            except OSError:
                continue
        postings.append((
            str(info.get("role") or "").strip() or "(unnamed posting)",
            app_locations(info, app_dir),
            assess_location(
                info.get("location"),
                policy,
                title=info.get("role"),
                description="\n".join(jd_texts),
            ),
        ))

    if not postings:
        return AppLocationRollup(assess_location("", policy), ())
    worst = min(postings,
                key=lambda p: _LOCATION_DECISION_RANK.get(p[2].decision, 0))[2]
    return AppLocationRollup(worst, tuple(postings))


def _resolve_application_target(target: str | Path) -> Path | None:
    """Resolve a slug or application-folder path."""
    p = Path(target)
    if p.exists():
        return application_dir(p)
    return find_application(str(target))


def enrich_application_metadata(target: str | Path, *, overwrite: bool = False) -> Path:
    """Safely insert missing current-schema job metadata into one ``meta.yaml``."""
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
            "current-schema fields"
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


def _raw_company_key(app_dir: Path) -> object:
    """The ``company_key`` as WRITTEN in ``meta.yaml``, falsy values included.

    ``load_application`` copies a field only ``if meta_data.get(key)``, so ``""``,
    ``false`` and ``0`` vanish there and an application carrying one looked exactly
    like an application carrying none. Both other validators call those a hard
    error, so the coverage report was the only one of the three giving that tree a
    clean bill of health. Absent, unreadable and unparseable all return ``None``:
    ``meta.yaml``'s own schema is ``job_metadata``'s business, and an unparseable
    file has no key to report.
    """
    meta = app_dir / "meta.yaml"
    if not meta.is_file():
        return None
    try:
        data = yaml.safe_load(meta.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data.get("company_key") if isinstance(data, dict) else None


def company_keys_report(statuses: list[str], *, strict: bool = False,
                        as_json: bool = False) -> bool:
    """Report company-key COVERAGE. Coverage is a number, never a gate.

    Deliberately fail-open but LOUD on COVERAGE. An application is scaffolded
    without a key and keyed later, so demanding one would block unrelated work in
    the window between the two; instead the unkeyed count is printed, which is a
    number a human reads rather than a silence a human misses.

    What is never open is CORRECTNESS, and there are two ways to be incorrect —
    kept apart because an unkeyed application and a broken one must not report the
    same number:

      * **malformed** — present but not a company key: ``""``, ``false``, ``0``,
        ``"acme-labs\\n"``. ``job_metadata.validate_meta`` calls each of these an
        ERROR and the reconciler calls each a FINDING, so this report agreeing with
        them is the whole point. Shape is tested with ``company_index.KEY_RE``, the
        same regex both of the others use;
      * **unresolved** — a well-shaped key that is not in the index.

    ``--strict`` exits 1 on either. An absent, empty, or unreadable index is
    reported as such and every present key is then counted unresolved rather than
    wrong — "cannot check" is not "checked and clean".
    """
    # The market index path is a repo-root-relative LITERAL, not
    # `config.companies_root()` (the interview-prep tree).
    # Under the example config that accessor resolves into `examples/`, so routing
    # through it would one day check a placeholder index and report a clean bill of
    # health for a tree that was never inspected — the same trap documented at
    # `automation/publish/review_gate.py`. `JOBHUNT_COMPANY_INDEX` overrides it, for
    # tests and for checking a proposed index before it is committed.
    override = os.environ.get("JOBHUNT_COMPANY_INDEX", "").strip()
    index_path = (Path(override) if override
                  else Path(config.REPO_ROOT) / company_index.DEFAULT_REL)
    # ``exists() or is_symlink()``, not ``is_file()``: a directory or a dangling
    # symlink here is a broken overlay, not a missing one, and reporting it as
    # "no index" was a clean bill of health for a tree nothing had read.
    index_present = index_path.exists() or index_path.is_symlink()
    index: dict = {}
    index_error = ""
    index_empty = False
    if index_present:
        try:
            raw = company_index.read_raw(index_path)
            # ``read_raw`` returns None for an EMPTY file. 0 keys is what a
            # truncated file reports too, so it is named rather than counted.
            index_empty = raw is None or not raw
            index = company_index.from_raw(raw)
        except Exception as exc:      # malformed YAML, unreadable or not-a-file
            index_error = f"{type(exc).__name__}: {exc}"

    rows: list[dict] = []
    for status in statuses:
        status_dir = _status_dir(status)
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            if not app_dir.is_dir() or app_dir.name.startswith("."):
                continue
            info = load_application(app_dir, status)
            raw_key = _raw_company_key(app_dir)
            well_formed = (isinstance(raw_key, str)
                           and bool(company_index.KEY_RE.match(raw_key)))
            rows.append({
                "slug": app_dir.name,
                "status": status,
                "company": str(info.get("company") or "").strip(),
                "company_key": raw_key if well_formed else "",
                # Absent is unkeyed; present-but-not-a-key is malformed. The two are
                # different defects and the report must not merge them.
                "malformed": None if raw_key is None else (not well_formed),
                "raw_key": raw_key,
                # Unknown, not clean, when the index could not be read.
                "resolves": well_formed and bool(index) and raw_key in index,
            })

    malformed = [r for r in rows if r["malformed"]]
    keyed = [r for r in rows if r["company_key"]]
    unkeyed = [r for r in rows if r["malformed"] is None]
    unresolved = [r for r in keyed if not r["resolves"]]
    distinct_companies = {r["company"].casefold() for r in rows if r["company"]}
    distinct_keys = {r["company_key"] for r in keyed}
    ok = not (unresolved or malformed) if strict else True

    if as_json:
        print(json.dumps({
            "index_path": str(index_path),
            "index_present": index_present,
            "index_empty": index_empty,
            "index_error": index_error,
            "index_keys": len(index),
            "applications": len(rows),
            "distinct_companies": len(distinct_companies),
            "keyed": len(keyed),
            "distinct_keys": len(distinct_keys),
            "unkeyed": [r["slug"] for r in unkeyed],
            "malformed": [{"slug": r["slug"], "company_key": repr(r["raw_key"])}
                          for r in malformed],
            "unresolved": [{"slug": r["slug"], "company_key": r["company_key"]}
                           for r in unresolved],
            "strict": strict,
            "ok": ok,
        }, indent=2))
        return ok

    print(f"company keys: {len(rows)} applications, "
          f"{len(distinct_companies)} distinct company strings")
    print(f"  keyed:       {len(keyed):<4} ({len(distinct_keys)} distinct keys)")
    print(f"  unkeyed:     {len(unkeyed):<4} -> listed below"
          if unkeyed else f"  unkeyed:     {len(unkeyed)}")
    print(f"  malformed:   {len(malformed):<4} -> company_key present but not a key"
          f"{' (FAIL under --strict)' if malformed else ''}")
    print(f"  unresolved:  {len(unresolved):<4} -> company_key not in the index"
          f"{' (FAIL under --strict)' if unresolved else ''}")
    if not index_present:
        print(f"\n  index not found at {company_index.DEFAULT_REL} — the company "
              "index is private and is absent in any checkout without the "
              "overlay. Resolution was NOT checked.")
    elif index_error:
        print(f"\n  index at {company_index.DEFAULT_REL} could not be read "
              f"({index_error}). Resolution was NOT checked.")
    elif index_empty:
        print(f"\n  index at {company_index.DEFAULT_REL} is EMPTY (0 entries) — "
              "that is what a truncated or half-written file reports too. "
              "Resolution was NOT checked.")
    if unkeyed:
        print("\n  unkeyed applications:")
        for r in unkeyed:
            print(f"    {r['slug']}  ({r['status']})")
    if malformed:
        print("\n  malformed company_key values — not a lowercase index key "
              "([a-z0-9-], no whitespace); fix the meta.yaml:")
        for r in malformed:
            print(f"    {r['slug']}  ->  {r['raw_key']!r}")
    if unresolved:
        print("\n  unresolved keys — add them to the index, or correct the "
              "application:")
        for r in unresolved:
            print(f"    {r['slug']}  ->  {r['company_key']}")
    return ok


def check_locations(statuses: list[str], as_json: bool = False) -> bool:
    """Flag applications whose posting location is outside the configured location policy.

    **Scored per POSTING, worst-wins** (see ``app_location_assessment``): a folder
    holding one in-policy and one foreign posting is a mismatch, and the offending
    posting is named by role. A row is a *mismatch* (hard failure) only when a
    posting's location is a definite place outside the policy — a foreign location
    or a non-preferred US office. An *unknown* row (blank or unrecognized location)
    is surfaced for manual review but is NOT a policy violation, so it does not
    fail the check.

    An **unreadable** row is a third bucket and a hard failure. `AGENTS.md` names
    this command as the way to verify the location guardrail, so a row whose
    metadata would not parse is one this command did not actually inspect — the
    file can say ``location: London, UK`` in plain text while the assessment sees
    none of it. It is not merely "unknown" either: with meta.yaml unreadable the
    location falls back to whatever the JD file happens to say, which can come
    back *matching*. Unreadable rows are therefore classified first and are never
    scored as match, mismatch or review. Returns True when there are neither
    mismatches nor unreadable rows.
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
            rollup = app_location_assessment(info, app_dir)
            assessment = rollup.assessment
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
                "locations": [loc for _role, locs, _a in rollup.postings
                              for loc in locs],
                # Per posting, so a mismatch names the ROLE that caused it rather
                # than collapsing the folder to one category and one location list.
                "postings": [
                    {"role": role, "locations": locs, "category": a.category,
                     "decision": a.decision, "workplace": a.workplace}
                    for role, locs, a in rollup.postings
                ],
                "offending": [{"role": role, "locations": locs}
                              for role, locs in rollup.offending],
                "unclassified": [{"role": role, "locations": locs}
                                 for role, locs in rollup.unclassified],
                "meta_error": info.get("meta_error", ""),
            })

    # Unreadable first: such a row's assessment was built from an incomplete
    # picture, so whatever decision it carries — including "match" — means nothing.
    unreadable = [r for r in rows if r["meta_error"]]
    inspected = [r for r in rows if not r["meta_error"]]
    non_matching = [r for r in inspected if not r["match"]]
    # Split non-matching rows into definite policy violations (foreign / non-preferred
    # US office) and "unknown" rows (blank / unrecognized location). Only the former
    # fail the check; the latter are surfaced for manual review.
    mismatches = [r for r in non_matching if r["decision"] == "no_match"]
    review = [r for r in non_matching if r["decision"] == "review"]
    ok = not mismatches and not unreadable

    if as_json:
        print(json.dumps({
            "rows": rows,
            "non_matching": non_matching,
            "mismatches": mismatches,
            "review": review,
            "unreadable": unreadable,
        }, indent=2))
        return ok

    if not rows:
        print(f"No applications found under: {', '.join(statuses)}")
        return True

    width = max((len(r["slug"]) for r in rows), default=4)
    print("\u2500" * (width + 40))
    print(f"{'SLUG':<{width}}  {'MATCH':<5}  {'CATEGORY':<13}  LOCATIONS")
    print("\u2500" * (width + 40))
    for r in sorted(rows, key=lambda x: (not x["meta_error"], x["match"], x["slug"])):
        if r["meta_error"]:
            mark, category = "ERR", "unreadable"
        else:
            mark, category = ("ok" if r["match"] else "NO"), r["category"]
        loc = " | ".join(r["locations"]) if r["locations"] else "(none recorded)"
        print(f"{r['slug']:<{width}}  {mark:<5}  {category:<13}  {loc}")
    print("\u2500" * (width + 40))
    print(f"Total: {len(rows)}  |  match: {len(inspected) - len(non_matching)}  "
          f"|  mismatch: {len(mismatches)}  |  review: {len(review)}  "
          f"|  unreadable: {len(unreadable)}")
    if unreadable:
        print("\nUnreadable (metadata would not parse \u2014 location NOT inspected):")
        for r in unreadable:
            print(f"  - {r['slug']}  {r['meta_error']}")
        print("  Fix each file (--check-metadata names the same errors), then "
              "re-run. Until then this gate cannot clear these applications.")
    if mismatches:
        print("\nMismatches (outside the configured location policy):")
        for r in mismatches:
            print(f"  - {r['slug']}  [{r['category']}]  "
                  f"{' | '.join(r['locations']) or '(none recorded)'}")
            # The folder verdict is the worst POSTING's, so say which posting.
            # Without this a mixed folder reads as wholly out of policy, and the
            # owner cannot tell which cover letter to stop writing.
            for p in r["offending"]:
                print(f"      offending posting: {p['role']}: "
                      f"{' | '.join(p['locations']) or '(none recorded)'}")
    if review:
        print("\nReview (blank / unrecognized location \u2014 not a policy failure):")
        for r in review:
            print(f"  - {r['slug']}  [{r['category']}]  "
                  f"{' | '.join(r['locations']) or '(none recorded)'}")
            for p in r["unclassified"]:
                print(f"      not classifiable: {p['role']}: "
                      f"{' | '.join(p['locations']) or '(none recorded)'}")
    return ok


def find_application(slug: str) -> Path | None:
    """Return the current path of an application by slug, searching status folders."""
    for status in STATUS_FOLDERS:
        candidate = _status_dir(status) / slug
        if candidate.is_dir():
            return candidate
    return None


def _load_current_meta(meta_path: Path) -> tuple[dict, bytes]:
    """Load meta.yaml, failing loud unless it matches the current schema."""
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
              f"run migrate_to_v{APPLICATION_SCHEMA_VERSION}.py before updating status",
              file=sys.stderr)
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


def _calendar_html_path() -> Path:
    """Optional generated companion beside the canonical Markdown calendar."""
    return _calendar_path().with_suffix(".html")


def _details_reference(meta_path: Path, *, source_meta_path: Path | None = None) -> str:
    """Relative role-context link for the human calendar row."""
    target = meta_path.parent / "notes.md"
    source_notes = source_meta_path.parent / "notes.md" if source_meta_path else None
    if not target.is_file() and not (source_notes and source_notes.is_file()):
        target = meta_path
    return Path(os.path.relpath(target, start=_calendar_path().parent)).as_posix()


_EMAIL_TIMELINE_HEADING_RE = re.compile(r"^## Email Timeline\s*$", re.MULTILINE)
_EMAIL_ENTRY_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


def _latest_standardized_note(notes_path: Path, *, details: str) -> dict | None:
    """Read the latest standardized Email Timeline item, never arbitrary prose.

    The email-assistant contract keeps this section reverse chronological and
    gives each item a ``Summary`` plus ``Outcome / next step``. Prefer the
    outcome because it expresses the current company-level workflow; fall back
    to the concise summary when the outcome is absent.
    """
    try:
        text = notes_path.read_text(encoding="utf-8")
    except OSError:
        return None
    timeline = _EMAIL_TIMELINE_HEADING_RE.search(text)
    if timeline is None:
        return None
    section = text[timeline.end():]
    next_section = re.search(r"^##\s+", section, re.MULTILINE)
    if next_section:
        section = section[:next_section.start()]
    entry = _EMAIL_ENTRY_HEADING_RE.search(section)
    if entry is None:
        return None
    entry_body = section[entry.end():]
    next_entry = _EMAIL_ENTRY_HEADING_RE.search(entry_body)
    if next_entry:
        entry_body = entry_body[:next_entry.start()]
    value = None
    for field in ("Outcome / next step", "Summary"):
        match = re.search(
            rf"^- \*\*{re.escape(field)}:\*\*\s*(.+?)\s*$",
            entry_body,
            re.MULTILINE,
        )
        if match:
            value = " ".join(match.group(1).split())
            break
    if not value:
        return None
    return {
        "heading": " ".join(entry.group(1).split()),
        "summary": value,
        "details": details,
        "source_kind": "email_timeline",
    }


def _company_view_data(
    meta_overrides: dict[Path, tuple[bytes, Path]] | None = None,
    calendar_overrides: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict], dict | None, list[str]]:
    """Build a deterministic read-only projection of all in-progress companies.

    Overrides map a current ``meta.yaml`` path to prospective bytes and the
    path it will have after a status-folder move. This lets a calendar write and
    its metadata transition agree before either reaches disk.
    """
    overrides = meta_overrides or {}
    grouped: dict[str, dict] = {}
    errors: list[str] = []
    calendar_rows: dict[str, dict] = {}
    agenda_items: list[dict] = []
    availability: dict | None = None
    calendar_raw = _read_calendar_raw()
    if calendar_raw is not None:
        try:
            calendar_doc = parse_calendar(calendar_raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            errors.append(f"{_calendar_path()}: cannot build company view: {exc}")
        else:
            errors.extend(
                f"{_calendar_path()}: cannot build company view: {error}"
                for error in calendar_doc.errors
            )
            if not calendar_doc.errors:
                calendar_rows = {
                    item: entry.fields()
                    for item, entry in calendar_doc.entries.items()
                }
                agenda_items = list(calendar_doc.agenda_items)
                availability = calendar_doc.availability
    calendar_rows.update(calendar_overrides or {})
    seen: set[Path] = set()
    for status in STATUS_FOLDERS:
        status_dir = _status_dir(status)
        if not status_dir.is_dir():
            continue
        for app_dir in sorted(status_dir.iterdir()):
            meta_path = app_dir / "meta.yaml"
            if not app_dir.is_dir() or not meta_path.is_file() or meta_path in seen:
                continue
            seen.add(meta_path)
            override = overrides.get(meta_path)
            raw = override[0] if override else None
            display_meta_path = override[1] if override else meta_path
            try:
                meta = yaml.safe_load(
                    raw.decode("utf-8") if raw is not None
                    else meta_path.read_text(encoding="utf-8")
                ) or {}
                jobs = meta.get("jobs") if isinstance(meta, dict) else None
                overall = derive_status(jobs)
            except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
                if status == "in_progress" or override is not None:
                    errors.append(f"{meta_path}: cannot build company view: {exc}")
                continue
            if overall != "in_progress":
                continue

            company = str(meta.get("company") or app_dir.name).strip() or app_dir.name
            key = company.casefold()
            company_row = grouped.setdefault(key, {
                "company": company,
                "applications": [],
            })
            details = _details_reference(
                display_meta_path, source_meta_path=meta_path)
            latest_note = _latest_standardized_note(
                meta_path.parent / "notes.md", details=details)
            roles = []
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                progress = job.get("progress") \
                    if isinstance(job.get("progress"), dict) else {}
                source = progress.get("source") \
                    if isinstance(progress.get("source"), dict) else {}
                calendar_items = [
                    calendar_rows[item]
                    for item in _progress_calendar_items(progress)
                    if item in calendar_rows
                ]
                actions = [
                    {
                        "state": item.get("state"),
                        "action": item.get("action"),
                        "due_at": item.get("due_at"),
                        "follow_up_at": item.get("follow_up_at"),
                        "timezone": item.get("timezone"),
                    }
                    for item in calendar_items
                    if item.get("state") in PROGRESS_ACTION_STATES
                ]
                if not actions and progress.get("state") in PROGRESS_ACTION_STATES:
                    # Metadata remains the authority even before an owner has
                    # added optional action wording or a due date to its entry.
                    actions.append({"state": progress.get("state")})
                roles.append({
                    "role": str(job.get("role") or "Tracked role"),
                    "status": str(job.get("status") or ""),
                    "phase": str(progress.get("phase") or ""),
                    "state": str(progress.get("state") or "unknown"),
                    "label": str(progress.get("label") or ""),
                    "updated_at": (
                        progress.get("updated_at")
                        or job.get("status_date")
                        or meta.get("research_date")
                    ),
                    "source_kind": str(source.get("kind") or "metadata"),
                    "details": details,
                    "interviews": [
                        {
                            "starts_at": item.get("starts_at"),
                            "ends_at": item.get("ends_at"),
                            "timezone": item.get("timezone"),
                            "label": item.get("label"),
                            "action": item.get("action"),
                            "display_rounds": item.get("display_rounds") or [],
                        }
                        for item in calendar_items
                        if item.get("state") == "scheduled" and item.get("starts_at")
                    ],
                    "actions": actions,
                })
            if latest_note is None:
                next_action = str(meta.get("next_action") or "").strip()
                if next_action:
                    latest_note = {
                        "heading": "Date not recorded",
                        "summary": " ".join(next_action.split()),
                        "details": details,
                        "source_kind": "human",
                    }
                elif roles:
                    latest_role = max(
                        roles,
                        key=lambda item: str(item.get("updated_at") or ""),
                    )
                    stage = str(
                        latest_role.get("label")
                        or latest_role.get("phase")
                        or "progress unknown"
                    ).replace("_", " ").strip().title()
                    state = str(
                        latest_role.get("state") or "unknown"
                    ).replace("_", " ").strip().title()
                    latest_note = {
                        "heading": str(
                            latest_role.get("updated_at") or "Date not recorded"),
                        "summary": (
                            f"{latest_role.get('role')}: {stage} — {state}."),
                        "details": details,
                        "source_kind": "metadata",
                    }
            company_row["applications"].append({
                "application": app_dir.name,
                "latest_note": latest_note,
                "roles": roles,
            })

    for row in grouped.values():
        row["applications"].sort(key=lambda item: item["application"])
    companies = sorted(grouped.values(), key=lambda item: item["company"].casefold())
    return companies, agenda_items, availability, errors


def _company_view_markdown(
    meta_overrides: dict[Path, tuple[bytes, Path]] | None = None,
    calendar_overrides: dict[str, dict] | None = None,
) -> tuple[str, int, list[str]]:
    companies, agenda_items, availability, errors = _company_view_data(
        meta_overrides, calendar_overrides)
    return render_company_view(
        companies, agenda_items, availability_config=availability,
    ), len(companies), errors


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
    entry, *, slug: str, job: dict, progress: dict, company: str,
    meta_path: Path, calendar_item: str,
) -> dict:
    """Merge a job's new progress summary into its calendar entry fields."""
    if entry is not None:
        fields = entry.fields()
    else:
        fields = {
            "id": calendar_item,
            "application": slug,
            "role": str(job.get("role") or ""),
            "action": None,
            "due_at": None,
            "starts_at": None,
            "ends_at": None,
            "timezone": None,
            "follow_up_at": None,
            "details": None,
            "source": "manual",
            "reschedule_to": None,
            "reschedule_timezone": None,
            "cancel": False,
            "history": [],
        }
    # The application folder or role may have been corrected since this stable
    # calendar occurrence was created.  Identity follows current metadata just
    # like phase/state do; preserving the stale values makes --check-calendar
    # fail after an otherwise valid rename.
    fields["application"] = slug
    fields["role"] = str(job.get("role") or "")
    fields["phase"] = progress.get("phase")
    fields["state"] = progress.get("state")
    fields["label"] = progress.get("label")
    fields["details"] = _details_reference(meta_path)
    if entry is not None and entry.state != progress.get("state") \
            and progress.get("state") not in PROGRESS_ACTION_STATES:
        fields["action"] = None
        fields["due_at"] = None
    source = progress.get("source") if isinstance(progress.get("source"), dict) else {}
    if source.get("kind") == "email" and str(source.get("ref") or "").strip():
        fields["source"] = f"email:{str(source['ref']).strip()}"
    fields["_company"] = company
    return fields


def _progress_calendar_items(progress: dict | None) -> list[str]:
    """Return the ordered occurrence ids from one schema-v6 progress mapping."""
    if not isinstance(progress, dict):
        return []
    values = progress.get("calendar_items")
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


_CALENDAR_STATE_PRIORITY = (
    "reschedule_required",
    "booking_required",
    "action_required",
    "decision_required",
    "follow_up_required",
    "in_progress",
    "scheduled",
    "reschedule_pending",
    "awaiting_schedule",
    "awaiting_result",
    "waiting_employer",
    "paused",
    "unknown",
    "closed",
)


def _occurrence_terminal_status(fields) -> str | None:
    """Return completed/cancelled for a terminal occurrence, else ``None``."""
    history = (
        fields.get("history")
        if isinstance(fields, dict)
        else getattr(fields, "history", ())
    ) or []
    starts_at = (
        fields.get("starts_at")
        if isinstance(fields, dict)
        else getattr(fields, "starts_at", None)
    )
    if starts_at or not history or not isinstance(history[-1], dict):
        return None
    status = history[-1].get("status")
    return status if status in {"completed", "cancelled"} else None


def _reduce_calendar_occurrences(occurrences: list, *, fallback: str) -> str:
    """Reduce occurrence-local lifecycle into one role-level progress state.

    Owner action outranks a confirmed future slot; otherwise any remaining
    scheduled occurrence keeps the role scheduled.  The role reaches
    ``awaiting_result`` only after every linked occurrence has advanced there.
    """
    active = [item for item in occurrences if _occurrence_terminal_status(item) is None]
    normalized = [
        str(item.get("state") if isinstance(item, dict) else getattr(item, "state", ""))
        for item in active
    ]
    normalized = [state for state in normalized if state in PROGRESS_STATES]
    if not normalized:
        terminal = [_occurrence_terminal_status(item) for item in occurrences]
        if "completed" in terminal:
            return "awaiting_result"
        if "cancelled" in terminal:
            return "action_required"
        return fallback
    for candidate in _CALENDAR_STATE_PRIORITY:
        if candidate in normalized:
            return candidate
    return fallback


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


def _record_log_events(slug: str) -> None:
    """Append this application's postings to the append-only skip-log.

    This replaces the old "re-run --sync-log" reminder. A reminder left the log a
    lagging projection of whatever the folders looked like the last time somebody
    remembered to sync; appending at the moment of the status write makes it an
    event log. The rows are built through ``build_log`` — the same call
    ``--sync-log`` makes, over the same ``skip_log.posting_rows`` flattening that
    job-search's ``handoff.py`` uses when it scaffolds a folder — so no writer can
    drift apart in shape from the others.

    Called unconditionally rather than only when something changed: the upsert
    appends nothing when the posting already matches the fold, and the FIRST
    ``--update`` on a posting that predates the log is exactly the case a
    "changed?" guard would skip.
    """
    app_dir = find_application(slug)
    if app_dir is None:
        return
    info = load_application(app_dir, status_label_for_dir(app_dir.parent.name) or "")
    if not info:
        return
    log = build_log([info])
    if log["unreadable"]:
        # Belt and braces: --update / --update-job already fail loud through
        # _load_current_meta, so an unparseable file cannot reach this point today. The
        # guard stays because the cost of it being wrong is a permanent log row.
        print(f"Warning: no skip-log row recorded for {slug} — "
              f"{log['unreadable'][0]['error']}", file=sys.stderr)
        return
    appended = _upsert_log_rows(log["postings"], source="update")
    if appended:
        print(f"Recorded {appended} posting event(s) -> {APPLICATIONS_JSONL}")


def _transition_calendar_plan(
    slug: str, company: str, jobs_progress: list[tuple[dict, dict]],
    *, source_meta_path: Path, prospective_meta: bytes, target_meta_path: Path,
):
    """Plan entry changes plus the generated company view transactionally.

    ``jobs_progress`` pairs each affected job dict with its NEW progress
    summary. The company view is also rendered from the prospective metadata,
    so entering/leaving ``in_progress`` cannot leave it stale. Returns ``None``
    only when no calendar exists, no entry is referenced, and the generated
    view is empty.
    """
    referencing = [
        (job, progress, item)
        for job, progress in jobs_progress
        for item in _progress_calendar_items(progress)
    ]
    overrides = {source_meta_path: (prospective_meta, target_meta_path)}
    raw = _read_calendar_raw()
    if raw is None and referencing:
        raw = _read_calendar_raw(create=True)
    doc = parse_calendar(
        raw.decode("utf-8") if raw is not None else CALENDAR_TEMPLATE)
    if doc.errors:
        print(f"Error: calendar file {_calendar_path()} failed validation:",
              file=sys.stderr)
        for error in doc.errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    upserts: dict[str, dict] = {}
    for job, progress, item in referencing:
        entry = doc.entries.get(item)
        if entry is None:
            print(f"Error: {slug} references missing calendar entry '{item}'; "
                  "run --check-calendar", file=sys.stderr)
            sys.exit(1)
        upserts[item] = _entry_fields_for_progress(
            entry, slug=slug, job=job, progress=progress, company=company,
            meta_path=target_meta_path, calendar_item=item)
    company_view, company_count, view_errors = _company_view_markdown(
        overrides, upserts)
    if view_errors:
        print("Error: could not build the generated company view:", file=sys.stderr)
        for error in view_errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    if raw is None and not company_count:
        return None
    if raw is None:
        raw = _read_calendar_raw(create=True)
    plan = plan_calendar_update(raw, upserts, company_view=company_view)
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
    write) if meta.yaml is missing, unparseable, or not the current schema.
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
    meta, raw = _load_current_meta(meta_path)
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
        slug, str(meta.get("company") or ""), jobs_progress,
        source_meta_path=meta_path, prospective_meta=plan.output_bytes,
        target_meta_path=_status_dir(new_status) / slug / "meta.yaml")
    changed = _commit_meta_and_calendar([(meta_path, raw, plan)], calendar_plan)
    if plan.changed:
        print(f"{slug}: set all {len(meta['jobs'])} posting(s) to '{new_status}' "
              f"(status_date {today})")

    moved = _move_application(slug, src, new_status)
    if not changed and not moved:
        print(f"{slug} is already fully '{new_status}' — nothing to do")
    _record_log_events(slug)


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
    meta, raw = _load_current_meta(meta_path)
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
    edited_preview = yaml.safe_load(plan.output_bytes.decode("utf-8"))
    derived = derive_status(edited_preview["jobs"])
    calendar_plan = _transition_calendar_plan(
        slug, str(meta.get("company") or ""), [(job, progress)],
        source_meta_path=meta_path, prospective_meta=plan.output_bytes,
        target_meta_path=_status_dir(derived) / slug / "meta.yaml")
    changed = _commit_meta_and_calendar([(meta_path, raw, plan)], calendar_plan)

    detail = f"status {old_status} -> {status}"
    print(f"{slug} posting [{index + 1}] {role}: {detail}")
    if not changed:
        print(f"  (meta.yaml already matched — {detail})")

    # Recompute the rollup from the edited postings and move the folder to match.
    _move_application(slug, src, derived)
    _record_log_events(slug)


def _print_plan_errors(meta_path: Path, plan) -> None:
    print(f"Error: could not update {meta_path} (nothing written):",
          file=sys.stderr)
    for error in plan.errors:
        print(f"  - {error}", file=sys.stderr)


def _utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_progress(
    slug: str, role_match: str, *, phase: str, state: str,
    label: str | None = None, email_ref: str | None = None,
    action: str | None = None, due_at: str | None = None,
    starts_at: str | None = None, ends_at: str | None = None,
    timezone_name: str | None = None, follow_up_at: str | None = None,
    calendar_item: str | None = None, add_occurrence: bool = False,
    display_rounds: list[str] | None = None,
):
    """Set ONE posting's structured progress; never moves the status folder.

    Writes ``jobs[].progress`` (phase, state, optional label, tool-stamped
    ``updated_at``, ``source: manual``) and the calendar entry together,
    transactionally. Entering a scheduling state (booking/waiting/scheduled/
    reschedule) creates the calendar entry when the job has none — with a fresh
    stable id appended to ``progress.calendar_items``. ``--state scheduled``
    requires an exact ``--starts-at`` plus ``--timezone`` on the SAME
    invocation (they land on the entry before it is validated); ``--ends-at``
    is optional. ``--add-occurrence`` appends a parallel confirmed slot instead
    of overwriting a prior occurrence. With several linked occurrences,
    ``--calendar-item`` targets exactly one; omitting it applies a pure
    phase/state change to all linked entries.
    """
    if phase not in PROGRESS_PHASES:
        print(f"Error: --phase must be one of {', '.join(PROGRESS_PHASES)}",
              file=sys.stderr)
        sys.exit(1)
    if state not in PROGRESS_STATES:
        print(f"Error: --state must be one of {', '.join(PROGRESS_STATES)}",
              file=sys.stderr)
        sys.exit(1)
    normalized_email_ref = str(email_ref or "").strip()
    if normalized_email_ref and not _NEUTRAL_EMAIL_REF_RE.fullmatch(normalized_email_ref):
        print("Error: --email-ref must be a neutral acct-NN/<64-lowercase-hex> "
              "stored-message reference", file=sys.stderr)
        sys.exit(1)
    requested_item = str(calendar_item or "").strip()
    if add_occurrence and requested_item:
        print("Error: --add-occurrence and --calendar-item are mutually exclusive",
              file=sys.stderr)
        sys.exit(1)
    if add_occurrence and state != "scheduled":
        print("Error: --add-occurrence requires --state scheduled", file=sys.stderr)
        sys.exit(1)
    if add_occurrence and (not starts_at or not timezone_name):
        print("Error: --add-occurrence requires --starts-at and --timezone",
              file=sys.stderr)
        sys.exit(1)

    src = find_application(slug)
    if src is None:
        print(f"Error: application '{slug}' not found under any status folder "
              f"({', '.join(STATUS_FOLDERS)})", file=sys.stderr)
        sys.exit(1)

    meta_path = src / "meta.yaml"
    meta, raw = _load_current_meta(meta_path)
    jobs = meta["jobs"]
    index = _resolve_job_index(jobs, role_match)
    job = jobs[index] if isinstance(jobs[index], dict) else {}
    role = str(job.get("role") or "").strip() or f"job {index + 1}"
    current = job.get("progress") if isinstance(job.get("progress"), dict) else {}

    progress: dict = {"phase": phase, "state": state}
    effective_label = label if label is not None else current.get("label")
    if str(effective_label or "").strip():
        progress["label"] = effective_label
    progress["source"] = (
        {"kind": "email", "ref": normalized_email_ref}
        if normalized_email_ref
        else {"kind": "manual", "ref": ""}
    )
    calendar_items = _progress_calendar_items(current)

    company = str(meta.get("company") or "")
    calendar_plan = None
    raw_calendar = None
    upserts: dict[str, dict] = {}
    create_missing = False
    needs_entry = (
        state in PROGRESS_CALENDAR_STATES
        or bool(calendar_items)
        or add_occurrence
        or bool(requested_item)
    )
    if needs_entry:
        raw_calendar = _read_calendar_raw(create=True)
        doc = parse_calendar(raw_calendar.decode("utf-8"))
        if doc.errors:
            print(f"Error: calendar file {_calendar_path()} failed validation "
                  "(fix it or run --check-calendar):", file=sys.stderr)
            for error in doc.errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)
        missing = [item for item in calendar_items if item not in doc.entries]
        if missing:
            print(f"Error: {slug} references missing calendar entr"
                  f"{'y' if len(missing) == 1 else 'ies'}: "
                  f"{', '.join(missing)}; run --check-calendar", file=sys.stderr)
            sys.exit(1)
        if requested_item and requested_item not in calendar_items:
            print(f"Error: --calendar-item '{requested_item}' is not linked to "
                  f"{slug} [{role}]", file=sys.stderr)
            sys.exit(1)

        occurrence_values = any(value is not None for value in (
            action, due_at, starts_at, ends_at, timezone_name, follow_up_at,
        )) or display_rounds is not None
        if add_occurrence:
            target_items = [generate_entry_id(doc.entries, slug)]
            calendar_items.append(target_items[0])
            create_missing = True
        elif requested_item:
            target_items = [requested_item]
        elif not calendar_items:
            target_items = [generate_entry_id(doc.entries, slug)]
            calendar_items.append(target_items[0])
            create_missing = True
        elif len(calendar_items) == 1:
            target_items = list(calendar_items)
        elif occurrence_values:
            print("Error: this role has multiple calendar occurrences; pass "
                  "--calendar-item to update one or --add-occurrence to append "
                  "a parallel confirmed slot", file=sys.stderr)
            sys.exit(1)
        else:
            target_items = list(calendar_items)

        progress["calendar_items"] = list(calendar_items)
        for item in target_items:
            entry = doc.entries.get(item)
            if entry is not None and starts_at is not None \
                    and entry.starts_at is not None \
                    and starts_at != entry.starts_at:
                print(
                    f"Error: calendar entry '{item}' already records confirmed "
                    f"occurrence {entry.starts_at}; refusing to overwrite it "
                    f"with {starts_at}. For a replacement, edit that entry's "
                    "reschedule_to proposal and run --sync-calendar --write. "
                    "For a parallel slot, use --add-occurrence.",
                    file=sys.stderr,
                )
                sys.exit(1)
            fields = _entry_fields_for_progress(
                entry, slug=slug, job=job, progress=progress, company=company,
                meta_path=meta_path, calendar_item=item)
            for key, value in (
                ("action", action), ("due_at", due_at),
                ("starts_at", starts_at), ("ends_at", ends_at),
                ("timezone", timezone_name), ("follow_up_at", follow_up_at),
            ):
                if value is not None:
                    fields[key] = value or None
            if display_rounds is not None:
                fields["display_rounds"] = list(display_rounds)
            upserts[item] = fields

        occurrence_fields = {
            item: doc.entries[item].fields()
            for item in calendar_items
            if item in doc.entries
        }
        occurrence_fields.update(upserts)
        progress["state"] = _reduce_calendar_occurrences(
            [occurrence_fields[item] for item in calendar_items],
            fallback=state,
        )

    progress["updated_at"] = _utc_now_stamp()

    plan = plan_field_updates(raw, {("jobs", index): {"progress": progress}})
    if plan.errors:
        _print_plan_errors(meta_path, plan)
        if state == "closed":
            print("Hint: close a role with --update-job <slug> <role> "
                  "rejected|ignored — that sets state 'closed' with it.",
                  file=sys.stderr)
        sys.exit(1)

    company_view, company_count, view_errors = _company_view_markdown(
        {meta_path: (plan.output_bytes, meta_path)}, upserts)
    if view_errors:
        print("Error: could not build the generated company view:", file=sys.stderr)
        for error in view_errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    if raw_calendar is None:
        raw_calendar = _read_calendar_raw()
        if raw_calendar is None and company_count:
            raw_calendar = _read_calendar_raw(create=True)
    if raw_calendar is not None:
        calendar_plan = plan_calendar_update(
            raw_calendar,
            upserts,
            create_missing=create_missing,
            company_view=company_view,
        )
        if calendar_plan.errors:
            print("Error: could not plan the calendar update (nothing written):",
                  file=sys.stderr)
            for error in calendar_plan.errors:
                print(f"  - {error}", file=sys.stderr)
            if state == "scheduled":
                print("Hint: pass --starts-at <ISO timestamp> and --timezone "
                      "<IANA zone> (plus optional --ends-at) with the progress "
                      "update.",
                      file=sys.stderr)
            sys.exit(1)
    _commit_meta_and_calendar([(meta_path, raw, plan)], calendar_plan)
    bits = [f"phase -> {phase}", f"state -> {state}"]
    if label is not None:
        bits.append(f"label -> {label!r}")
    print(f"{slug} posting [{index + 1}] {role}: {'; '.join(bits)}")
    if calendar_plan is not None and calendar_plan.changed:
        print(f"Updated calendar entr"
              f"{'y' if len(upserts) == 1 else 'ies'} "
              f"{', '.join(upserts)} -> {_calendar_path()}")
    print("Progress-only update: the status folder is unchanged.")


# --------------------------------------------------------------------------- #
# Calendar verification + preview-first human-edit sync
# --------------------------------------------------------------------------- #
def _fleet_calendar_refs() -> dict[str, list[tuple[Path, dict, int, dict]]]:
    """Calendar item id -> owning job rows across the schema-v6 fleet."""
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
                for item in _progress_calendar_items(progress):
                    refs.setdefault(item, []).append((meta_path, meta, index, job))
    return refs


def check_calendar(as_json: bool = False) -> bool:
    """Verify calendar.md and its cross-links with per-job progress (read-only)."""
    path = _calendar_path()
    findings: list[str] = []
    refs = _fleet_calendar_refs()
    company_view, company_count, view_errors = _company_view_markdown()
    findings.extend(view_errors)
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
        if not doc.errors and not view_errors:
            view_plan = plan_calendar_update(
                raw, {}, company_view=company_view)
            if view_plan.errors:
                findings.extend(view_plan.errors)
            elif view_plan.changed:
                findings.append(
                    "generated company view is stale "
                    "(run --refresh-calendar --write)")
    if raw is None and company_count:
        findings.append(
            f"calendar file {path} is missing but {company_count} in-progress "
            f"compan{'y' if company_count == 1 else 'ies'} require the generated view")

    entries = doc.entries if doc is not None else {}
    grouped_occurrences: dict[tuple[Path, int], list] = {}
    for item, holders in sorted(refs.items()):
        if len(holders) > 1:
            findings.append(
                f"calendar entry '{item}' is referenced by multiple jobs: "
                + ", ".join(h[0].parent.name for h in holders))
        entry = entries.get(item)
        if entry is None:
            if doc is not None:
                findings.append(
                    f"{holders[0][0].parent.name}: progress.calendar_items "
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
        if entry.phase != progress.get("phase"):
            findings.append(
                f"entry '{item}': phase '{entry.phase}' drifted from meta "
                f"progress '{progress.get('phase')}' (run --sync-calendar)")
        grouped_occurrences.setdefault((meta_path, index), []).append(entry)
        expected_section = STATE_SECTIONS.get(entry.state)
        if expected_section and entry.section != expected_section:
            findings.append(
                f"entry '{item}': sits under '{entry.section}' but state "
                f"'{entry.state}' belongs under '{expected_section}'")
        if entry.checked and entry.state in CHECKED_BOX_TRANSITIONS:
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
                f"entry '{item}': no job's progress.calendar_items references it "
                f"(application '{entry.application}', role '{entry.role}')")

    for (meta_path, index), occurrences in sorted(
        grouped_occurrences.items(), key=lambda row: (str(row[0][0]), row[0][1])
    ):
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        job = meta["jobs"][index]
        progress = job.get("progress") or {}
        reduced = _reduce_calendar_occurrences(
            occurrences,
            fallback=str(progress.get("state") or "unknown"),
        )
        if progress.get("state") != reduced:
            findings.append(
                f"{meta_path.parent.name} jobs[{index}]: aggregate progress.state "
                f"'{progress.get('state')}' does not reduce from linked "
                f"occurrences to '{reduced}' (run --sync-calendar)")

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


def refresh_calendar(
    write: bool = False, as_json: bool = False, html_companion: bool = False,
) -> bool:
    """Preview or re-render managed rows plus the generated company view.

    Metadata remains canonical for phase/state. This command only refreshes
    visible dates/actions, role links, the hidden one-line markers, and the
    read-only company projection; it does not infer a transition or touch any
    application metadata. ``html_companion`` emits an optional, separately
    derived offline view beside the canonical Markdown file.
    """
    path = _calendar_path()
    raw = _read_calendar_raw()
    refs = _fleet_calendar_refs()
    company_view, company_count, view_errors = _company_view_markdown()
    if view_errors:
        print("Error: cannot refresh generated company view:", file=sys.stderr)
        for error in view_errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    if raw is None:
        if not refs and not company_count:
            print(f"No calendar file at {path}; nothing to refresh.")
            return True
        raw = (_read_calendar_raw(create=True)
               if write else CALENDAR_TEMPLATE.encode("utf-8"))
    doc = parse_calendar(raw.decode("utf-8"))
    if doc.errors:
        print(f"Error: calendar file {path} failed validation:", file=sys.stderr)
        for error in doc.errors:
            print(f"  - {error}", file=sys.stderr)
        return False

    upserts: dict[str, dict] = {}
    errors: list[str] = []
    for item, holders in sorted(refs.items()):
        if len(holders) != 1:
            errors.append(f"entry '{item}' is referenced by {len(holders)} jobs")
            continue
        entry = doc.entries.get(item)
        if entry is None:
            errors.append(f"referenced entry '{item}' is missing")
            continue
        meta_path, meta, _index, job = holders[0]
        progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
        occurrence_progress = dict(progress)
        occurrence_progress["state"] = entry.state
        upserts[item] = _entry_fields_for_progress(
            entry, slug=meta_path.parent.name, job=job,
            progress=occurrence_progress,
            company=str(meta.get("company") or ""), meta_path=meta_path,
            calendar_item=item)
    for item in sorted(doc.entries):
        if item not in refs:
            errors.append(f"entry '{item}' is not referenced by application metadata")
    if errors:
        print("Error: cannot refresh calendar:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return False

    company_view, company_count, view_errors = _company_view_markdown(
        calendar_overrides=upserts)
    if view_errors:
        print("Error: cannot refresh generated company view:", file=sys.stderr)
        for error in view_errors:
            print(f"  - {error}", file=sys.stderr)
        return False

    plan = plan_calendar_update(raw, upserts, company_view=company_view)
    if plan.errors:
        print("Error: could not refresh calendar:", file=sys.stderr)
        for error in plan.errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    html_output = None
    html_path = _calendar_html_path()
    html_changed = False
    if html_companion:
        html_companies, html_agenda_items, html_availability, html_errors = _company_view_data(
            calendar_overrides=upserts)
        if html_errors:
            print("Error: cannot render calendar HTML:", file=sys.stderr)
            for error in html_errors:
                print(f"  - {error}", file=sys.stderr)
            return False
        html_output = render_company_view_html(
            html_companies, html_agenda_items,
            availability_config=html_availability,
        )
        try:
            existing_html = html_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing_html = None
        except (OSError, UnicodeDecodeError) as exc:
            print(f"Error: cannot read calendar HTML companion {html_path}: {exc}",
                  file=sys.stderr)
            return False
        if existing_html is not None and "Generated from canonical application progress" not in existing_html:
            print(f"Error: refusing to overwrite non-generated calendar HTML {html_path}",
                  file=sys.stderr)
            return False
        html_changed = existing_html != html_output

    summary = {
        "calendar": str(path),
        "entries": len(upserts),
        "companies": company_count,
        "changed": plan.changed or html_changed,
        "html": str(html_path) if html_companion else None,
        "mode": "write" if write else "dry_run",
    }
    if as_json:
        print(json.dumps(summary, indent=2))
    elif plan.changed or html_changed:
        print(f"Calendar refresh ({'WRITE' if write else 'DRY RUN'}): "
              f"{len(upserts)} managed row(s) and {company_count} company "
              f"view row(s) will be re-rendered.")
    else:
        print(f"Calendar {path}: already uses the current layout.")
    if (not plan.changed and not html_changed) or not write:
        if (plan.changed or html_changed) and not as_json:
            print("No files written. Re-run with --refresh-calendar --write.")
        return True
    if plan.changed:
        try:
            atomic_write_bytes(path, plan.output_bytes,
                               expected_sha256=plan.before_sha256)
        except (MetadataChecksumMismatchError, OSError) as exc:
            print(f"Error: calendar refresh failed: {exc}", file=sys.stderr)
            return False
    if html_changed and html_output is not None:
        try:
            atomic_write_text(html_path, html_output)
        except OSError as exc:
            print(f"Error: calendar HTML refresh failed: {exc}", file=sys.stderr)
            return False
    rendered = [str(path)] if plan.changed else []
    if html_changed:
        rendered.append(str(html_path))
    print(f"Refreshed {len(upserts)} managed calendar row(s) and "
          f"{company_count} company view row(s) -> {', '.join(rendered)}")
    return True


def _sync_proposals(doc, refs):
    """Compute (proposal_rows, errors) mapping owner calendar edits to progress.

    A proposal row is ``(entry_id, meta_path, job_index, new_progress,
    new_entry_fields, description)``. Meta stays canonical for phase/state, so
    entries that merely drifted are re-rendered from meta; the owner-edit
    surfaces (checked box, reschedule_to, cancel: true) win over drift repair.
    """
    proposals = []
    errors = []
    final_fields: dict[str, dict] = {}
    owners: dict[tuple[Path, int], tuple[dict, dict, str]] = {}
    descriptions: dict[str, str] = {}
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
        company = str(meta.get("company") or "")
        fields = entry.fields()
        fields["_company"] = company
        fields["details"] = _details_reference(meta_path)
        owners[(meta_path, index)] = (job, progress, slug)

        if progress.get("state") == "closed":
            fields["phase"] = progress.get("phase")
            fields["state"] = "closed"  # never reopen a closed role here
            if (entry.phase, entry.state) != (fields["phase"], fields["state"]):
                descriptions[item] = (
                    f"{slug} [{entry.role}]: re-render closed occurrence from "
                    "canonical metadata")
        elif entry.cancel:
            fields = record_cancellation(fields)
            fields["_company"] = company
            fields["phase"] = progress.get("phase")
            fields["details"] = _details_reference(meta_path)
            descriptions[item] = (
                f"{slug} [{entry.role}]: cancellation recorded — occurrence "
                f"kept in history, occurrence state -> {fields['state']}")
        elif entry.reschedule_to:
            fields = record_reschedule(
                fields, entry.reschedule_to, entry.reschedule_timezone)
            fields["_company"] = company
            fields["phase"] = progress.get("phase")
            fields["details"] = _details_reference(meta_path)
            descriptions[item] = (
                f"{slug} [{entry.role}]: confirmed reschedule to "
                f"{fields['starts_at']} {fields['timezone']} — old occurrence "
                "kept as superseded")
        elif entry.checked and entry.state in CHECKED_BOX_TRANSITIONS:
            new_state = CHECKED_BOX_TRANSITIONS[entry.state]
            if entry.state == "scheduled":
                fields = record_completion(fields)
                fields["_company"] = company
                fields["details"] = _details_reference(meta_path)
            else:
                fields["state"] = new_state
            fields["phase"] = progress.get("phase")
            descriptions[item] = (
                f"{slug} [{entry.role}]: checked occurrence — state "
                f"{entry.state} -> {new_state}")
        else:
            if entry.phase != progress.get("phase"):
                fields["phase"] = progress.get("phase")
                descriptions[item] = (
                    f"{slug} [{entry.role}]: re-render occurrence phase from "
                    f"meta progress ({progress.get('phase')})")
        final_fields[item] = fields

    for (meta_path, index), (_job, progress, slug) in sorted(
        owners.items(), key=lambda row: (str(row[0][0]), row[0][1])
    ):
        occurrence_ids = _progress_calendar_items(progress)
        missing = [item for item in occurrence_ids if item not in final_fields]
        if missing:
            errors.append(
                f"{slug} jobs[{index}] references missing occurrence(s): "
                + ", ".join(missing))
            continue
        reduced = (
            "closed"
            if progress.get("state") == "closed"
            else _reduce_calendar_occurrences(
                [final_fields[item] for item in occurrence_ids],
                fallback=str(progress.get("state") or "unknown"),
            )
        )
        new_progress = None
        if reduced != progress.get("state"):
            new_progress = dict(progress)
            new_progress["state"] = reduced
            new_progress["phase"] = progress.get("phase")
            new_progress["updated_at"] = _utc_now_stamp()
            new_progress["source"] = {"kind": "manual", "ref": ""}

        changed_items = [
            item for item in occurrence_ids
            if item in descriptions
        ]
        if new_progress is not None and not changed_items and occurrence_ids:
            changed_items = [occurrence_ids[0]]
            descriptions[occurrence_ids[0]] = (
                f"{slug}: aggregate occurrence state -> {reduced}")
        for position, item in enumerate(changed_items):
            proposals.append((
                item,
                meta_path,
                index,
                new_progress if position == 0 else None,
                final_fields[item],
                descriptions[item],
            ))
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
    meta_overrides: dict[Path, tuple[bytes, Path]] = {}
    for meta_path, updates in sorted(by_meta.items()):
        pre_image = meta_path.read_bytes()
        plan = plan_field_updates(pre_image, updates)
        if plan.errors:
            _print_plan_errors(meta_path, plan)
            return False
        meta_writes.append((meta_path, pre_image, plan))
        meta_overrides[meta_path] = (plan.output_bytes, meta_path)
    company_view, _company_count, view_errors = _company_view_markdown(
        meta_overrides, upserts)
    if view_errors:
        print("Error: could not build the generated company view:", file=sys.stderr)
        for error in view_errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    calendar_plan = plan_calendar_update(
        raw, upserts, company_view=company_view)
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
    if a.get("meta_error"):
        # Never an empty cell: a blank role is what "no roles recorded yet" looks
        # like, and this row is "the file would not parse" instead.
        return "(metadata unreadable)"
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

    # Deliberately a report, not an exit code. This table is a read-only fleet
    # view, not a gate: one broken file must not hide the other forty rows. The
    # gates that DO fail on these are --check-metadata and --check-locations, and
    # --sync-log refuses to write a row for them.
    unreadable = [a for a in apps if a.get("meta_error")]
    if unreadable:
        print(f"Unreadable metadata ({len(unreadable)}) — these rows show only "
              "folder-derived facts, and no skip-log row is written for them:")
        for a in unreadable:
            print(f"  ! {a['slug']}: {a['meta_error']}")


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
                linked_follow_ups = sorted(
                    follow_ups[item]
                    for item in _progress_calendar_items(progress)
                    if item in follow_ups
                )
                follow = linked_follow_ups[0][:10] if linked_follow_ups else ""
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

    The per-application flattening itself lives in ``skip_log.posting_rows``, not
    here, because this is no longer the only writer: job-search's ``handoff.py``
    appends the same rows when it scaffolds a folder, and a skill may not import
    another skill's ``scripts/``. All this wrapper adds is the (company, slug)
    ordering — which ``_upsert_log_rows`` relies on to collapse a re-application
    onto the fresher slug — the two header fields, and the unreadable guard below.

    **An application whose metadata failed to parse produces no row at all.** It is
    returned under ``unreadable`` instead, for the caller to report. This is the
    single choke point where a folder becomes a skip-log identity, and the skip-log
    is append-only and authoritative: nothing regenerates it, so a wrong row is
    permanent until the owner appends a ``--forget-log`` tombstone. Derived from an
    unparsed file the row is wrong in the way that matters most — the real posting
    URL never reaches it, so ``fold_key`` stores a ``(company, role)`` pair built
    from the folder name and the actual posting is never skipped. The two costs are
    not symmetric: a row not written is recovered by fixing the YAML and re-running,
    a row written wrong is not.
    """
    postings = []
    unreadable = []
    for a in sorted(apps, key=lambda x: (x.get("company", ""), x.get("slug", ""))):
        if a.get("meta_error"):
            unreadable.append({"slug": a.get("slug", ""), "error": a["meta_error"]})
            continue
        postings.extend(skip_log.posting_rows(a))
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(postings),
        "postings": postings,
        "unreadable": unreadable,
    }


def _default_aliases(name: str) -> list[str]:
    low = name.strip().lower()
    return [low] if low else []


def _load_company_search_log_raw() -> dict:
    """The parsed company search log, or a fresh skeleton when it does not exist.

    Exits rather than returning a skeleton when the file exists but will not parse.
    Every caller of this function goes on to REWRITE the file from what it returns,
    so handing back an empty document would replace the owner's whole search log
    with two keys and no companies — the same "unparseable read treated as an empty
    file" failure this module now refuses everywhere else.
    """
    if not COMPANY_SEARCH_LOG.exists():
        return {"skip_within_days": 7, "companies": []}
    try:
        with open(COMPANY_SEARCH_LOG) as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        print(f"Error: {_read_failure(str(COMPANY_SEARCH_LOG), exc)}\n"
              "  Refusing to rewrite it, which would discard every row it holds. "
              "Fix the file and re-run.", file=sys.stderr)
        sys.exit(1)
    if data is None:
        return {"skip_within_days": 7, "companies": []}
    if not isinstance(data, dict):
        print(f"Error: {COMPANY_SEARCH_LOG} must contain a mapping; refusing to "
              "rewrite it.", file=sys.stderr)
        sys.exit(1)
    return data


def _company_entry_key(name: str) -> str:
    return name.strip().lower()


def build_created_search_entries(apps: list[dict]) -> list[dict]:
    """One row per company with an application folder (latest folder date).

    Skips an application whose metadata failed to parse, for the same reason
    ``build_log`` does. Its ``company`` is then the slug run through ``.title()``
    — "Acme Labs Ml Engineer" for ``acme-labs-ml-engineer-20260701`` — so the row
    both invents a company that does not exist AND leaves the real one unrecorded,
    which is the wrong half of a skip decision in both directions.
    """
    latest: dict[str, str] = {}
    for a in apps:
        if a.get("meta_error"):
            continue
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
    """Rewrite the company search log atomically, keeping keys this writer does not own.

    Two properties a bare ``Path.write_text`` of a freshly built dict does not have:

    * **Atomic.** ``write_text`` truncates first and writes second, so an
      interrupted rewrite leaves a half file where a complete search log used to
      be — and this file is rewritten on every ``--sync-log`` and every
      ``--log-search``. The temp-then-rename helper leaves either the old bytes or
      the new bytes, never a truncation.
    * **Lossless.** The three keys below are the only ones this writer manages;
      anything else at the top level is carried through from the parsed document
      instead of being dropped in silence. The managed keys are written first, in
      their historical order, so a file with nothing extra comes out byte-shaped
      exactly as before.
    """
    out = {
        "skip_within_days": data.get("skip_within_days", 7),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "companies": data.get("companies") or [],
    }
    for key, value in (data or {}).items():
        if key not in out:
            out[key] = value
    atomic_write_text(
        COMPANY_SEARCH_LOG,
        COMPANY_SEARCH_LOG_HEADER
        + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=100))
    return COMPANY_SEARCH_LOG


def plan_company_search_log(apps: list[dict]) -> dict:
    """The company-search-log document this sync WOULD write. Reads; never writes.

    Split out of :func:`sync_company_search_log` so ``--sync-log`` can do all of
    its fallible work — parsing the existing log, flattening the folders — BEFORE
    it touches the append-only skip-log. See :func:`sync_log`.
    """
    raw = _load_company_search_log_raw()
    raw["companies"] = merge_company_search_log(
        raw.get("companies") or [], build_created_search_entries(apps))
    return raw


def sync_company_search_log(apps: list[dict]) -> Path:
    """Upsert `created` entries from application folders into company-search-log.yaml."""
    return write_company_search_log(plan_company_search_log(apps))


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


def _upsert_log_rows(rows: list[dict], *, source: str) -> int:
    """Append the postings that differ from the folded skip-log; return how many.

    A one-line binding of this module's log path to ``skip_log.record_postings``,
    which owns the comparison, the collision collapse and the append. The policy
    is shared rather than local because ``handoff.py`` performs the same append at
    creation time; the collapse's last-wins tie-break relies on ``build_log``'s
    (company, slug) ordering, so a re-application's later slug is the survivor.
    """
    return skip_log.record_postings(APPLICATIONS_JSONL, rows, source=source)


def sync_log() -> tuple[Path, int, Path, list[dict]]:
    """Append changed postings to the skip-log; upsert company-search-log from folders.

    Union-only. The skip-log is never rewritten and never truncated, so an
    application folder the owner deleted keeps its row and job-search keeps
    skipping that posting. Returns the skip-log path, how many events were
    appended, the company-search-log path, and the applications whose metadata
    would not parse — those contribute to neither file, and the caller turns them
    into a non-zero exit so an incomplete sync is never mistaken for a clean one.

    The retired ``applications-log.yaml`` is NOT written here any more — see
    ``backfill_log`` for the one-time seed and for what happens to the old file.

    **Derive everything, then write; permanent write LAST.** This used to append
    to the skip-log and only then build the company search log, so any failure in
    the second half landed after a write that nothing can take back: one
    ``meta.yaml`` carrying an unquoted ``research_date:`` raised deep inside
    ``build_created_search_entries`` and killed the run with the skip-log already
    appended and the search log never updated. The same window is reachable
    without a crash at all — ``_load_company_search_log_raw`` deliberately
    ``sys.exit``s on a company search log that will not parse, which was also
    happening after the append.

    So both fallible reads (the folder walk, the existing search log) and both
    derivations happen first, and the two writes are ordered by how expensive
    they are to undo: the company search log is rewritten wholesale from the
    folders on every run and therefore fully recoverable, while the skip-log is
    append-only and authoritative — a spurious row is repaired only by appending
    a ``--forget-log`` tombstone. Anything that raises now leaves the permanent
    file untouched and the run repeatable.
    """
    apps = collect_apps()
    log = build_log(apps)
    planned_search_log = plan_company_search_log(apps)
    search_path = write_company_search_log(planned_search_log)
    appended = _upsert_log_rows(log["postings"], source="sync")
    return APPLICATIONS_JSONL, appended, search_path, log["unreadable"]


def _yaml_log_postings() -> list[dict]:
    """The retired YAML skip-log's ``postings`` rows; ``[]`` when it is absent.

    The only place anything still reads that file: ``--backfill-log`` seeds from
    it once.
    """
    if not APPLICATIONS_LOG.exists():
        return []
    with open(APPLICATIONS_LOG) as f:
        data = yaml.safe_load(f) or {}
    rows = data.get("postings")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def backfill_log(force: bool = False) -> tuple[Path, int, int, list[dict]]:
    """Seed the append-only skip-log from the YAML log UNION the folder rows.

    Returns (path, events appended, resulting fold size, unreadable applications).
    An application whose metadata would not parse contributes no seed row — a bad
    seed row is exactly as permanent as a bad sync row — and is handed back for the
    caller to report and exit non-zero on.

    A key present in both sources takes the FOLDER row: the YAML was only ever a
    projection of the folders, refreshed on the last sync, so the folder is the
    fresher of the two. A key present in only one source is kept — that union is
    the point, since a row whose folder the owner already deleted is precisely
    what this phase exists to preserve.

    ``--force`` appends a fresh generation rather than refusing. Refuse-if-exists
    as the ONLY mode would make a wrong seed permanent, because nothing in this
    format may delete a line; re-seeding is just another append, and a later line
    wins the fold.
    """
    if APPLICATIONS_JSONL.exists() and not force:
        print(f"Error: {APPLICATIONS_JSONL} already exists — refusing to seed it "
              "twice. Re-run with --force to append a fresh generation (a later "
              "line wins the fold; nothing is ever deleted).", file=sys.stderr)
        sys.exit(1)

    folder_log = build_log(collect_apps())
    merged: dict[tuple, dict] = {}
    for source_rows in (_yaml_log_postings(), folder_log["postings"]):
        for raw in source_rows:
            row = skip_log.posting_row(raw)
            merged[skip_log.fold_key(row)] = row

    # A re-seed must not reverse a decision the owner made by hand. The retired YAML
    # still contains every row that has since been tombstoned and is never updated, so
    # without this a --force generation resurrects every --forget-log ever run — and
    # says nothing about it.
    forgotten = skip_log.forgotten_keys(APPLICATIONS_JSONL)
    honored = [key for key in merged if key in forgotten]
    for key in honored:
        del merged[key]

    for row in merged.values():
        skip_log.append_event(APPLICATIONS_JSONL, row, source="backfill")
    if honored:
        print(f"  kept {len(honored)} earlier --forget-log tombstone(s); those "
              "postings were NOT re-seeded")
    return (APPLICATIONS_JSONL, len(merged),
            len(skip_log.fold(APPLICATIONS_JSONL)), folder_log["unreadable"])


def _near_log_matches(fold: dict, values: list[str], limit: int = 10) -> list[dict]:
    """Folded rows whose company/role/url overlaps one of the query strings.

    Printed when ``--forget-log`` finds no exact key, so the owner sees the row
    they probably meant — a URL that lost its query string, a company spelled a
    second way — instead of a bare "not found". Matching runs in both directions
    because the typo can be on either side: the query can be a fragment of the
    stored row, or the stored row a fragment of an over-long pasted URL.
    """
    needles = [n for n in (skip_log.norm_text(v) for v in values) if n]
    hits: list[dict] = []
    for row in fold.values():
        fields = [skip_log.norm_text(row.get(k)) for k in ("company", "role", "url")]
        haystack = " ".join(fields)
        if (any(needle in haystack for needle in needles)
                or any(f and any(f in needle for needle in needles) for f in fields)):
            hits.append(row)
        if len(hits) >= limit:
            break
    return hits


def forget_log(values: list[str]) -> None:
    """Un-skip one posting by appending a tombstone the fold honours.

    ``values`` is either ONE posting URL or TWO strings, COMPANY and ROLE — the
    same two branches ``skip_log.fold_key`` uses.

    Regeneration used to heal a wrong row for free: the next sync rewrote the
    whole file. Append-only removes that, so without this command a typo'd company
    string is immortal — it suppresses every future posting that normalizes to it,
    and hand-editing an authoritative machine-owned file is the owner's only
    remedy. Agents may not delete lines, so the repair is itself an append.

    Refuses a key that is not currently folded. A silent no-op un-skip is worse
    than an error: the owner walks away believing the posting will resurface, and
    it will not.
    """
    try:
        if len(values) == 1:
            row = skip_log.forget_row(url=values[0])
            target = f"url {values[0]!r}"
        elif len(values) == 2:
            row = skip_log.forget_row(company=values[0], role=values[1])
            target = f"company {values[0]!r} + role {values[1]!r}"
        else:
            print(f"Error: --forget-log takes ONE value (the posting URL) or TWO "
                  f"(COMPANY ROLE); got {len(values)}", file=sys.stderr)
            sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    fold = skip_log.fold(APPLICATIONS_JSONL)
    key = skip_log.fold_key(row)

    # A tombstone on a posting that still has an application folder is undone by the
    # very next --sync-log, which rebuilds that row from the folder — and the tombstone
    # would have printed a success line on its way to being reverted. Refuse instead:
    # a live folder is live evidence that the posting WAS handled, so there is nothing
    # here to un-skip. Same principle as refusing an unfolded key — an un-skip that
    # quietly does nothing is worse than an error.
    #
    # **The remedy must be one an agent may actually perform.** This message used to
    # read "Move or delete the application folder first" and it was the ONLY exit from
    # handoff's explicit-``--select`` duplicate chain, so an agent following it deleted
    # an application folder — the one act AGENTS.md forbids outright ("application
    # folders … are removed by the USER only — never by an agent, under any
    # condition"). "Move" was never an out either: handoff's ``LIVE_STATUS_DIRS``
    # covers all five status folders, so a move between them changes nothing.
    #
    # An opt-in flag that appended the tombstone anyway was considered and rejected:
    # the next --sync-log rebuilds the row from the folder, so the flag would buy
    # exactly the silent no-op un-skip this branch exists to refuse. The real remedy
    # is that the application ALREADY EXISTS — use it — and, if it genuinely should
    # go, the owner disposes of it (memory/decisions/handoff-records-every-folder-it-
    # creates.md rests on a missing folder always meaning the owner removed it).
    backing = next(
        (r for r in build_log(collect_apps())["postings"]
         if skip_log.fold_key(r) == key), None)
    if backing is not None:
        folder = find_application(backing["slug"])
        where = str(folder) if folder else f"slug {backing['slug']!r}"
        print(f"Error: {target} is still backed by a live application folder "
              f"({backing['slug']!r}, status {backing['status']!r}). A tombstone would "
              "be undone by the next --sync-log, which rebuilds that row from the "
              "folder — the folder IS the record that this posting was handled, so "
              "there is nothing to un-skip.\n"
              f"  Work with the application that already exists: {where}\n"
              "  Removing that folder is NOT the remedy and is not an agent's to "
              "make: application folders are removed by the USER only, never by an "
              "agent, under any condition (AGENTS.md, \"Agents never delete owner "
              "data\"). If it truly should go, propose the removal in "
              "message-queue/needs-human/ and stop; --forget-log repairs the row "
              "afterwards, once the owner has acted.\n"
              "  (--forget-log is for a row whose folder is already gone — a typo, "
              "or an application the owner removed.)", file=sys.stderr)
        sys.exit(1)

    current = fold.get(key)
    if current is None:
        print(f"Error: no folded posting in {APPLICATIONS_JSONL} matches {target}; "
              "refusing to append a tombstone that would drop nothing.",
              file=sys.stderr)
        near = _near_log_matches(fold, values)
        if near:
            print("  Closest folded rows:", file=sys.stderr)
            for hit in near:
                print(f"    - {hit.get('company', '')} / {hit.get('role', '')} "
                      f"[{hit.get('status', '')}]  {hit.get('url', '')}",
                      file=sys.stderr)
        print(f"  The fold holds {len(fold)} posting(s). A row that carries a URL "
              "is addressed by that URL, never by company + role.", file=sys.stderr)
        sys.exit(1)

    print("Dropping from the skip-log: "
          f"{current.get('company', '')} / {current.get('role', '')} "
          f"[{current.get('status', '')}] slug={current.get('slug', '')} "
          f"date={current.get('date', '')} url={current.get('url', '')}")
    skip_log.append_event(APPLICATIONS_JSONL, row, source="update", forget=True)
    print(f"Appended a tombstone -> {APPLICATIONS_JSONL} "
          f"({len(skip_log.fold(APPLICATIONS_JSONL))} posting(s) still folded)")


# Flags that scan EVERY application under the active config's applications root. They
# take no path or slug, so `--check-metadata <folder>` exits 2 with a bare argparse
# "unrecognized arguments" and no way to tell a wrong path from a wrong call shape.
# Three measured subject-agent runs each burned a retry on exactly that; the entries
# below turn the rejection into an instruction. (attr, flag, per-application alternative)
_SCAN_FLAGS_TAKING_NO_PATH = (
    ("check_metadata", "--check-metadata", "--enrich-metadata <slug-or-path>"),
    ("backfill_metadata", "--backfill-metadata", "--enrich-metadata <slug-or-path>"),
    ("check_locations", "--check-locations", None),
    ("company_keys", "--company-keys", None),
)


def _report_unwritable(unreadable: list[dict], verb: str) -> None:
    """Name the applications a log write was refused for, and how to clear them.

    Printed to stderr and paired with a non-zero exit by the caller: the write that
    DID happen covered every other application, so this is a partial success, and a
    partial success that exits 0 is one nobody notices.
    """
    sys.stdout.flush()  # keep this block below the write summary it qualifies
    print(f"\nRefused to {verb} a skip-log row for "
          f"{len(unreadable)} application(s) whose metadata would not parse:",
          file=sys.stderr)
    for row in unreadable:
        print(f"  - {row['slug']}: {row['error']}", file=sys.stderr)
    print("  The skip-log is append-only and authoritative: a row derived from an "
          "unparsed file loses the real posting URL, and only a --forget-log "
          "tombstone can undo it. Fix each meta.yaml (--check-metadata reports the "
          "same errors) and re-run.", file=sys.stderr)


def _reject_extra_args(parser, args, extras):
    """Exit 2 on unrecognized arguments, naming the fix when a scan flag caused it."""
    named = " ".join(extras)
    for attr, flag, alternative in _SCAN_FLAGS_TAKING_NO_PATH:
        if not getattr(args, attr, False):
            continue
        hint = (f"{flag} scans every application under the active config's "
                "applications root and takes no path argument; narrow it with "
                "--statuses <folder>")
        if alternative:
            hint += f", or target one application with {alternative}"
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: unrecognized arguments: {named}",
              file=sys.stderr)
        print(f"{parser.prog}: hint: {hint}.", file=sys.stderr)
        sys.exit(2)
    parser.error(f"unrecognized arguments: {named}")


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
    parser.add_argument("--email-ref", default=None, metavar="MESSAGE_KEY",
                        help="Neutral stored-message reference proving an email-"
                             "driven --update-progress. Omit for a manual update.")
    parser.add_argument("--action", default=None, metavar="TEXT",
                        help="Short verb-led calendar todo for --update-progress.")
    parser.add_argument("--due-at", default=None, metavar="ISO_DATE_OR_TIME",
                        help="Todo deadline for --update-progress.")
    parser.add_argument("--starts-at", default=None, metavar="ISO_TIME",
                        help="Confirmed event start for --update-progress.")
    parser.add_argument("--ends-at", default=None, metavar="ISO_TIME",
                        help="Optional confirmed event end (must follow start).")
    parser.add_argument("--timezone", default=None, metavar="IANA_ZONE",
                        help="Explicit event timezone, e.g. America/Los_Angeles.")
    parser.add_argument("--follow-up-at", default=None,
                        metavar="ISO_DATE_OR_TIME",
                        help="When to follow up if the current wait is unresolved.")
    parser.add_argument("--calendar-item", default=None, metavar="CAL_ID",
                        help="Target one linked occurrence when a role has more "
                             "than one calendar item.")
    parser.add_argument("--display-round", action="append", default=None,
                        metavar="TEXT",
                        help="With --update-progress: add one ordered round or "
                             "interviewer label to the targeted shared organizer "
                             "block. Repeat for each subslot.")
    parser.add_argument("--add-occurrence", action="store_true",
                        help="Append a distinct confirmed occurrence to the "
                             "role's calendar_items list; requires scheduled "
                             "state, --starts-at, and --timezone.")
    parser.add_argument("--check-calendar", action="store_true",
                        help="Verify calendar.md (markers, duplicate ids, "
                             "scheduled time+timezone) and its cross-links with "
                             "per-job progress. Read-only.")
    parser.add_argument("--sync-calendar", action="store_true",
                        help="Preview how owner edits to calendar.md (checked "
                             "boxes, reschedule_to, cancel) map back to progress. "
                             "Add --write to apply transactionally.")
    parser.add_argument("--refresh-calendar", action="store_true",
                        help="Preview re-rendering every managed row with visible "
                             "dates/actions, role links, compact markers, and the "
                             "generated in-progress company view. Add --write "
                             "to apply; metadata is untouched.")
    parser.add_argument("--html", action="store_true",
                        help="With --refresh-calendar: also preview or write the "
                             "optional offline calendar.html companion beside the "
                             "canonical Markdown calendar.")
    parser.add_argument("--write", action="store_true",
                        help="With --sync-calendar or --refresh-calendar: apply "
                             "the previewed proposals.")
    parser.add_argument("--sync-log", action="store_true",
                        help="Append every changed posting to the append-only "
                             "skip-log applications-log.jsonl (the postings "
                             "job-search skips) and upsert company-search-log.yaml "
                             "created entries. Never rewrites the log, so a "
                             "deleted folder does not un-skip its posting.")
    parser.add_argument("--backfill-log", action="store_true",
                        help="One-time seed of the append-only skip-log from the "
                             "UNION of the retired applications-log.yaml and the "
                             "application folders (the folder row wins a key in "
                             "both). Refuses when the log already exists; --force "
                             "appends a fresh generation instead.")
    parser.add_argument("--force", action="store_true",
                        help="With --backfill-log: append a fresh seed generation "
                             "even though the skip-log already exists (a later "
                             "line wins the fold; nothing is deleted).")
    parser.add_argument("--forget-log", nargs="+", metavar="VALUE",
                        help="Un-skip ONE posting by appending a tombstone: pass "
                             "one value (the posting URL) or two (COMPANY ROLE). "
                             "Refuses when that key is not currently folded — a "
                             "row that carries a URL is addressed by its URL.")
    parser.add_argument("--enrich-metadata", metavar="SLUG_OR_PATH",
                        help="Safely insert missing current-schema per-posting metadata "
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
    parser.add_argument("--company-keys", action="store_true",
                        help="Report company-key coverage (keyed / unkeyed / "
                             "unresolved). Coverage is a printed number, never a "
                             "gate; add --strict to exit 1 on a key that is not in "
                             "the index.")
    parser.add_argument("--strict", action="store_true",
                        help="With --company-keys: exit 1 when any company_key is "
                             "malformed, or does not resolve to a key in the "
                             "company index.")
    parser.add_argument("--statuses", default=None,
                        help="Comma-separated status folders for --check-locations, "
                             "--check-metadata, --backfill-metadata, or "
                             "--company-keys "
                             f"(default: all). Options: {', '.join(STATUS_FOLDERS)}.")
    args, extras = parser.parse_known_args()
    if extras:
        _reject_extra_args(parser, args, extras)

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
                        phase=args.phase, state=args.state, label=args.label,
                        email_ref=args.email_ref, action=args.action,
                        due_at=args.due_at, starts_at=args.starts_at,
                        ends_at=args.ends_at, timezone_name=args.timezone,
                        follow_up_at=args.follow_up_at,
                        calendar_item=args.calendar_item,
                        add_occurrence=args.add_occurrence,
                        display_rounds=args.display_round)
        return

    if args.check_calendar:
        sys.exit(0 if check_calendar(as_json=args.json) else 1)

    if args.sync_calendar:
        sys.exit(0 if sync_calendar(write=args.write, as_json=args.json) else 1)

    if args.refresh_calendar:
        sys.exit(0 if refresh_calendar(
            write=args.write, as_json=args.json, html_companion=args.html) else 1)

    if args.write:
        print("Error: --write requires --sync-calendar or --refresh-calendar",
              file=sys.stderr)
        sys.exit(1)

    if args.html:
        print("Error: --html requires --refresh-calendar",
              file=sys.stderr)
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

    # Both scan flags run when both are given. Each used to own an `if` block
    # ending in an unconditional `sys.exit`, so `--check-metadata
    # --check-locations` silently never reached the location check and reported a
    # clean exit 0 while out-of-policy locations went unexamined. Neither call is
    # short-circuited (the accumulator is the RIGHT operand of `and`), so each
    # check still prints its own report, and the exit code is non-zero if either
    # one fails.
    if args.check_metadata or args.check_locations:
        statuses = _resolve_statuses(args)
        ok = True
        if args.check_metadata:
            ok = check_metadata(statuses, as_json=args.json) and ok
        if args.check_locations:
            ok = check_locations(statuses, as_json=args.json) and ok
        sys.exit(0 if ok else 1)

    if args.company_keys:
        statuses = _resolve_statuses(args)
        ok = company_keys_report(statuses, strict=args.strict, as_json=args.json)
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

    if args.backfill_log:
        path, appended, folded, unreadable = backfill_log(force=args.force)
        print(f"Seeded the append-only skip-log -> {path}")
        print(f"  appended {appended} event(s); the fold now holds "
              f"{folded} posting(s)")
        print(f"  the old YAML log {APPLICATIONS_LOG} is no longer read or "
              "written by any tool. Remove it yourself once you are satisfied "
              "with the seed — agents never delete owner data.")
        if unreadable:
            _report_unwritable(unreadable, "seed")
            sys.exit(1)
        return

    if args.forget_log:
        forget_log(args.forget_log)
        return

    if args.force:
        print("Error: --force requires --backfill-log", file=sys.stderr)
        sys.exit(1)

    if args.sync_log:
        app_path, appended, search_path, unreadable = sync_log()
        if appended:
            print(f"Appended {appended} posting event(s) -> {app_path}")
        else:
            print(f"No posting changes — {app_path} unchanged")
        print(f"Updated company search log -> {search_path}")
        if unreadable:
            _report_unwritable(unreadable, "sync")
            sys.exit(1)
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
