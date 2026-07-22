#!/usr/bin/env python3
"""Bridge a ranked search result into a scaffolded application folder.

Usage:
  .venv/bin/python skills/job-search/scripts/handoff.py \
      --json <search.json> (--select <"rank N" | "Company/Title"> | --all) \
      [--applications-root DIR] [--status-dir 6_drafted] \
      [--research-date YYYY-MM-DD] [--skip-jd-fetch] \
      [--allow-location-mismatch] [--report REPORT.json]

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
3. Write ``meta.yaml`` (schema v5), carrying over every structured fact the search
   row already computed — level, YOE, salary, workplace, sponsorship, location,
   URL, posted date, source channel — using the vendored ``metadata_editor``
   (the same formatting-preserving editor the tracker's ``--enrich-metadata``
   uses, so a later enrich is a no-op). Facts the row lacks are NOT invented; they
   are left for the tracker's ``status.py --enrich-metadata`` follow-up.
4. Validate with the vendored ``job_metadata`` validator before exit. On failure
   the tool exits non-zero and lists what is missing.
5. Run the SAME location-policy check the tracker's ``status.py --check-locations``
   uses (via the vendored ``location`` module + ``config.location_policy``). A
   definite mismatch (a foreign posting or a non-preferred US office) LEAVES the
   folder on disk, prints the verdict + the offending location string + a one-line
   remedy to stderr, and exits non-zero (code 3) unless ``--allow-location-mismatch``
   is passed. This catches a wrong-metro / foreign posting at handoff — before the
   drafting leg pays for it — instead of only when the tracker gate runs later. A
   blank / unrecognized location is surfaced for manual review but does NOT block
   (identical to the tracker's ``review`` vs ``mismatch`` split).

Stdout is exactly two lines: the folder path and the meta.yaml validation status.
Everything else (fetch notes, gap diagnostics, the location verdict) goes to stderr.

Self-contained: this script imports only its own sibling ``fetch_jd`` and the
vendored ``job_metadata`` / ``metadata_editor`` / ``location`` / ``config`` modules.
It never subprocesses another skill's scripts; the tracker's ``--enrich-metadata`` /
``--check-metadata`` / ``--check-locations`` remain agent-invoked follow-ups.
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
from location import (  # noqa: E402  (vendored shared location policy)
    classify_location,
    classify_locations,
    extract_jd_locations,
    is_match,
)

DEFAULT_STATUS_DIR = "6_drafted"
LIVE_STATUS_DIRS = (
    "6_drafted", "5_applied", "4_in_progress", "3_rejected", "2_ignored",
)

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


def _posting_keys(root: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """Collect URL and company/role duplicate keys from logs and live folders."""
    urls: set[str] = set()
    pairs: set[tuple[str, str]] = set()

    log_path = root / "0_profile" / "applications-log.yaml"
    if log_path.exists():
        data = yaml.safe_load(log_path.read_text(encoding="utf-8")) or {}
        for posting in data.get("postings") or []:
            if not isinstance(posting, dict):
                continue
            url = _norm(posting.get("url"))
            company = _norm(posting.get("company"))
            role = _norm(posting.get("role"))
            if url:
                urls.add(url.rstrip("/"))
            if company and role:
                pairs.add((company, role))

    for status in LIVE_STATUS_DIRS:
        status_dir = root / status
        if not status_dir.exists():
            continue
        for meta_path in status_dir.glob("*/meta.yaml"):
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            company = _norm(meta.get("company"))
            jobs = meta.get("jobs") or []
            if not jobs and meta.get("role"):
                jobs = [{"role": meta.get("role"), "url": meta.get("url")}]
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                url = _norm(job.get("url"))
                role = _norm(job.get("role"))
                if url:
                    urls.add(url.rstrip("/"))
                if company and role:
                    pairs.add((company, role))
    return urls, pairs


def _duplicate_reason(
    row: dict,
    urls: set[str],
    pairs: set[tuple[str, str]],
) -> str | None:
    url = _norm(row.get("url")).rstrip("/")
    pair = (_norm(row.get("company")), _norm(row.get("title")))
    if url and url in urls:
        return "same URL already exists in the log or a live application folder"
    if all(pair) and pair in pairs:
        return "same company and role already exists in the log or a live folder"
    return None


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


_STALE_LAST_SEEN_DAYS = 7


def warn_if_stale(store_key: str) -> None:
    """Warn (stderr) when the store's local last_seen for this posting is stale.

    Queries the LOCAL index by key only (no network); the store never says
    "closed", so a stale last_seen is a prompt to re-check the live board. Fully
    guarded — a disabled/missing store is silent, never an error.
    """
    if not store_key:
        return
    try:
        import config
        data_root = config.data_root()
        if data_root is None:
            return
        from _vendor.store.atomic import read_jsonl
        from _vendor.store.paths import domain_layout
        layout = domain_layout(data_root, "jobs")
        rows = read_jsonl(layout.index / "postings.jsonl")
        row = next((r for r in (rows[1:] if rows else [])
                    if r.get("key") == store_key), None)
        last_seen = row.get("last_seen") if row else None
        if not last_seen:
            return
        seen = datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - seen).days
        if age > _STALE_LAST_SEEN_DAYS:
            print(
                f"handoff: STALE — the store last observed this posting {age} days "
                f"ago (last_seen {last_seen}). The store never says 'closed'; "
                f"re-check the live board before drafting.", file=sys.stderr)
    except Exception:  # noqa: BLE001 — the staleness hint must never break handoff
        return


# --------------------------------------------------------------------------- #
# meta.yaml (schema v5)
# --------------------------------------------------------------------------- #
def carry_metadata(row: dict) -> dict:
    """Carry the row's structured metadata into the schema-v5 posting shape.

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
    job_entry = {
        "role": str(row.get("title") or ""),
        "jd_file": jd_file,
        # Handoff always creates a fresh DRAFTED application; schema v5 pairs
        # that with the deterministic drafted progress summary.
        "status": "drafted",
        "progress": {"phase": "application_prep", "state": "action_required"},
        "location": str(row.get("location") or ""),
        "url": str(row.get("url") or ""),
        "posted_date": _posted_date(row),
    }
    # Durable link to the posting's store biography — COPIED verbatim from the
    # search JSON (handoff never re-derives identity). Additive optional field.
    store_key = str(row.get("store_key") or "").strip()
    if store_key:
        job_entry["store_key"] = store_key
    scaffold = {
        "job_metadata_schema_version": APPLICATION_SCHEMA_VERSION,
        "company": str(row.get("company") or ""),
        "research_date": research_date,
        "channel": str(row.get("source") or ""),
        "jobs": [job_entry],
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
# Location policy gate (mirrors status.py --check-locations for one folder)
# --------------------------------------------------------------------------- #
def gather_locations(meta: dict, folder: Path) -> list[str]:
    """Every posting-location string for the scaffolded application.

    Mirrors the tracker's ``app_locations``: prefer the ``location`` recorded in
    meta.yaml (top-level, then each ``jobs:`` entry); fall back to the ``Location:``
    line(s) of any saved ``source/JD-*.md`` when meta.yaml records none.
    """
    locs: list[str] = []
    top = str(meta.get("location") or "").strip()
    if top:
        locs.append(top)
    jobs = meta.get("jobs")
    if isinstance(jobs, list):
        for job in jobs:
            if isinstance(job, dict) and str(job.get("location") or "").strip():
                locs.append(str(job["location"]).strip())
    if locs:
        return locs
    source_dir = folder / "source"
    if source_dir.is_dir():
        for jd in sorted(source_dir.glob("JD-*.md")):
            try:
                locs.extend(extract_jd_locations(jd.read_text(encoding="utf-8")))
            except OSError:
                continue
    return locs


def check_location_policy(meta: dict, folder: Path) -> tuple[str, str, list[str], list[tuple[str, str]]]:
    """Classify the folder's location(s) against ``config.location_policy()``.

    Returns ``(verdict, category, locations, offending)`` where ``verdict`` is
    ``"match"`` (a preferred-metro or US-remote posting), ``"mismatch"`` (a definite
    policy violation — foreign or non-preferred US office) or ``"review"`` (blank /
    unrecognized location). This is the exact split the tracker's
    ``status.py --check-locations`` uses: only a definite ``mismatch`` is a hard
    failure; ``review`` rows are surfaced but do not block. ``offending`` lists the
    ``(location, category)`` pairs that fail the policy (populated for a mismatch).
    """
    import config  # vendored toolkit loader (location policy)
    policy = config.location_policy()
    locs = gather_locations(meta, folder)
    category, matched = classify_locations(locs, policy)
    if matched:
        return "match", category, locs, []
    if category == "unknown":
        return "review", category, locs, []
    offending = [
        (loc, classify_location(loc, policy))
        for loc in locs
        if not is_match(classify_location(loc, policy))
    ]
    return "mismatch", category, locs, offending


def report_location(
    verdict: str,
    category: str,
    locs: list[str],
    offending: list[tuple[str, str]],
    folder: Path,
    *,
    allow_mismatch: bool,
) -> bool:
    """Emit the location verdict to stderr; return True iff drafting is blocked.

    Keeps handoff's two-line stdout contract intact — every location message goes
    to stderr alongside the other diagnostics. ``match`` and ``review`` are one
    confirmation line each and never block; a ``mismatch`` blocks (returns True)
    unless ``allow_mismatch`` overrides it.
    """
    shown = " | ".join(locs) if locs else "(none recorded)"
    if verdict == "match":
        print(f"handoff: location OK [{category}]: {shown}", file=sys.stderr)
        return False
    if verdict == "review":
        print(
            f"handoff: location NOT classifiable [{category}]: {shown} — review "
            "it against the location policy manually before drafting.",
            file=sys.stderr,
        )
        return False
    # Definite mismatch (foreign / non-preferred US office).
    detail = " | ".join(f"{loc} [{cat}]" for loc, cat in offending) or shown
    print(
        f"handoff: LOCATION POLICY MISMATCH [{category}] — this posting is outside "
        f"the configured location policy: {detail}",
        file=sys.stderr,
    )
    if allow_mismatch:
        print(
            "handoff: --allow-location-mismatch set; keeping the folder and "
            "proceeding despite the mismatch.",
            file=sys.stderr,
        )
        return False
    print(
        f"handoff: remedy — delete the folder ({folder}), or rerun with "
        "--allow-location-mismatch if this location is intentional.",
        file=sys.stderr,
    )
    return True


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _run_row(row: dict, args: argparse.Namespace) -> tuple[int, Path]:
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
        return 2, folder

    jd_file = jd_filename(role)
    source_dir = folder / "source"
    source_dir.mkdir(parents=True, exist_ok=False)

    # --- JD (verbatim, exactly one fetch) --------------------------------- #
    # Fresh-JD refusal (store-is-never-verification): scaffolding without a
    # session-fresh JD is NOT allowed — the store is memory that routes attention,
    # never a substitute for the JD text you act on. A skip or a failed fetch is an
    # explicit refusal (non-zero exit); there is no override flag.
    jd_ok = True
    if args.skip_jd_fetch:
        jd_ok = False
        print(
            f"handoff: REFUSING to treat this as ready — --skip-jd-fetch means no "
            f"session-fresh JD, and the store is never a verification substitute. "
            f"Save {source_dir / jd_file} live this session before drafting.",
            file=sys.stderr,
        )
    else:
        jd_ok, jd_msg = save_jd(str(row.get("url") or ""), source_dir / jd_file)
        if not jd_ok:
            print(
                f"handoff: REFUSING to treat this as ready — no session-fresh JD "
                f"({jd_msg}), and the store is never a verification substitute; you "
                f"must act on the live JD text, not stored facts. The folder is "
                f"scaffolded but NOT draftable until you save "
                f"{source_dir / jd_file} live this session. If the page is "
                "JS-rendered, recover the verbatim JD via `company_roles.py --jd`; "
                "if no fetch works at all (e.g. HTTP 403), save the scraper-extracted "
                "text with a non-verbatim provenance note (reference.md § "
                "\"Recovering a JD when the page fetch is unusable\").",
                file=sys.stderr,
            )

    # Stale-posting hint (local store lookup by the copied store_key; never blocks).
    warn_if_stale(str(row.get("store_key") or "").strip())

    # --- meta.yaml (schema v5, facts carried from the row) ---------------- #
    meta_bytes, editor_errors = build_meta_bytes(
        row, jd_file=jd_file, research_date=research_date)
    (folder / "meta.yaml").write_bytes(meta_bytes)
    for message in editor_errors:
        print(f"handoff: metadata not carried: {message}", file=sys.stderr)

    # --- validate (vendored job_metadata) --------------------------------- #
    meta = yaml.safe_load(meta_bytes.decode("utf-8"))
    errors = validate_meta(meta, app_dir=folder)

    # --- location policy gate (same verdict as status.py --check-locations)  #
    loc_verdict, loc_cat, loc_locs, loc_offending = check_location_policy(meta, folder)

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

    # Location policy gate. A definite mismatch is the highest-priority failure
    # ("do not draft this posting at all"), so it wins over an incomplete-metadata
    # / missing-JD exit; ``--allow-location-mismatch`` downgrades it to a warning.
    location_blocked = report_location(
        loc_verdict, loc_cat, loc_locs, loc_offending, folder,
        allow_mismatch=args.allow_location_mismatch,
    )
    if location_blocked:
        return 3, folder
    return (0 if (errors == [] and jd_ok) else 1), folder


# Exit codes _run_row returns, mapped to a bulk-report row status. A location
# mismatch is auditable as its own status/count (distinct from an incomplete
# scaffold) so a bulk run's report shows exactly why each folder is not clean.
_BULK_STATUS_BY_CODE = {0: "created", 3: "location_mismatch"}


def _run_bulk(rows: list[dict], args: argparse.Namespace) -> int:
    root = _applications_root(args.applications_root)
    urls, pairs = _posting_keys(root)
    report: list[dict] = []
    counts = {
        "created": 0,
        "incomplete": 0,
        "location_mismatch": 0,
        "duplicate": 0,
        "failed": 0,
    }

    for index, row in enumerate(rows, 1):
        reason = _duplicate_reason(row, urls, pairs)
        if reason:
            counts["duplicate"] += 1
            report.append({
                "rank": index,
                "company": row.get("company"),
                "title": row.get("title"),
                "url": row.get("url"),
                "status": "duplicate",
                "detail": reason,
            })
            print(
                f"handoff: skipped duplicate rank {index}: "
                f"{row.get('company')} / {row.get('title')} ({reason})",
                file=sys.stderr,
            )
            continue

        try:
            code, folder = _run_row(row, args)
        except ValueError as exc:
            counts["failed"] += 1
            report.append({
                "rank": index,
                "company": row.get("company"),
                "title": row.get("title"),
                "url": row.get("url"),
                "status": "failed",
                "detail": str(exc),
            })
            print(f"handoff: rank {index} failed: {exc}", file=sys.stderr)
            continue

        status = _BULK_STATUS_BY_CODE.get(code, "incomplete")
        counts[status] += 1
        report.append({
            "rank": index,
            "company": row.get("company"),
            "title": row.get("title"),
            "url": row.get("url"),
            "status": status,
            "folder": str(folder),
            "exit_code": code,
        })
        # A partial scaffold (or a mismatch folder left for review) is still a live
        # folder and must block a second row.
        url = _norm(row.get("url")).rstrip("/")
        pair = (_norm(row.get("company")), _norm(row.get("title")))
        if url:
            urls.add(url)
        if all(pair):
            pairs.add(pair)

    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"counts": counts, "rows": report}, indent=2),
            encoding="utf-8",
        )
    print(
        "Bulk handoff: "
        + " | ".join(f"{key}={value}" for key, value in counts.items())
    )
    # Any non-clean outcome (incomplete scaffold, location mismatch, or a hard
    # failure) makes the bulk run exit non-zero.
    return 1 if (
        counts["incomplete"] or counts["location_mismatch"] or counts["failed"]
    ) else 0


def run(args: argparse.Namespace) -> int:
    rows = load_rows(Path(args.json).expanduser())
    if args.select_all:
        return _run_bulk(rows, args)
    row = select_row(rows, args.select)
    code, _folder = _run_row(row, args)
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Scaffold an application folder from a ranked search result.")
    ap.add_argument("--json", required=True,
                    help="search_jobs.py --json-out file (list of posting records).")
    selection = ap.add_mutually_exclusive_group(required=True)
    selection.add_argument("--select",
                           help='Which posting: "rank N" (1-based) or "Company/Title".')
    selection.add_argument("--all", dest="select_all", action="store_true",
                           help="Scaffold every row after duplicate preflight.")
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
    ap.add_argument("--allow-location-mismatch", action="store_true",
                    help="Proceed even when the posting's location is outside the "
                         "configured location policy (foreign / non-preferred US "
                         "office). Without this flag a definite mismatch leaves the "
                         "folder on disk and exits non-zero (code 3).")
    ap.add_argument("--report", default=None,
                    help="Optional JSON report path for --all results (counts + "
                         "per-row status, including location_mismatch).")
    args = ap.parse_args(argv)

    try:
        return run(args)
    except ValueError as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
