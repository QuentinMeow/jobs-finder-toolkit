#!/usr/bin/env python3
"""Search job boards + aggregators for postings matching a job-matching profile.

Usage:
  .venv/bin/python .agents/skills/job-search/scripts/search_jobs.py \
      [--profile <label>] [--stage 1|2] [--max-age-days 3] [--top-k 40] \
      [--visa-policy exclude_negative|require_positive] [--ai-native-only] \
      [--company-tags ai-lab,ai-infra] [--aggregators jobicy,themuse] \
      [--jobspy] [--no-jobspy] [--no-companies] [--out <discoveries_dir>/DATE-label.md]

The --profile default and the applications-log / company-search-log / discoveries
output locations come from the toolkit config layer (config.job_search.default_profile
and config.paths.*), so nothing candidate-specific is hardcoded here. When no config
is available the profile falls back to "default" and paths fall back under the repo's
applications/ tree.

Two search STAGES (all feed one filter/score/rank pipeline):
  Stage 1 (default, reliable, every use case): company ATS boards from
    companies.yaml + keyless aggregators (Jobicy/RemoteOK/The Muse) + JobSpy on its
    reliable sites (Indeed + Google). Free, no API keys, fast.
  Stage 2 (--stage 2, extended, opt-in): everything in stage 1 PLUS JobSpy on its
    extended sites (LinkedIn/Glassdoor) + keyed aggregators (Adzuna/JSearch) that
    activate only when their API keys are set.

Pipeline: fetch (threaded) -> normalize -> filter (date/title/location/visa/
AI-native) -> score (incl. AI-native-company boost) -> dedupe -> rank.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

# Self-contained skill: put this skill's own scripts/ (sibling modules) and the
# vendored copies under _vendor/ on sys.path. The candidate identity, paths, and
# profile default all come from the vendored config loader — never hardcoded here.
# _vendor/ itself goes on the path so config.py can `import layout` as a sibling
# (mirrors how the skill already imports the vendored location module).
SKILL_SCRIPTS = Path(__file__).resolve().parent
_VENDOR = SKILL_SCRIPTS / "_vendor"
for _p in (str(SKILL_SCRIPTS), str(_VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from aggregators import (  # noqa: E402
    KEYED, KEYLESS, build_aggregator_tasks, build_jobspy_tasks, jobspy_available,
    keyed_available,
)
from common import days_since  # noqa: E402
from job_metadata import analyze_job_metadata, load_company_levels  # noqa: E402
from registry import Registry, load_registry  # noqa: E402
from scoring import (  # noqa: E402
    ai_company_ok, date_ok, experience_ok, location_ok, score_posting, title_ok,
    visa_ok,
)
from sources import fetch_company  # noqa: E402

try:
    import config  # noqa: E402  (vendored toolkit config loader)
except Exception:  # noqa: BLE001 — standalone use without a config layer
    config = None

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[2]  # .agents/skills/job-search -> repo root


def default_profile() -> str:
    """Profile label to use when --profile is omitted (config-driven)."""
    if config is not None:
        try:
            return config.default_profile()
        except Exception:  # noqa: BLE001
            pass
    return "default"


def applications_root() -> Path:
    """Applications root (holds profile/ logs); config-driven with a repo fallback."""
    if config is not None:
        try:
            return config.applications_root()
        except Exception:  # noqa: BLE001
            pass
    return REPO_ROOT / "applications"


def discoveries_dir() -> Path:
    """Directory for the ranked-shortlist output; config-driven with a repo fallback."""
    if config is not None:
        try:
            return config.discoveries_dir()
        except Exception:  # noqa: BLE001
            pass
    return REPO_ROOT / "applications" / "1_discoveries"


def profile_dir() -> Path:
    """Directory holding the skip-logs (applications-log / company-search-log).

    Config-derived and rename-robust: the logs live next to the candidate profile,
    so we prefer the parent of the configured profile markdown (e.g.
    ``applications/0_profile``). We then probe common layout names and pick whichever
    actually holds a log file, so a folder rename (``profile`` -> ``0_profile``)
    doesn't silently disable the already-considered / recently-searched skips.
    """
    candidates: list[Path] = []
    if config is not None:
        try:
            candidates.append(config.profile_md_path().parent)
        except Exception:  # noqa: BLE001
            pass
    root = applications_root()
    candidates += [root / "0_profile", root / "profile"]
    for cand in candidates:
        if (cand / "applications-log.yaml").exists() or \
           (cand / "company-search-log.yaml").exists():
            return cand
    return candidates[0] if candidates else root / "profile"


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def resolve_profile(name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    cand = SKILL_DIR / "profiles" / (name if name.endswith(".yaml") else f"{name}.yaml")
    if not cand.exists():
        sys.exit(f"Profile not found: {name} (looked in {cand})")
    return cand


def resolve_query_terms(profile: dict) -> list[str]:
    terms = (profile.get("sources", {}) or {}).get("query_terms")
    if terms:
        return terms
    include = (profile.get("titles", {}) or {}).get("include", [])
    return [t for t in include if " " in t][:6] or ["software engineer"]


def run_tasks(tasks, workers: int = 12):
    """tasks: list[(label, callable)] -> (postings, errors)."""
    postings, errors, per_source = [], [], Counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn): label for label, fn in tasks}
        for fut in concurrent.futures.as_completed(futs):
            label = futs[fut]
            try:
                res = fut.result()
                postings.extend(res)
                per_source[label.split(":")[0]] += len(res)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {exc}")
    return postings, errors, per_source


def dedupe(postings):
    seen, out = set(), []
    for p in postings:
        key = (p.company.lower().strip(), p.title.lower().strip())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def select_diverse(postings, top_k: int, max_per_company: int | None):
    """Pick the top_k highest-scoring postings with a per-employer cap.

    `postings` must already be sorted best-first. Greedily takes up to
    `max_per_company` rows per company (in score order) so one employer can't
    dominate the shortlist; if that leaves fewer than top_k, the best capped-out
    overflow rows backfill the remaining slots so a thin search still returns
    top_k. `max_per_company` <= 0 (or None) disables the cap.
    """
    if not max_per_company or max_per_company <= 0:
        return postings[:top_k]
    counts: Counter = Counter()
    primary, overflow = [], []
    for p in postings:
        key = (p.company or "").strip().lower()
        if counts[key] < max_per_company:
            primary.append(p)
            counts[key] += 1
            if len(primary) >= top_k:
                return primary
        else:
            overflow.append(p)
    if len(primary) < top_k:            # not enough distinct employers — backfill
        primary.extend(overflow[: top_k - len(primary)])
        primary.sort(key=lambda p: p.score, reverse=True)
    return primary[:top_k]


def _norm_url(url: str) -> str:
    return (url or "").strip().lower().rstrip("/")


def load_considered() -> tuple[set[str], set[tuple[str, str]]]:
    """Postings already generated/considered (<applications_root>/0_profile/applications-log.yaml).

    The profile directory comes from the config layer (``profile_dir()``), so this is
    not tied to any candidate's directory and survives folder renames. Returns
    (urls, (company, role) pairs). New roles at the same company are NOT in the pair
    set, so they still surface.
    """
    path = profile_dir() / "applications-log.yaml"
    urls: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    if path.exists():
        for post in (load_yaml(path).get("postings") or []):
            u = _norm_url(post.get("url", ""))
            if u:
                urls.add(u)
            comp = (post.get("company") or "").strip().lower()
            role = (post.get("role") or "").strip().lower()
            if comp and role:
                pairs.add((comp, role))
    return urls, pairs


def already_considered(p, urls: set[str], pairs: set[tuple[str, str]]) -> bool:
    if p.url and _norm_url(p.url) in urls:
        return True
    return (p.company.strip().lower(), p.title.strip().lower()) in pairs


def load_company_search_log(
    profile: dict | None = None,
    registry: Registry | None = None,
) -> tuple[int, dict[str, date]]:
    """Map every company match key -> last successful search date.

    Each log row's date is registered under all of the registry's match keys for
    the company it resolves to (so a board's canonical name matches a log entry
    written under an aggregator variant, e.g. "Arize" vs "Arize AI"), plus the
    row's own name/aliases so companies absent from the registry still work.
    """
    path = profile_dir() / "company-search-log.yaml"
    skip_days = 7
    if profile:
        prof_skip = (profile.get("company_search_log") or {}).get("skip_within_days")
        if prof_skip is not None:
            skip_days = int(prof_skip)
    token_dates: dict[str, date] = {}
    if not path.exists():
        return skip_days, token_dates
    data = load_yaml(path)
    if data.get("skip_within_days") is not None and not (
        profile and (profile.get("company_search_log") or {}).get("skip_within_days")
        is not None
    ):
        skip_days = int(data["skip_within_days"])
    for c in (data.get("companies") or []):
        if not isinstance(c, dict):
            continue
        raw_date = c.get("last_successful_search")
        if not raw_date:
            continue
        try:
            searched = date.fromisoformat(str(raw_date).strip()[:10])
        except ValueError:
            continue
        name = c.get("name") or ""
        tokens = {name.strip().lower()}
        tokens.update(str(a).strip().lower() for a in (c.get("aliases") or []))
        if registry is not None:
            tokens |= registry.match_keys(name)
        tokens.discard("")
        for tok in tokens:
            prev = token_dates.get(tok)
            if prev is None or searched > prev:
                token_dates[tok] = searched
    return skip_days, token_dates


def is_recently_searched(
    p,
    token_dates: dict[str, date],
    skip_days: int,
    as_of: date,
    registry: Registry | None = None,
) -> bool:
    keys = (registry.match_keys(p.company) if registry is not None
            else {p.company.strip().lower()})
    keys.discard("")
    for key in keys:
        last = token_dates.get(key)
        if last is not None and (as_of - last).days <= skip_days:
            return True
    return False


def _display_loc(location: str, preferred: list[str]) -> str:
    """Show the preferred-metro segment first so multi-city roles are clear."""
    segs = [s.strip() for s in re.split(r"[/;]", location or "") if s.strip()]
    if preferred:
        for s in segs:
            low = s.lower()
            if any(p in low for p in preferred):
                extra = f" (+{len(segs) - 1})" if len(segs) > 1 else ""
                return (s + extra)
    return location or ""


def enrich_posting_metadata(posting, company_levels: dict) -> None:
    """Attach structured handoff metadata used when a result becomes an application."""
    metadata = analyze_job_metadata(
        company=posting.company,
        title=posting.title,
        description=posting.description,
        location=posting.location,
        company_levels=company_levels,
        supplied_salary_range=posting.salary_range,
    )
    for field, value in metadata.items():
        setattr(posting, field, value)


def _format_level(posting) -> str:
    level = posting.job_level or {}
    normalized = str(level.get("normalized") or "?").replace("_", " ")
    low, high = level.get("min"), level.get("max")
    if low is None and high is None:
        equivalent = "?"
    elif low is None:
        equivalent = f"\u2264L{float(high):.1f}"
    elif high is None:
        equivalent = f"L{float(low):.1f}+"
    else:
        equivalent = f"L{float(low):.1f}-L{float(high):.1f}"
    return f"{normalized} ({equivalent})"


def _format_yoe(posting) -> str:
    yoe = posting.required_yoe or {}
    low, high = yoe.get("min"), yoe.get("max")
    if low is None:
        return "?"
    return f"{low:g}-{high:g}y" if high is not None else f"{low:g}+y"


def _format_comp(value: dict | None) -> str:
    """Compact USD/year salary range for the discovery table."""
    if not value:
        return "?"
    low, high = value.get("min"), value.get("max")
    if low is None and high is None:
        return "?"

    def compact(number):
        if number is None:
            return "?"
        return f"{number / 1000:g}k" if number >= 1000 else f"{number:g}"

    return f"{compact(low)}-{compact(high)}"


def render_markdown(kept, profile, meta) -> str:
    preferred = [p.lower() for p in (profile.get("location", {}) or {}).get("preferred", [])]
    age_desc = (f"\u2264 {meta['max_age_days']} days"
                if meta["max_age_days"] is not None else "any (not filtered)")
    cap = meta.get("max_per_company")
    cap_desc = (f"{cap}/company" if cap and cap > 0 else "off")
    lines = [f"# Job matches — {profile.get('name', meta['profile'])}",
             "",
             f"- Profile: `{meta['profile']}`",
             f"- Generated: {meta['generated']}",
             f"- Filters: posting age {age_desc} | "
             f"visa policy: {meta['visa_policy']} | per-employer cap: {cap_desc}",
             f"- Stage {meta.get('stage', 1)}: {meta['n_companies']} company boards + "
             f"aggregators [{', '.join(meta['aggregators']) or 'none'}]",
             f"- Scanned {meta['n_raw']} postings \u2192 {len(kept)} matches "
             f"(skipped {meta.get('n_blacklisted', 0)} blacklisted + "
             f"{meta.get('n_considered', 0)} already-considered + "
             f"{meta.get('n_recently_searched', 0)} recently-searched)",
             ""]
    if meta["errors"]:
        lines += ["> Source errors: " + "; ".join(meta["errors"][:12]), ""]
    lines += [
        "| # | Score | Company | Title | Level (Google eq.) | YOE | Salary | "
        "Loc/Remote | Age | Visa | Source | Why | Link |",
        "|---|------|---------|-------|--------------------|-----|--------|"
        "------------|-----|------|--------|-----|------|",
    ]
    for i, p in enumerate(kept, 1):
        age = "?" if p.age_days is None else f"{p.age_days:.1f}d"
        loc = (_display_loc(p.location, preferred).replace("|", "/")[:30] or p.remote)
        why = "; ".join(p.reasons)[:100].replace("|", "/")
        title = p.title.replace("|", "/")[:46]
        lines.append(
            f"| {i} | {p.score:g} | {p.company} | {title} | {_format_level(p)} | "
            f"{_format_yoe(p)} | {_format_comp(p.salary_range)} | {loc} | "
            f"{age} | {p.visa_label} | {p.source} | {why} | [link]({p.url}) |")
    lines += ["",
              "_Visa labels are heuristic (JD-text scan): `yes` = sponsorship stated, "
              "`no` = explicitly excluded, `unclear` = not mentioned. Always confirm "
              "with the employer before relying on it._"]
    return "\n".join(lines)


def _jobspy_missing_banner(skipped_sites: list[str]) -> str:
    """Prominent multi-line stderr banner: JobSpy enabled but not importable."""
    sites = ", ".join(dict.fromkeys(s for s in skipped_sites if s)) or "all JobSpy sites"
    bar = "!" * 74
    return "\n".join([
        "",
        bar,
        "!! JobSpy is ENABLED for this run but the 'python-jobspy' package is NOT",
        "!! importable, so its scraper tier is being SKIPPED this run.",
        f"!! Skipped JobSpy sources: {sites}",
        "!! (Indeed/Google + any stage-2 LinkedIn/Glassdoor coverage will be missing.)",
        "!!",
        "!! Install it, then re-run the search:",
        "!!     .venv/bin/pip install python-jobspy",
        bar,
        "",
    ])


def assemble_jobspy_tasks(jobspy_on, stage, jobspy_cfg, query_terms, max_age,
                          *, available=None, stream=sys.stderr):
    """Build this run's JobSpy fetch tasks, or skip them loudly.

    Returns ``(tasks, labels, skipped_sites)``. Stage 1 uses the reliable sites
    (Indeed+Google); stage >= 2 also adds the extended sites (LinkedIn/Glassdoor).
    When JobSpy is enabled but ``python-jobspy`` can't be imported, prints a prominent
    multi-line banner to ``stream`` naming the exact install command and every skipped
    site, returns no tasks, and lets the caller continue on the remaining sources.

    No network is touched here — ``build_jobspy_tasks`` only builds deferred callables.
    ``available`` overrides import detection (tests).
    """
    if not jobspy_on:
        return [], [], []
    reliable = jobspy_cfg.get("reliable_sites") or ["indeed", "google"]
    extended = (jobspy_cfg.get("extended_sites") or ["linkedin"]) if stage >= 2 else []
    wanted = list(reliable) + list(extended)
    ok = jobspy_available() if available is None else available
    if not ok:
        print(_jobspy_missing_banner(wanted), file=stream)
        return [], [], wanted
    tasks: list = []
    labels: list = []
    tasks += build_jobspy_tasks(query_terms, jobspy_cfg, reliable, max_age)
    labels.append("jobspy:" + ",".join(reliable))
    if extended:
        tasks += build_jobspy_tasks(query_terms, jobspy_cfg, extended, max_age)
        labels.append("jobspy:" + ",".join(extended))
    return tasks, labels, wanted


def main() -> int:
    ap = argparse.ArgumentParser(description="Match job postings to a profile.")
    ap.add_argument("--profile", default=default_profile(),
                    help="job-matching profile label (in profiles/) or a path to a "
                         "profile YAML; the default comes from "
                         "config.job_search.default_profile "
                         "(currently %(default)s)")
    ap.add_argument("--stage", type=int, choices=[1, 2], default=1,
                    help="1 = reliable tier only (company boards + keyless aggregators "
                         "+ JobSpy Indeed/Google); 2 = also the extended tier "
                         "(JobSpy LinkedIn/Glassdoor + keyed Adzuna/JSearch when keys "
                         "are set). Default: 1.")
    ap.add_argument("--max-age-days", type=float, default=None)
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--max-per-company", type=int, default=None,
                    help="Cap rows per employer in the shortlist so one company "
                         "can't dominate (overrides profile diversity.max_per_company; "
                         "default 3). 0 disables the cap.")
    ap.add_argument("--visa-policy", choices=["exclude_negative", "require_positive"],
                    default=None)
    ap.add_argument("--ai-native-only", action="store_true",
                    help="Hard-filter to AI-native / AI-transitioning employers "
                         "(registry ai-native tag OR an AI-company signal in the JD). "
                         "Default is a soft score boost, keeping breadth.")
    ap.add_argument("--company-tags", default=None,
                    help="Comma-separated tags to select from companies.yaml.")
    ap.add_argument("--aggregators", default=None,
                    help="Comma-separated KEYLESS aggregator names (override profile). "
                         "Options: arbeitnow,jobicy,remoteok,themuse. Keyed aggregators "
                         "(adzuna,jsearch) and JobSpy LinkedIn run in stage 2.")
    ap.add_argument("--jobspy", action="store_true",
                    help="Force-enable the JobSpy scraper even if the profile has it off.")
    ap.add_argument("--no-jobspy", action="store_true",
                    help="Disable JobSpy for this run (quick company-board + keyless "
                         "aggregator sweep).")
    ap.add_argument("--no-companies", action="store_true",
                    help="Skip company ATS boards; use aggregators only.")
    ap.add_argument("--include-considered", action="store_true",
                    help="Do NOT skip postings already in applications-log.yaml "
                         "(re-surface roles you've already generated/considered). "
                         "The company blacklist is always applied.")
    ap.add_argument("--include-recent", "--ignore-search-log", action="store_true",
                    help="Do NOT skip companies with a recent successful search in "
                         "company-search-log.yaml (blacklist still applies).")
    ap.add_argument("--search-log-skip-days", type=int, default=None,
                    help="Override skip_within_days from company-search-log.yaml.")
    ap.add_argument("--sponsor-index", default=str(SKILL_DIR / "data" / "sponsors.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    profile = load_yaml(resolve_profile(args.profile))
    registry = load_registry()
    company_levels = {}
    if config is not None:
        try:
            company_levels = load_company_levels(config.company_levels_path())
        except Exception:  # noqa: BLE001 — optional cache must not break search
            company_levels = {}
    src_cfg = profile.get("sources", {}) or {}

    max_age = args.max_age_days if args.max_age_days is not None \
        else profile.get("max_age_days")
    if args.visa_policy:
        profile.setdefault("visa", {})["policy"] = args.visa_policy
    if args.ai_native_only:
        profile.setdefault("ai_company", {})["require"] = True
    top_k = args.top_k or profile.get("top_k", 40)
    div_cfg = profile.get("diversity", {}) or {}
    max_per_company = (args.max_per_company if args.max_per_company is not None
                       else div_cfg.get("max_per_company", 3))
    stage = args.stage

    # ---- assemble fetch tasks (two stages) ----
    tasks = []
    companies = []
    if not args.no_companies:                     # stage 1: company ATS boards
        tags = (args.company_tags.split(",") if args.company_tags
                else src_cfg.get("company_tags"))
        companies = registry.poll_companies(tags)
        tasks += [(f"board:{c['name']}", (lambda c=c: fetch_company(c))) for c in companies]

    query_terms = resolve_query_terms(profile)
    query_location = src_cfg.get("query_location")
    jobspy_cfg = src_cfg.get("jobspy", {}) or {}
    jobspy_on = bool(args.jobspy or jobspy_cfg.get("enabled")) and not args.no_jobspy

    # Aggregator names from CLI (keyless override) or profile. Keyed names listed
    # anywhere are deferred to stage 2; keyless ones run in stage 1.
    prof_aggs = ([a.lower().strip() for a in args.aggregators.split(",")]
                 if args.aggregators
                 else [a.lower().strip() for a in (src_cfg.get("aggregators") or [])])
    extended_aggs = [a.lower().strip() for a in (src_cfg.get("extended_aggregators") or [])]
    stage1_aggs = [a for a in prof_aggs if a in KEYLESS]
    keyed_wanted = [a for a in (prof_aggs + extended_aggs) if a in KEYED]

    agg_labels: list[str] = list(stage1_aggs)
    # Stage 1 keyless aggregators
    tasks += build_aggregator_tasks(stage1_aggs, query_terms, query_location,
                                    max_age, jobspy_cfg)
    # JobSpy tier (stage-1 reliable + stage-2 extended). Fails loud: if JobSpy is
    # enabled but python-jobspy is unimportable, this prints a banner naming the
    # install command + skipped sites and returns no tasks so the run continues.
    jobspy_tasks, jobspy_labels, _ = assemble_jobspy_tasks(
        jobspy_on, stage, jobspy_cfg, query_terms, max_age)
    tasks += jobspy_tasks
    agg_labels += jobspy_labels

    # Stage 2 keyed aggregators
    if stage >= 2:
        seen_keyed = []
        for a in keyed_wanted:                    # de-dupe, preserve order
            if a not in seen_keyed:
                seen_keyed.append(a)
        avail_keyed = [a for a in seen_keyed if keyed_available(a)]
        missing_keyed = [a for a in seen_keyed if not keyed_available(a)]
        tasks += build_aggregator_tasks(avail_keyed, query_terms, query_location,
                                        max_age, jobspy_cfg)
        agg_labels += avail_keyed
        if missing_keyed:
            print(f"Stage 2: skipped keyed aggregators missing API keys: "
                  f"{', '.join(missing_keyed)} (set env vars to enable).",
                  file=sys.stderr)

    if not tasks:
        sys.exit("No sources selected. Check company_tags / aggregators / --stage.")

    sponsor_index = None
    if os.path.exists(args.sponsor_index):
        with open(args.sponsor_index) as f:
            sponsor_index = json.load(f)

    print(f"Stage {stage}: fetching {len(companies)} company boards + "
          f"{len(agg_labels)} aggregator sources "
          f"[{', '.join(agg_labels) or 'none'}] ({len(tasks)} tasks)...",
          file=sys.stderr)
    postings, errors, per_source = run_tasks(tasks, workers=args.workers)
    n_raw = len(postings)
    print(f"Fetched {n_raw} raw postings "
          f"({dict(per_source)}); {len(errors)} source errors.", file=sys.stderr)

    considered_urls, considered_pairs = (
        (set(), set()) if args.include_considered else load_considered())
    skip_days, search_tokens = load_company_search_log(profile, registry)
    if args.search_log_skip_days is not None:
        skip_days = args.search_log_skip_days
    ignore_search_log = args.include_recent

    # AI-native employer match keys (registry companies tagged ai-lab/ai-infra/
    # ai-native, or a profile-configured tag list). Used for the company-level
    # AI-native boost / hard-filter; the JD-text heuristic (ai_company_hits) is
    # source-agnostic and handled inside scoring.
    ai_cfg = profile.get("ai_company", {}) or {}
    ai_native_tags = ai_cfg.get("company_tags") or ["ai-lab", "ai-infra", "ai-native"]
    ai_native_keys = registry.tagged_keys(ai_native_tags) if ai_cfg else set()

    now = datetime.now(timezone.utc)
    as_of = now.date()
    kept = []
    n_blacklisted = n_considered = n_recently_searched = n_non_ai = 0
    for p in postings:
        p.age_days = days_since(p.posted_at, now)
        if not title_ok(p, profile):
            continue
        if not date_ok(p, max_age):
            continue
        if not location_ok(p, profile):
            continue
        if not visa_ok(p, profile):
            continue
        if not experience_ok(p, profile):
            continue
        is_ai_native = bool(ai_native_keys
                            and registry.match_keys(p.company) & ai_native_keys)
        if not ai_company_ok(p, profile, is_ai_native):
            n_non_ai += 1
            continue
        if registry.is_blacklisted(p.company)[0]:
            n_blacklisted += 1
            continue
        if already_considered(p, considered_urls, considered_pairs):
            n_considered += 1
            continue
        if not ignore_search_log and is_recently_searched(
                p, search_tokens, skip_days, as_of, registry):
            n_recently_searched += 1
            continue
        enrich_posting_metadata(p, company_levels)
        score_posting(p, profile, sponsor_index, is_ai_native_company=is_ai_native)
        kept.append(p)

    if n_blacklisted or n_considered or n_recently_searched or n_non_ai:
        extra = f" + {n_non_ai} non-AI-native" if n_non_ai else ""
        print(f"Skipped {n_blacklisted} blacklisted + {n_considered} "
              f"already-considered + {n_recently_searched} recently-searched"
              f"{extra} postings.",
              file=sys.stderr)

    kept = dedupe(kept)
    kept.sort(key=lambda p: p.score, reverse=True)
    kept = select_diverse(kept, top_k, max_per_company)

    meta = {
        "profile": args.profile,
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "max_age_days": max_age,
        "visa_policy": (profile.get("visa", {}) or {}).get("policy", "exclude_negative"),
        "n_companies": len(companies),
        "aggregators": agg_labels,
        "stage": stage,
        "n_raw": n_raw,
        "n_blacklisted": n_blacklisted,
        "n_considered": n_considered,
        "n_recently_searched": n_recently_searched,
        "max_per_company": max_per_company,
        "errors": errors,
    }
    md = render_markdown(kept, profile, meta)

    out_path = args.out
    if out_path is None:
        disc = discoveries_dir()
        disc.mkdir(parents=True, exist_ok=True)
        out_path = disc / f"{now.strftime('%Y%m%d')}-{args.profile}.md"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(md)
    print(f"Wrote {len(kept)} matches -> {out_path}", file=sys.stderr)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps([p.to_dict() for p in kept], indent=2))
        print(f"Wrote JSON -> {args.json_out}", file=sys.stderr)

    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
