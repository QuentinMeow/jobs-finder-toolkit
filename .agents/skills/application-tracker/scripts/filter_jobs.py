"""Filter and list job postings across the application status folders.

Unlike ``status.py`` (which prints one row per application FOLDER), this tool works
at POSTING granularity: it emits one row per ``jobs:`` entry, flattened across every
status folder (6_drafted, 5_applied, 4_in_progress, 3_rejected, 2_ignored). That is
the natural grain for questions like "show every remote senior posting I've applied to
that pays 200k+", because one application folder can cover several postings whose
per-job status, level, salary, and fit differ.

meta.yaml is read leniently: a missing or misshapen field never crashes — the row just
fails the corresponding filter. Files whose ``job_metadata_schema_version`` is not 4
get a one-line stderr warning; their ``jobs:`` entries (if any) are still listed
best-effort, but only v4 fields are read — there is no legacy-shape translation
(run the tracker's validators to find and fix such files).

Schema-v4 meta.yaml carries a per-job ``status`` (drafted|applied|in_progress|rejected
|ignored) — that field is what ``--status`` and the STATUS column use; the status
folder is its derived rollup and is reported separately as ``folder_status``.

Usage:
    .venv/bin/python .agents/skills/application-tracker/scripts/filter_jobs.py
    .venv/bin/python .agents/skills/application-tracker/scripts/filter_jobs.py --status applied,in_progress --sort date
    .venv/bin/python .agents/skills/application-tracker/scripts/filter_jobs.py --min-level 5.0 --workplace remote --json
    .venv/bin/python .agents/skills/application-tracker/scripts/filter_jobs.py --company stripe --min-salary 200000 --count
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Self-contained skill: this script lives in the application-tracker skill's scripts/
# folder alongside its _vendor/ copies of the pure toolkit modules. Put both the script
# folder and its _vendor/ on sys.path and import ONLY from those vendored modules
# (config for the applications root, layout for the status-folder mapping). status.py
# is deliberately not imported: this tool is read-only and must stay runnable no
# matter what state the mutating CLI is in.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

import yaml  # noqa: E402  (import after sys.path bootstrap, by design)

import config  # noqa: E402
from layout import STATUS_DIRS, STATUS_FOLDERS  # noqa: E402

SCHEMA_VERSION = 4

# Status labels ranked for --sort fit (best first) and for the folder-order status sort.
_FIT_RANK = {"strong": 3, "good": 2, "partial": 1}


# ── small lenient helpers ─────────────────────────────────────
def _s(value) -> str:
    """Coerce any scalar to a stripped string ('' for None)."""
    return "" if value is None else str(value).strip()


def _num_or_none(value):
    """Return value as a float, or None when it is missing/null/non-numeric.

    Booleans are treated as non-numeric (a stray ``true`` is not a level).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_date(value):
    """Parse a ``YYYY-MM-DD`` string to a date, or None if empty/unparseable."""
    text = _s(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_arg(text):
    """argparse type: a strict ``YYYY-MM-DD`` date for the date filters."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date {text!r}, expected YYYY-MM-DD")


def _csv(value):
    """Split a comma-separated flag into lowercased, stripped terms (None if unset).

    Comma-separated values are OR-combined within a single flag.
    """
    if value is None:
        return None
    terms = [t.strip().lower() for t in str(value).split(",") if t.strip()]
    return terms or None


def _sub_match(value, terms) -> bool:
    """True if `value` contains ANY term (case-insensitive substring). None terms pass."""
    if terms is None:
        return True
    haystack = str(value or "").lower()
    return any(t in haystack for t in terms)


def _mem_match(value, terms) -> bool:
    """True if `value` equals ANY term (case-insensitive membership). None terms pass."""
    if terms is None:
        return True
    return str(value or "").strip().lower() in terms


# ── display formatters ────────────────────────────────────────
def _fmt_num(x) -> str:
    """Render a level number: whole values keep one decimal ('5' -> '5.0')."""
    f = float(x)
    return f"{f:.1f}" if f.is_integer() else ("%g" % f)


def _fmt_level(lo, hi) -> str:
    """Render a job-level envelope: '5.0-5.7' / '5.0+' / '<=5.7' / '?'."""
    if lo is None and hi is None:
        return "?"
    if lo is not None and hi is not None:
        return f"{_fmt_num(lo)}–{_fmt_num(hi)}"
    if lo is not None:
        return f"{_fmt_num(lo)}+"
    return f"≤{_fmt_num(hi)}"


def _fmt_salary(lo, hi) -> str:
    """Render a salary range in thousands: '185-240k' / '185k+' / '<=240k' / ''."""
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is not None:
        return f"{round(lo / 1000)}–{round(hi / 1000)}k"
    if hi is not None:
        return f"≤{round(hi / 1000)}k"
    return f"{round(lo / 1000)}k+"


def _truncate(text, width) -> str:
    """Truncate `text` to `width` columns, marking elision with a single '...'."""
    s = str(text)
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width == 1:
        return "…"
    return s[:width - 1] + "…"


# ── row model ─────────────────────────────────────────────────
def _build_row(meta: dict, job: dict, folder_status: str, slug: str) -> dict:
    """Flatten one ``jobs:`` entry (plus its company-scope context) into a row.

    ``meta`` is the whole meta.yaml (company-scope fields); ``job`` is one entry from
    its ``jobs:`` list.
    """
    job_level = job.get("job_level") if isinstance(job.get("job_level"), dict) else None
    required_yoe = (job.get("required_yoe")
                    if isinstance(job.get("required_yoe"), dict) else None)
    salary_range = (job.get("salary_range")
                    if isinstance(job.get("salary_range"), dict) else None)

    fit = _s(job.get("fit"))
    per_job_status = _s(job.get("status"))

    level_min = _num_or_none(job_level.get("min")) if job_level else None
    level_max = _num_or_none(job_level.get("max")) if job_level else None
    sal_min = _num_or_none(salary_range.get("min")) if salary_range else None
    sal_max = _num_or_none(salary_range.get("max")) if salary_range else None
    yoe_min = _num_or_none(required_yoe.get("min")) if required_yoe else None

    posted_date = _s(job.get("posted_date"))
    research_date = _s(meta.get("research_date"))
    posted_parsed = _parse_date(posted_date)
    research_parsed = _parse_date(research_date)

    return {
        # ── public fields (emitted verbatim by --json) ──
        "status": per_job_status,          # per-job status ('' only in invalid files)
        "folder_status": folder_status,    # derived rollup: the folder the file lives in
        "company": _s(meta.get("company")),
        "role": _s(job.get("role")),
        "location": _s(job.get("location")),
        "workplace": _s(job.get("workplace")),
        "sponsorship": _s(job.get("sponsorship")),
        "fit": fit,
        "job_level": job_level,
        "required_yoe": required_yoe,
        "salary_range": salary_range,
        "posted_date": posted_date,
        "research_date": research_date,
        "channel": _s(meta.get("channel")),
        "stage": _s(job.get("stage")),
        "status_date": _s(job.get("status_date")),
        "url": _s(job.get("url")),
        "jd_file": _s(job.get("jd_file")),
        "slug": slug,
        "schema_version": meta.get("job_metadata_schema_version"),
        # ── internal derived fields (excluded from --json) ──
        "_fit_norm": fit.split()[0].lower() if fit else "",
        "_level_min": level_min,
        "_level_max": level_max,
        "_sal_min": sal_min,
        "_sal_max": sal_max,
        "_yoe_min": yoe_min,
        "_posted_parsed": posted_parsed,
        "_research_parsed": research_parsed,
        "_level_disp": _fmt_level(level_min, level_max),
        "_salary_disp": _fmt_salary(sal_min, sal_max),
    }


def _read_meta(path: Path):
    """Load a meta.yaml leniently. Returns a dict, or None (with a stderr note)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"warning: {path}: could not read/parse "
              f"({exc.__class__.__name__}); skipped", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"warning: {path}: meta.yaml is not a mapping; skipped",
              file=sys.stderr)
        return None
    return data


def _job_entries(meta: dict) -> list:
    """The postings to flatten from one meta.yaml: its ``jobs:`` list entries."""
    jobs = meta.get("jobs")
    if isinstance(jobs, list):
        return [j for j in jobs if isinstance(j, dict)]
    return []


def collect_rows() -> list:
    """Scan every status folder and flatten all postings to rows (job granularity)."""
    root = config.applications_root()
    rows = []
    for label in STATUS_FOLDERS:
        folder = root / STATUS_DIRS[label]
        if not folder.is_dir():
            continue
        for app_dir in sorted(folder.iterdir()):
            if not app_dir.is_dir() or app_dir.name.startswith("."):
                continue
            meta_file = app_dir / "meta.yaml"
            if not meta_file.exists():
                continue
            meta = _read_meta(meta_file)
            if meta is None:
                continue
            version = meta.get("job_metadata_schema_version")
            try:
                v_ok = int(version) == SCHEMA_VERSION
            except (TypeError, ValueError):
                v_ok = False
            if not v_ok:
                print(f"warning: {meta_file}: job_metadata_schema_version="
                      f"{version!r} (expected {SCHEMA_VERSION}); reading best-effort",
                      file=sys.stderr)
            for job in _job_entries(meta):
                rows.append(_build_row(meta, job, label, app_dir.name))
    return rows


# ── filtering ─────────────────────────────────────────────────
def matches(row: dict, f: dict) -> bool:
    """Apply every active filter (AND across flags, OR within a comma list)."""
    if not _mem_match(row["status"], f["status"]):
        return False
    if not _sub_match(row["company"], f["company"]):
        return False
    if not _sub_match(row["role"], f["role"]):
        return False
    if not _sub_match(row["location"], f["location"]):
        return False
    if not _sub_match(row["stage"], f["stage"]):
        return False
    if not _sub_match(row["slug"], f["slug"]):
        return False
    if not _sub_match(row["channel"], f["channel"]):
        return False
    if not _mem_match(row["workplace"], f["workplace"]):
        return False
    if not _mem_match(row["sponsorship"], f["sponsorship"]):
        return False
    if f["fit"] is not None and row["_fit_norm"] not in f["fit"]:
        return False

    # Level: overlap test against the [min,max] envelope; a null bound is unbounded
    # on that side; a posting with no numeric level is excluded when a level filter runs.
    if f["min_level"] is not None or f["max_level"] is not None:
        lo, hi = row["_level_min"], row["_level_max"]
        if lo is None and hi is None:
            return False
        want_lo = f["min_level"] if f["min_level"] is not None else float("-inf")
        want_hi = f["max_level"] if f["max_level"] is not None else float("inf")
        env_lo = lo if lo is not None else float("-inf")
        env_hi = hi if hi is not None else float("inf")
        if not (env_hi >= want_lo and env_lo <= want_hi):
            return False

    # Salary: max (or min when max is null) must clear the floor; null range excluded.
    if f["min_salary"] is not None:
        eff = row["_sal_max"] if row["_sal_max"] is not None else row["_sal_min"]
        if eff is None or eff < f["min_salary"]:
            return False

    # Required YOE: keep postings you qualify for (min <= cap); unknown min passes.
    if f["max_yoe"] is not None:
        if row["_yoe_min"] is not None and row["_yoe_min"] > f["max_yoe"]:
            return False

    # Posted-after / since: inclusive lower bound; missing/unparseable date excluded.
    if f["posted_after"] is not None:
        d = row["_posted_parsed"]
        if d is None or d < f["posted_after"]:
            return False
    if f["since"] is not None:
        d = row["_research_parsed"]
        if d is None or d < f["since"]:
            return False

    return True


def apply_sort(rows: list, name):
    """Return rows sorted by `name` (stable; None keeps folder+slug scan order)."""
    if name is None:
        return rows
    if name == "company":
        return sorted(rows, key=lambda r: r["company"].lower())
    if name == "status":
        order = {s: i for i, s in enumerate(STATUS_FOLDERS)}
        return sorted(rows, key=lambda r: order.get(r["status"], len(order)))
    if name == "date":
        # posted_date, falling back to research_date; newest first, undated last.
        return sorted(
            rows,
            key=lambda r: r["_posted_parsed"] or r["_research_parsed"] or date.min,
            reverse=True)
    if name == "level":
        return sorted(
            rows,
            key=lambda r: r["_level_max"] if r["_level_max"] is not None
            else float("-inf"),
            reverse=True)
    if name == "salary":
        def _sal_key(r):
            v = r["_sal_max"] if r["_sal_max"] is not None else r["_sal_min"]
            return v if v is not None else float("-inf")
        return sorted(rows, key=_sal_key, reverse=True)
    if name == "fit":
        return sorted(rows, key=lambda r: _FIT_RANK.get(r["_fit_norm"], 0),
                      reverse=True)
    return rows


# ── output ────────────────────────────────────────────────────
_COLUMNS = [
    ("STATUS", lambda r: r["status"], 11),
    ("COMPANY", lambda r: r["company"], 20),
    ("ROLE", lambda r: r["role"], 34),
    ("LOCATION", lambda r: r["location"], 22),
    ("WP", lambda r: r["workplace"], 7),
    ("SPONSOR", lambda r: r["sponsorship"], 9),
    ("FIT", lambda r: r["fit"], 8),
    ("LEVEL", lambda r: r["_level_disp"], 9),
    ("SALARY", lambda r: r["_salary_disp"], 9),
    ("POSTED", lambda r: r["posted_date"], 10),
    ("SLUG", lambda r: r["slug"], 30),
]


def print_table(rows: list):
    """Print an aligned, truncated table (auto-sized columns, capped per column)."""
    cells = [[_truncate(get(r), maxw) for _, get, maxw in _COLUMNS] for r in rows]
    widths = []
    for i, (name, _, maxw) in enumerate(_COLUMNS):
        longest = max([len(name)] + [len(row[i]) for row in cells])
        widths.append(min(maxw, longest))
    header = "  ".join(f"{name:<{widths[i]}}"
                       for i, (name, _, _) in enumerate(_COLUMNS))
    sep = "─" * len(header)
    print(sep)
    print(header)
    print(sep)
    for row in cells:
        print("  ".join(f"{_truncate(row[i], widths[i]):<{widths[i]}}"
                        for i in range(len(_COLUMNS))))
    print(sep)
    print(f"{len(rows)} job{'' if len(rows) == 1 else 's'}")


def _json_record(row: dict) -> dict:
    """The public record for --json (drops the internal `_`-prefixed derived keys)."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


_EPILOG = """\
examples:
  # active pipeline, newest posting first
  filter_jobs.py --status applied,in_progress --sort date

  # senior remote/hybrid roles I qualify for, as JSON for further processing
  filter_jobs.py --min-level 5.0 --workplace remote,hybrid --max-yoe 6 --json

  # how many Stripe postings pay at least 200k
  filter_jobs.py --company stripe --min-salary 200000 --count
"""


def main():
    parser = argparse.ArgumentParser(
        prog="filter_jobs.py",
        description="Filter job postings across the application status folders "
                    "(one row per posting).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG)

    # Filters (all optional; AND across flags, OR within a comma-separated flag).
    parser.add_argument("--status",
                        help="Per-job status (drafted,applied,in_progress,rejected,"
                             "ignored). Comma = OR.")
    parser.add_argument("--company", help="Company substring (case-insensitive).")
    parser.add_argument("--role", help="Role substring (case-insensitive).")
    parser.add_argument("--location", help="Location substring (case-insensitive).")
    parser.add_argument("--stage", help="Per-job stage substring (case-insensitive).")
    parser.add_argument("--slug", help="Application-folder slug substring.")
    parser.add_argument("--channel", help="Lead channel substring (case-insensitive).")
    parser.add_argument("--workplace",
                        help="onsite,hybrid,remote,unknown. Comma = OR.")
    parser.add_argument("--sponsorship",
                        help="likely,unlikely,unknown. Comma = OR.")
    parser.add_argument("--fit", help="strong,good,partial. Comma = OR.")
    parser.add_argument("--min-level", type=float,
                        help="Keep postings whose level envelope reaches >= F.")
    parser.add_argument("--max-level", type=float,
                        help="Keep postings whose level envelope reaches <= F.")
    parser.add_argument("--min-salary", type=int,
                        help="Keep postings whose salary max (or min) is >= N.")
    parser.add_argument("--max-yoe", type=int,
                        help="Keep postings whose required-YOE min is <= N "
                             "(unknown passes).")
    parser.add_argument("--posted-after", type=_date_arg, metavar="YYYY-MM-DD",
                        help="Keep postings posted on/after this date.")
    parser.add_argument("--since", type=_date_arg, metavar="YYYY-MM-DD",
                        help="Keep applications researched on/after this date "
                             "(research_date).")

    # Output.
    parser.add_argument("--json", action="store_true",
                        help="Emit full records as a JSON array.")
    parser.add_argument("--count", action="store_true",
                        help="Print only the number of matching postings.")
    parser.add_argument("--sort",
                        choices=["company", "date", "level", "salary", "fit", "status"],
                        help="Sort the results. date=newest first; level/salary by max "
                             "desc (nulls last); fit strong>good>partial.")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="Show at most N postings (after sorting).")

    args = parser.parse_args()

    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be >= 0")

    filters = {
        "status": _csv(args.status),
        "company": _csv(args.company),
        "role": _csv(args.role),
        "location": _csv(args.location),
        "stage": _csv(args.stage),
        "slug": _csv(args.slug),
        "channel": _csv(args.channel),
        "workplace": _csv(args.workplace),
        "sponsorship": _csv(args.sponsorship),
        "fit": _csv(args.fit),
        "min_level": args.min_level,
        "max_level": args.max_level,
        "min_salary": args.min_salary,
        "max_yoe": args.max_yoe,
        "posted_after": args.posted_after,
        "since": args.since,
    }

    rows = [r for r in collect_rows() if matches(r, filters)]
    rows = apply_sort(rows, args.sort)
    if args.limit is not None:
        rows = rows[:args.limit]

    if args.count:
        print(len(rows))
        return

    if not rows:
        print("no matching jobs", file=sys.stderr)
        if args.json:
            print("[]")
        return

    if args.json:
        print(json.dumps([_json_record(r) for r in rows], indent=2))
    else:
        print_table(rows)


if __name__ == "__main__":
    main()
