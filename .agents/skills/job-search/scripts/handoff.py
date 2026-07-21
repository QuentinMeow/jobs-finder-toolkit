#!/usr/bin/env python3
"""Bridge a ranked search result into a scaffolded application folder.

Usage:
  .venv/bin/python .agents/skills/job-search/scripts/handoff.py \
      --json <search.json> --select <"rank N" | "Company/Title"> \
      [--applications-root DIR] [--status-dir 6_drafted] \
      [--research-date YYYY-MM-DD] [--skip-jd-fetch]

``search.json`` is what ``search_jobs.py --json-out`` writes: a list of posting
records (``JobPosting.to_dict()``), score-ranked. This tool takes ONE selected
row and does the deterministic, transcription-error-prone folder setup so the
drafting agent can start at gap analysis instead of re-transcribing ~10 fields:

1. Create ``<applications_root>/<status-dir>/<slug>/`` per the AGENTS.md
   Application Folder Convention (``<company>-<role>-<YYYYMMDD>`` slug). The tool
   REFUSES to overwrite an existing folder.
2. Save ``source/JD-<job title>.md`` VERBATIM via the sibling ``fetch_jd`` module
   (imported, never subprocessed; exactly one fetch). If the fetch fails the
   folder is still scaffolded, but the tool exits non-zero telling the agent to
   save the JD manually.
3. Write ``meta.yaml`` (schema v4), carrying over every structured fact the search
   row already computed — level, YOE, salary, workplace, sponsorship, location,
   URL, posted date, source channel — using the vendored ``metadata_editor``
   (the same formatting-preserving editor the tracker's ``--enrich-metadata``
   uses, so a later enrich is a no-op). Facts the row lacks are NOT invented; they
   are left for the tracker's ``status.py --enrich-metadata`` follow-up.
4. Validate with the vendored ``job_metadata`` validator before exit. On failure
   the tool exits non-zero and lists what is missing.

Stdout is exactly two lines: the folder path and the meta.yaml validation status.
Everything else (fetch notes, gap diagnostics) goes to stderr.

Self-contained: this script imports only its own sibling ``fetch_jd`` and the
vendored ``job_metadata`` / ``metadata_editor`` modules. It never subprocesses
another skill's scripts; the tracker's ``--enrich-metadata`` / ``--check-metadata``
remain agent-invoked follow-ups.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Self-contained skill: this script's own scripts/ (for the sibling fetch_jd
# module) and its vendored copies under _vendor/ go on sys.path. _vendor/ is on
# the path directly so metadata_editor can `import job_metadata` as a sibling.
_SKILL_SCRIPTS = Path(__file__).resolve().parent
_VENDOR = _SKILL_SCRIPTS / "_vendor"
for _p in (str(_SKILL_SCRIPTS), str(_VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fetch_jd  # noqa: E402  (sibling skill module)
from job_metadata import (  # noqa: E402
    APPLICATION_SCHEMA_VERSION,
    POSTING_METADATA_FIELDS,
    SPONSORSHIP_VALUES,
    WORKPLACE_VALUES,
    validate_meta,
)
from metadata_editor import plan_metadata_edit  # noqa: E402

DEFAULT_STATUS_DIR = "6_drafted"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_RANK_RE = re.compile(r"^\s*(?:rank\s+)?(\d+)\s*$", re.I)


# --------------------------------------------------------------------------- #
# Row selection
# --------------------------------------------------------------------------- #
def load_rows(json_path: Path) -> list[dict]:
    """Load the search-JSON list of posting records."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not read search JSON {json_path}: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ValueError(
            f"{json_path} is not a non-empty list of postings "
            "(expected search_jobs.py --json-out output)"
        )
    rows = [row for row in data if isinstance(row, dict)]
    if not rows:
        raise ValueError(f"{json_path} contains no posting records")
    return rows


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def select_row(rows: list[dict], selector: str) -> dict:
    """Select one posting by ``rank N`` (1-based) or ``Company/Title``."""
    rank_match = _RANK_RE.match(selector)
    if rank_match:
        rank = int(rank_match.group(1))
        if not 1 <= rank <= len(rows):
            raise ValueError(
                f"rank {rank} is out of range (1..{len(rows)} postings available)"
            )
        return rows[rank - 1]

    if "/" not in selector:
        raise ValueError(
            f"--select {selector!r} is neither a rank ('rank N') nor a "
            "'Company/Title' pair"
        )
    company, title = selector.split("/", 1)
    matches = [
        row for row in rows
        if _norm(row.get("company")) == _norm(company)
        and _norm(row.get("title")) == _norm(title)
    ]
    if not matches:
        raise ValueError(
            f"no posting matches company/title {selector!r}; "
            "use the exact company and title from the search table"
        )
    if len(matches) > 1:
        raise ValueError(
            f"company/title {selector!r} matches {len(matches)} postings; "
            "select by rank instead"
        )
    return matches[0]


# --------------------------------------------------------------------------- #
# Slugs and paths
# --------------------------------------------------------------------------- #
def slugify(text: str) -> str:
    """Lowercase, hyphen-separated, alphanumeric-only slug (per AGENTS.md)."""
    return _SLUG_RE.sub("-", str(text or "").casefold()).strip("-")


def folder_slug(company: str, role: str, date_str: str) -> str:
    """``<company>-<role>-<YYYYMMDD>`` folder slug for an application."""
    stamp = date_str.replace("-", "")
    parts = [slugify(company), slugify(role), stamp]
    return "-".join(part for part in parts if part)


def jd_filename(role: str) -> str:
    """``JD-<job title>.md`` — the exact per-posting JD file name."""
    return f"JD-{slugify(role)}.md"


def _applications_root(override: str | None) -> Path:
    """Applications root: the CLI override, else the vendored config default."""
    if override:
        return Path(override).expanduser().resolve()
    import config  # vendored; imported lazily so --applications-root needs no config
    return config.applications_root()


# --------------------------------------------------------------------------- #
# JD fetch (verbatim, via the sibling fetch_jd module)
# --------------------------------------------------------------------------- #
def save_jd(url: str, jd_path: Path) -> tuple[bool, str]:
    """Save the JD verbatim via fetch_jd.main; return (ok, message).

    fetch_jd owns the whole extraction/idempotency/warning path. Its stdout/stderr
    are captured so handoff.py keeps its own stdout to the two-line contract; the
    captured text is relayed to the caller for the message.
    """
    if not url:
        return False, "posting row has no URL; save the JD manually"
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fetch_jd.main([url, "--out", str(jd_path)])
    detail = (err.getvalue() or out.getvalue()).strip()
    if code != 0:
        return False, detail or f"fetch_jd failed for {url}"
    return True, detail


# --------------------------------------------------------------------------- #
# meta.yaml (schema v4)
# --------------------------------------------------------------------------- #
def carry_metadata(row: dict) -> dict:
    """Carry the row's structured metadata into the schema-v4 posting shape.

    Every one of ``POSTING_METADATA_FIELDS`` is present (the editor requires the
    full set), but values are only carried when the row actually provides them:
    an absent workplace/sponsorship becomes ``""`` and an absent level/YOE becomes
    ``{}`` — both invalid on purpose, so validation fails loud and the tracker's
    ``--enrich-metadata`` fills the gap from the JD rather than handoff inventing a
    value. ``salary_range`` is legitimately nullable (many postings state no pay).
    """
    workplace = _norm(row.get("workplace"))
    if workplace not in WORKPLACE_VALUES:
        remote = _norm(row.get("remote"))  # raw scraper flag, same value domain
        workplace = remote if remote in WORKPLACE_VALUES else ""

    sponsorship = _norm(row.get("sponsorship"))
    if sponsorship not in SPONSORSHIP_VALUES:
        sponsorship = ""

    level = row.get("job_level")
    required_yoe = row.get("required_yoe")
    salary = row.get("salary_range")
    return {
        "workplace": workplace,
        "sponsorship": sponsorship,
        "job_level": level if isinstance(level, dict) and level else {},
        "required_yoe": required_yoe if isinstance(required_yoe, dict) and required_yoe else {},
        "salary_range": salary if isinstance(salary, dict) and salary else None,
    }


def _posted_date(row: dict) -> str:
    """The posting's date (YYYY-MM-DD) from ``posted_at``, or ``""``."""
    raw = str(row.get("posted_at") or "").strip()
    return raw[:10] if raw else ""


def build_meta_bytes(row: dict, *, jd_file: str, research_date: str) -> tuple[bytes, list[str]]:
    """Build meta.yaml bytes for the row; return (bytes, editor_errors).

    A scaffold (company scope + one job entry of descriptive fields) is rendered
    first, then the vendored ``plan_metadata_edit`` inserts the five metadata
    fields carried from the row — the same formatting-preserving path the tracker
    uses. If the carried metadata is incomplete/invalid the editor returns the
    scaffold unchanged (no metadata) so the failure surfaces in validation and the
    tracker can enrich it; ``editor_errors`` explains why nothing was carried.
    """
    scaffold = {
        "job_metadata_schema_version": APPLICATION_SCHEMA_VERSION,
        "company": str(row.get("company") or ""),
        "research_date": research_date,
        "channel": str(row.get("source") or ""),
        "jobs": [
            {
                "role": str(row.get("title") or ""),
                "jd_file": jd_file,
                # Handoff always creates a fresh DRAFTED application.
                "status": "drafted",
                "location": str(row.get("location") or ""),
                "url": str(row.get("url") or ""),
                "posted_date": _posted_date(row),
            }
        ],
    }
    raw = yaml.safe_dump(
        scaffold,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    ).encode("utf-8")

    generated = {("jobs", 0): carry_metadata(row)}
    plan = plan_metadata_edit(raw, generated)
    # On success output_bytes is the filled meta.yaml; on any editor error it is
    # the scaffold unchanged (fail-closed), which validation then flags.
    return plan.output_bytes, list(plan.errors)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    rows = load_rows(Path(args.json).expanduser())
    row = select_row(rows, args.select)

    company = str(row.get("company") or "").strip()
    role = str(row.get("title") or "").strip()
    if not company:
        raise ValueError("selected posting has no company; cannot build a folder slug")
    if not role:
        raise ValueError("selected posting has no title; cannot build a folder slug")

    research_date = args.research_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    root = _applications_root(args.applications_root)
    slug = folder_slug(company, role, research_date)
    folder = root / args.status_dir / slug

    if folder.exists():
        print(
            f"handoff: refusing to overwrite existing folder: {folder}",
            file=sys.stderr,
        )
        return 2

    jd_file = jd_filename(role)
    source_dir = folder / "source"
    source_dir.mkdir(parents=True, exist_ok=False)

    # --- JD (verbatim, exactly one fetch) --------------------------------- #
    jd_ok = True
    if args.skip_jd_fetch:
        jd_ok = False
        print(
            f"handoff: --skip-jd-fetch set; save {source_dir / jd_file} manually.",
            file=sys.stderr,
        )
    else:
        jd_ok, jd_msg = save_jd(str(row.get("url") or ""), source_dir / jd_file)
        if not jd_ok:
            print(
                f"handoff: JD not saved ({jd_msg}); scaffolded the folder anyway "
                f"— save {source_dir / jd_file} manually before drafting.",
                file=sys.stderr,
            )

    # --- meta.yaml (schema v4, facts carried from the row) ---------------- #
    meta_bytes, editor_errors = build_meta_bytes(
        row, jd_file=jd_file, research_date=research_date)
    (folder / "meta.yaml").write_bytes(meta_bytes)
    for message in editor_errors:
        print(f"handoff: metadata not carried: {message}", file=sys.stderr)

    # --- validate (vendored job_metadata) --------------------------------- #
    meta = yaml.safe_load(meta_bytes.decode("utf-8"))
    errors = validate_meta(meta, app_dir=folder)

    print(folder)
    print(f"meta.yaml: {'valid' if not errors else 'INVALID'}")
    if errors:
        print("handoff: meta.yaml is not yet complete:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "handoff: run "
            "`status.py --enrich-metadata <slug>` to fill JD-derived facts, "
            "then `status.py --check-metadata`.",
            file=sys.stderr,
        )
    return 0 if (errors == [] and jd_ok) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Scaffold an application folder from a ranked search result.")
    ap.add_argument("--json", required=True,
                    help="search_jobs.py --json-out file (list of posting records).")
    ap.add_argument("--select", required=True,
                    help='Which posting: "rank N" (1-based) or "Company/Title".')
    ap.add_argument("--applications-root", default=None,
                    help="Applications root (default: the vendored config value).")
    ap.add_argument("--status-dir", default=DEFAULT_STATUS_DIR,
                    help="Status subfolder to create the application under "
                         "(default: %(default)s — new applications are always "
                         "created in 6_drafted per the Folder Convention).")
    ap.add_argument("--research-date", default=None,
                    help="Search/handoff date YYYY-MM-DD (default: today, UTC); "
                         "also the folder-slug date stamp.")
    ap.add_argument("--skip-jd-fetch", action="store_true",
                    help="Do not fetch the JD (offline/testing); the folder is "
                         "scaffolded but exits non-zero so the JD is saved manually.")
    args = ap.parse_args(argv)

    try:
        return run(args)
    except ValueError as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
