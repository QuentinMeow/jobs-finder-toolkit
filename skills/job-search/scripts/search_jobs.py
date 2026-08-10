#!/usr/bin/env python3
"""Search job boards + aggregators for postings matching a job-matching profile.

Usage:
  .venv/bin/python skills/job-search/scripts/search_jobs.py \
      [--profile <label>] [--stage 1|2] [--max-age-days 3] [--top-k 40] \
      [--visa-policy exclude_negative|require_positive] [--ai-native-only] \
      [--company-tags ai-lab,ai-infra] [--company-batches ai-expansion-01] \
      [--aggregators jobicy,themuse] [--no-aggregators] [--all-matches] \
      [--jobspy] [--no-jobspy] [--no-companies] [--out <discoveries_dir>/DATE-label.md]

  # Re-answer a filter/rank question (wider window, different top-k, re-emit JSON)
  # WITHOUT re-fetching, using the snapshot the last fetch wrote:
      [--refilter latest] [--max-age-days 7] [--top-k 60] [--json-out out.json]

Default stdout is a ~5-line run summary + a compact top-K table; the full Markdown
report is always written to the discoveries file. Pass --print-full to dump the full
report to stdout instead. Every fetch writes a pre-filter snapshot to --cache-dir
(default local/search_cache/, gitignored); --refilter [PATH|latest] reuses it, anchoring
posting-age math to the snapshot's fetch time and refusing snapshots older than 6h
unless --allow-stale.

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
from common import days_since, drain_source_warnings  # noqa: E402
from job_metadata import analyze_job_metadata, load_company_levels  # noqa: E402
from registry import Registry, load_registry  # noqa: E402
from scoring import (  # noqa: E402
    ai_company_ok, date_ok, experience_ok, location_ok, posting_quality_ok,
    score_posting, title_ok, visa_ok,
)
import skip_log  # noqa: E402  (vendored: folds the append-only applications skip-log)
from sources import fetch_company  # noqa: E402
import title_filter  # noqa: E402  (sibling: profile-owned title word classes)
import snapshot  # noqa: E402  (sibling: pre-filter fetch cache + --refilter helpers)
import capture_hooks  # noqa: E402  (sibling: raw-store capture shim; lazy/no-op if unconfigured)

try:
    import config  # noqa: E402  (vendored toolkit config loader)
except Exception:  # noqa: BLE001 — standalone use without a config layer
    config = None

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]  # skills/job-search -> repo root

# Skip-log layout names, taken from the config module's CONSTANTS (reading them
# triggers no config load, so they are safe at import time). The literals here are
# reached only when the vendored config layer is entirely unavailable — standalone
# use — and must stay equal to the config module's values.
CANDIDATE_DIRNAME = getattr(config, "CANDIDATE_DIRNAME", "0_profile")
APPLICATIONS_JSONL_NAME = getattr(config, "APPLICATIONS_JSONL_FILENAME",
                                  "applications-log.jsonl")
COMPANY_SEARCH_LOG_NAME = getattr(config, "COMPANY_SEARCH_LOG_FILENAME",
                                  "company-search-log.yaml")


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


def default_cache_dir() -> Path:
    """Where fetch snapshots land when --cache-dir is omitted (gitignored local/)."""
    return REPO_ROOT / "local" / "search_cache"


# CLI flags that change WHAT is fetched (the source set), not how results are
# filtered/scored/ranked. --refilter reuses a cached fetch, so any of these being
# explicitly passed means the cache can't answer the question — a fresh fetch is
# required. Classified from code truth (see the fetch-task assembly in main):
#   --stage         -> gates stage-2 keyed aggregators + JobSpy extended sites
#   --company-tags  -> registry.poll_companies(tags) selects which boards are fetched
#   --company-batches -> selects opt-in registry polling batches
#   --aggregators   -> which keyless aggregators are fetched
#   --no-aggregators -> disables all cross-company sources (including JobSpy)
#   --no-companies  -> drops all company-board fetches
#   --jobspy        -> force-enables the JobSpy scraper fetch tier
#   --no-jobspy     -> disables the JobSpy scraper fetch tier
# NOT here (deliberately): --max-age-days is ALSO passed to fetchers, but it is the
# primary date FILTER and the headline reason to refilter (widen the window), so it
# stays refilter-adjustable; a widen past the fetch horizon is surfaced as a stderr
# note instead of a hard error. --workers only sets fetch concurrency (a no-op under
# refilter). --profile is validated against the snapshot separately (below).
FETCH_AFFECTING_FLAGS = (
    "--stage", "--company-tags", "--company-batches", "--aggregators",
    "--no-aggregators",
    "--no-companies", "--jobspy", "--no-jobspy",
)
# Flag -> argparse dest. The guard tests the parsed VALUE against the parser's own
# default, so an abbreviation (`--company-tag`) or an `=`-joined form is caught by
# construction rather than by string matching what the user typed.
_FETCH_AFFECTING_DESTS = {
    flag: flag.lstrip("-").replace("-", "_") for flag in FETCH_AFFECTING_FLAGS
}


def _applications_jsonl() -> Path:
    """The already-considered skip-log, from the config layer.

    This replaces a ``profile_dir()`` helper that hunted for *a directory
    containing a log file* and, finding none, returned its first guess. That was
    rename-robust and location-fragile in the same breath: the moment the two logs
    stopped living in the same folder as the profile — which the lifetime taxonomy
    does, sending them to ``market/logs/`` while the profile goes to ``me/`` — every
    probe came up empty, the fallback pointed at a directory with no logs in it, and
    **both skips switched off without a word**. A search that skips nothing re-drafts
    postings already applied to.

    Reading the accessor directly cannot fail that way: if the key is wrong the path
    does not exist and the skip is visibly empty, rather than silently correct-looking.
    The append-only JSONL inherits that rule unchanged — ``applications_jsonl_path()``
    is read straight, and the standalone fallback composes the SAME layout from the
    config module's constant. A guess that "finds a log" is still the failure mode to
    avoid: under an append-only log a wrong-but-plausible path is worse than a missing
    one, because nothing regenerates the file to reveal the mistake.
    """
    if config is not None:
        try:
            return config.applications_jsonl_path()
        except Exception:  # noqa: BLE001
            pass
    return applications_root() / CANDIDATE_DIRNAME / APPLICATIONS_JSONL_NAME


def _company_search_log() -> Path:
    """The recently-searched skip-log, from the config layer. See ``_applications_jsonl``."""
    if config is not None:
        try:
            return config.company_search_log_path()
        except Exception:  # noqa: BLE001
            pass
    return applications_root() / CANDIDATE_DIRNAME / COMPANY_SEARCH_LOG_NAME


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _under_public_skills(path: Path) -> bool:
    """True when ``path`` is the public ``skills/`` tree or lives inside it."""
    try:
        skills_root = (REPO_ROOT / "skills").resolve()
    except OSError:
        return False
    return path == skills_root or skills_root in path.parents


def profile_search_dirs() -> list[Path]:
    """Directories a bare ``--profile`` label is resolved against, in order.

    The candidate's OWN profiles live in the private overlay
    (``config.search_profiles_dir()``) and are searched FIRST, so a personal label
    wins over a same-named public file. They used to be symlinked into
    ``skills/job-search/profiles/`` — which put a personal filename at a public
    path — and that link family was deleted; the accessor is now the only route.
    The tracked ``profiles/`` folder (``example.yaml``, ``_TEMPLATE.yaml``) is the
    fallback, so a fresh public clone with no overlay still resolves a label.

    A configured profiles dir that resolves INSIDE the public ``skills/`` tree is
    dropped: with no config at all the accessor's derivation collapses onto the
    loader's own directory, and honouring that would re-create the very thing this
    phase deleted — a personal profile addressable at a public path.
    """
    dirs: list[Path] = []
    if config is not None:
        try:
            configured = config.search_profiles_dir().resolve()
        except Exception:  # noqa: BLE001 — no config layer / unreadable config
            configured = None
        if configured is not None and not _under_public_skills(configured):
            dirs.append(configured)
    dirs.append(SKILL_DIR / "profiles")
    return dirs


def resolve_profile(name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    filename = name if name.endswith(".yaml") else f"{name}.yaml"
    searched = profile_search_dirs()
    for base in searched:
        cand = base / filename
        if cand.exists():
            return cand
    sys.exit(f"Profile not found: {name} (looked in "
             f"{', '.join(str(d) for d in searched)})")


def profile_slug(profile_arg: str) -> str:
    """Filesystem-safe token for the discoveries filename from a --profile value.

    ``--profile`` is usually a bare label ("example") but may be a path to a
    profile file ("/abs/path/to/example.yaml") when the label is not resolvable
    from ``profile_search_dirs()`` (e.g. a profile kept outside the overlay's
    profiles folder). Interpolating the raw value into the
    output filename lets embedded ``/`` characters spawn a junk directory tree
    under the discoveries dir. Use only the stem, sanitized to ``[a-z0-9._-]``.
    """
    stem = Path(profile_arg).stem
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    return slug or "profile"


def apply_visa_policy(profile: dict, policy: str | None) -> None:
    """Apply an explicit ``--visa-policy`` override onto the profile in place.

    ``scoring.visa_ok`` short-circuits to keep-everything unless
    ``visa.needs_sponsorship`` is truthy, so setting only the policy leaves the
    flag a silent no-op when the profile ships ``needs_sponsorship: false`` (or
    omits it). Passing ``--visa-policy`` is an explicit intent to enforce the visa
    gate, so it also implies sponsorship is needed.
    """
    if not policy:
        return
    visa = profile.setdefault("visa", {})
    visa["policy"] = policy
    visa["needs_sponsorship"] = True


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
    """Keep the highest-scoring row per (company, title, LOCATION).

    What this collapses is the same opening reached from two sources — which is
    why the key cannot be the URL: the two sources are exactly the case where the
    URLs differ. But ``(company, title)`` alone cannot tell that apart from two
    genuinely different openings, and big-tech Workday / Amazon boards routinely
    publish one title as many per-location requisitions. Every one but the first
    vanished from the discoveries table, counted nowhere.

    Location is the cheapest field that separates those two cases. The residual
    cost is the reverse direction: two sources that spell the same city
    differently ("Seattle, WA" vs "Seattle, Washington, United States") now leave
    two rows. A visible duplicate is the better failure — the per-employer cap in
    ``select_diverse`` already bounds it, and the alternative silently deletes a
    real requisition.
    """
    best: dict[tuple[str, str, str], object] = {}
    order: list[tuple[str, str, str]] = []
    for p in postings:
        title = p.title.casefold().strip()
        if not title:
            continue
        key = (p.company.casefold().strip(), title,
               (p.location or "").casefold().strip())
        if key not in best:
            best[key] = p
            order.append(key)
        elif p.score > best[key].score:
            best[key] = p
    return [best[key] for key in order]


def select_diverse(
    postings,
    top_k: int | None,
    max_per_company: int | None,
):
    """Pick the top_k highest-scoring postings with a per-employer cap.

    `postings` must already be sorted best-first. Greedily takes up to
    `max_per_company` rows per company (in score order) so one employer can't
    dominate the shortlist; if that leaves fewer than top_k, the best capped-out
    overflow rows backfill the remaining slots so a thin search still returns
    top_k. `max_per_company` <= 0 (or None) disables the cap.
    """
    if top_k is None:
        return postings
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


def _warn_missing_skip_log(path: Path) -> None:
    """Say so on stderr when there are applications but no skip-log to check them against.

    A search whose skip-log is absent skips NOTHING and looks completely normal — the
    same silent fail-open that made ``profile_dir()`` unsafe. It is now also the exact
    state a half-finished migration leaves behind: the append-only log has to be seeded
    once with ``status.py --backfill-log``, and until it is, every posting the owner has
    already applied to comes back as fresh.

    Silent when the applications root holds no application folders, because that is a
    fresh checkout with nothing to skip rather than a missing file.
    """
    try:
        root = applications_root()
        has_apps = any(status_dir.is_dir() and any(status_dir.iterdir())
                       for status_dir in root.iterdir() if status_dir.is_dir())
    except OSError:
        return
    if not has_apps:
        return
    print(f"WARNING: no applications skip-log at {path} — this search will not skip "
          f"ANY posting you have already applied to. Seed it once with "
          f"`status.py --backfill-log`.", file=sys.stderr)


def load_considered(
    registry: Registry | None = None,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Postings already generated/considered (<applications_root>/0_profile/applications-log.jsonl).

    The rows come from ``skip_log.read_postings``, which folds the append-only event
    log down to one row per posting in exactly the ``{company, slug, date, status,
    role, url}`` shape the old YAML ``postings`` list carried — so everything below
    (``_norm_url``, the registry expansion, the two independent key adds) is
    unchanged. ``skip_log``'s own normalizer is deliberately WIDER than ``_norm_url``
    and is never used here: it dedupes lines inside the file, and applying it to the
    stored side while ``already_considered`` normalizes the incoming posting the old
    way would lose skips that fire today.

    The path comes straight from ``config.applications_jsonl_path()``, so it is not
    tied to any candidate's directory and cannot silently resolve to a log-less one. Returns
    (urls, (company match key, role) pairs). Each log row's company is expanded through the
    registry's match keys (name/alias/token + suffix-variant comparable forms), so a
    row stored under a short registry name matches an incoming aggregator posting that
    names the same employer with a trailing legal suffix (and vice-versa) — honoring
    the `reference.md` § Skip logic contract that identity resolves through the
    registry. New roles at the same company are NOT in the pair set, so they surface.
    """
    path = _applications_jsonl()
    urls: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    if not path.exists():
        _warn_missing_skip_log(path)
    else:
        for post in skip_log.read_postings(path):
            u = _norm_url(post.get("url", ""))
            if u:
                urls.add(u)
            comp = (post.get("company") or "").strip().lower()
            role = (post.get("role") or "").strip().lower()
            if comp and role:
                keys = (registry.match_keys(comp) if registry is not None
                        else {comp})
                keys.discard("")
                for key in keys:
                    pairs.add((key, role))
    return urls, pairs


def already_considered(
    p,
    urls: set[str],
    pairs: set[tuple[str, str]],
    registry: Registry | None = None,
) -> bool:
    if p.url and _norm_url(p.url) in urls:
        return True
    role = p.title.strip().lower()
    keys = (registry.match_keys(p.company) if registry is not None
            else {p.company.strip().lower()})
    keys.discard("")
    return any((key, role) in pairs for key in keys)


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
    path = _company_search_log()
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


def is_first_search(
    p,
    token_dates: dict[str, date],
    registry: Registry | None = None,
) -> bool:
    """True when this employer has NEVER completed a successful full-board search.

    Same identity resolution as :func:`is_recently_searched` — a company is "seen"
    under any of its registry match keys — but the question is different: not
    "searched lately?" but "searched EVER?". The company-search log is the only
    thing that knows, which is why the answer is read from there rather than
    guessed from the applications log (a company can be searched and yield nothing).

    ACCEPTED LIMITATION: the log is written on a successful search, and nothing
    regenerates it, so an employer whose row was never written (or whose search
    predates the log) reads as first-search and gets the wide window one more time.
    Erring that way costs one over-wide run; erring the other way costs the roles.
    """
    keys = (registry.match_keys(p.company) if registry is not None
            else {p.company.strip().lower()})
    keys.discard("")
    return not any(key in token_dates for key in keys)


def _display_loc(location: str, preferred: list[str]) -> str:
    """Show the preferred-metro segment first so multi-city roles are clear."""
    segs = [s.strip() for s in re.split(r"[/;•]", location or "") if s.strip()]
    if preferred:
        for s in segs:
            low = s.lower()
            if any(p in low for p in preferred):
                extra = f" (+{len(segs) - 1})" if len(segs) > 1 else ""
                return (s + extra)
    return location or ""


def enrich_posting_metadata(posting, company_levels: dict) -> None:
    """Attach structured handoff metadata used when a result becomes an application."""
    assessed_workplace = (
        posting.filter_assessments.get("location", {}).get("workplace")
    )
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
    if assessed_workplace:
        posting.workplace = assessed_workplace


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


CLIP_MARK = "…"
# Column budgets for the discoveries table. Every one of these used to be a raw
# slice (or, for Company, no limit at all), so a clipped cell read as a complete
# value: "Distributed Systems Engineer (Pl" is a title a human will believe.
CLIP_COMPANY = 24
CLIP_TITLE = 46
CLIP_LOC = 30
CLIP_WHY = 100
# Characters a clip may back up to, so the cut lands between words rather than
# inside one. A cut earlier than half the budget throws away more than it saves,
# so below that the hard cut wins.
_CLIP_BOUNDARIES = " \t;,/"


def _clip(text: str, limit: int) -> str:
    """Clip ``text`` to ``limit`` chars at a word/``;`` boundary, marked with ``…``.

    The mark is part of the budget, so the result is never longer than ``limit``, and
    a reader can always tell a shortened cell from a short one.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return CLIP_MARK[:limit]
    head = text[: limit - 1]
    cut = max((head.rfind(ch) for ch in _CLIP_BOUNDARIES), default=-1)
    if cut >= limit // 2:
        head = head[:cut]
    return head.rstrip(_CLIP_BOUNDARIES) + CLIP_MARK


def _clip_reasons(reasons, limit: int = CLIP_WHY) -> str:
    """Join ``reasons`` within ``limit`` chars, taking WHOLE reasons only.

    A reason is either fully present or fully absent — never a fragment — and the
    count of what did not fit is stated rather than implied. This column carries the
    mismatch marks (``over-leveled (-N)``, ``visa: …``), which are appended last and
    are therefore exactly what a character-level clip amputated mid-word.
    """
    items = [str(r).strip().replace("|", "/") for r in (reasons or [])
             if str(r).strip()]
    if not items:
        return ""

    def fit(reserve: int) -> list[str]:
        kept, used = [], 0
        for item in items:
            cost = len(item) + (2 if kept else 0)      # "; " separator
            if used + cost > limit - reserve:
                break
            kept.append(item)
            used += cost
        return kept

    kept = fit(0)
    if len(kept) == len(items):
        return "; ".join(kept)
    while kept:
        marker = f" +{len(items) - len(kept)} more"
        body = "; ".join(kept)
        if len(body) + len(marker) <= limit:
            return body + marker
        kept = kept[:-1]
    return _clip(items[0], limit)      # not even one whole reason fits


def render_review_section(meta, review_path=None, review_postings=(),
                          *, overflow_path=None, preview: int = 10) -> list[str]:
    """The ``## Manual review`` block: where the preserved rows are, and a sample.

    The persistent report used to say "{n} preserved for filter review" in prose and
    name the artifact nowhere — the path existed only in transient stdout, so a reader
    opening the report later saw a bare count and had no way to reach the rows. Empty
    when the run preserved nothing and capped nothing, so a clean run reads clean.

    Only the TABLE is bounded (``preview``); the artifact holds every row, and the
    rows the occupation cap demoted are named with their own artifact rather than
    reduced to an integer.
    """
    n_review = meta.get("n_review", 0) or 0
    overflow = meta.get("n_occupation_ambiguous_overflow", 0) or 0
    if not n_review and not overflow:
        return []
    rows = list(review_postings)[:preview]
    lines = ["", f"## Manual review ({len(rows)} shown of {n_review})", "",
             "Postings a filter would not decide alone: preserved instead of dropped, "
             "and NOT part of the ranked table above."]
    if review_path:
        lines += ["",
                  f"- Artifact: `{review_path}` — all {n_review} row(s)",
                  f"- Inspect: `.venv/bin/python -m json.tool \"{review_path}\"`"]
    else:
        lines += ["", "- Artifact: not written for this run."]
    lines.append(f"- By review reason: "
                 f"{format_families(meta.get('review_families') or [])}")
    if overflow:
        where = (f" and were written in full to `{overflow_path}`" if overflow_path
                 else " and were NOT persisted")
        lines.append(
            f"- Capped: {overflow} ambiguous-occupation posting(s) exceeded "
            f"`titles.occupation_review_cap`, so they are not in the artifact above"
            f"{where}. Raise the cap to keep them in the main review lane. "
            f"By review reason: "
            f"{format_families(meta.get('overflow_families') or [])}")
    if rows:
        lines += ["",
                  f"Top {len(rows)} by score:",
                  "",
                  "| Score | Company | Title | Review reason | Link |",
                  "|-------|---------|-------|---------------|------|"]
        for p in rows:
            why = _clip_reasons(getattr(p, "review_reasons", []) or [], CLIP_WHY)
            lines.append(
                f"| {p.score:g} | {_clip(p.company.replace('|', '/'), CLIP_COMPANY)} "
                f"| {_clip(p.title.replace('|', '/'), CLIP_TITLE)} | {why} "
                f"| [link]({p.url}) |")
        if n_review > len(rows):
            lines += ["", f"_{n_review - len(rows)} further row(s) are in the "
                          "artifact only._"]
    return lines


def render_markdown(kept, profile, meta, *, review_path=None,
                    review_postings=(), overflow_path=None) -> str:
    preferred = [p.lower() for p in (profile.get("location", {}) or {}).get("preferred", [])]
    age_desc = (f"\u2264 {meta['max_age_days']} days"
                if meta["max_age_days"] is not None else "any (not filtered)")
    if meta.get("first_search_widening"):
        # Say why the run may look different from the last one: on a company's
        # FIRST search there is no prior coverage to protect, so the recency gate
        # is widened for that employer only (owner decision 2026-08-01).
        first = meta.get("first_search_max_age_days")
        age_desc += (" (first search at an employer: "
                     + (f"\u2264 {first} days" if first is not None
                        else "any \u2014 never-searched employers are not age-filtered")
                     + ")")
    cap = meta.get("max_per_company")
    cap_desc = (f"{cap}/company" if cap and cap > 0 else "off")
    # `Scanned` counts RAW fetched rows; `matches` and `review` are counted after
    # dedupe, so the two sides of the arrow are not the same population — say so,
    # or the funnel reads as arithmetic that does not add up.
    unique = meta.get("n_raw_unique")
    scanned = f"Scanned {meta['n_raw']} postings"
    if unique is not None:
        scanned += f" ({unique} unique)"
    # The rescue count comes from the FINAL review list. It used to be counted per
    # RAW posting while `n_review` was counted after dedupe AND the occupation cap,
    # so the nested clause could claim more rescues than there were review rows at
    # all (an audit saw "420 preserved... of which 561 were kept"). The pre-dedupe
    # total is still reported — beside the nested number, never inside it.
    rescued = meta.get("n_title_word_filter_review_kept", 0)
    rescued_raw = meta.get("n_title_word_filter_review", 0)
    rescue_desc = f"{rescued} of them kept by titles.word_filter instead of dropped"
    if rescued_raw != rescued:
        rescue_desc += (f"; titles.word_filter rescued {rescued_raw} raw postings "
                        "before dedupe and the review cap")
    lines = [f"# Job matches — {profile.get('name', meta['profile'])}",
             "",
             f"- Profile: `{meta['profile']}`",
             f"- Generated: {meta['generated']}",
             f"- Filters: posting age {age_desc} | "
             f"visa policy: {meta['visa_policy']} | per-employer cap: {cap_desc}",
             f"- Stage {meta.get('stage', 1)}: {meta['n_companies']} company boards + "
             f"aggregators [{', '.join(meta['aggregators']) or 'none'}]",
             f"- {scanned} \u2192 {len(kept)} matches "
             f"(skipped {meta.get('n_blacklisted', 0)} blacklisted + "
             f"{meta.get('n_considered', 0)} already-considered + "
             f"{meta.get('n_recently_searched', 0)} recently-searched + "
             f"{meta.get('n_low_quality', 0)} unfilled-template + "
             f"{meta.get('n_title_hard_excluded', 0)} title hard-excluded; "
             f"{meta.get('n_review', 0)} preserved for filter review, "
             f"{rescue_desc})",
             ""]
    if meta["errors"]:
        lines += ["> Source errors / not inspected: "
                  + "; ".join(meta["errors"][:12]), ""]
    lines += [
        "| # | Score | Company | Title | Level (Google eq.) | YOE | Salary | "
        "Loc/Remote | Age | Visa | Source | Why | Link |",
        "|---|------|---------|-------|--------------------|-----|--------|"
        "------------|-----|------|--------|-----|------|",
    ]
    for i, p in enumerate(kept, 1):
        age = "?" if p.age_days is None else f"{p.age_days:.1f}d"
        display_loc = _display_loc(p.location, preferred).replace("|", "/")
        if p.workplace == "remote":
            display_loc = f"Remote — {display_loc}" if display_loc else "Remote"
        elif p.workplace == "hybrid":
            display_loc = f"Hybrid — {display_loc}" if display_loc else "Hybrid"
        loc = (_clip(display_loc, CLIP_LOC) or p.remote)
        why = _clip_reasons(p.reasons, CLIP_WHY)
        title = _clip(p.title.replace("|", "/"), CLIP_TITLE)
        company = _clip(p.company.replace("|", "/"), CLIP_COMPANY)
        lines.append(
            f"| {i} | {p.score:g} | {company} | {title} | {_format_level(p)} | "
            f"{_format_yoe(p)} | {_format_comp(p.salary_range)} | {loc} | "
            f"{age} | {p.visa_label} | {p.source} | {why} | [link]({p.url}) |")
    lines += ["",
              "_Visa labels are heuristic (JD-text scan): `yes` = sponsorship stated, "
              "`no` = explicitly excluded, `unclear` = not mentioned. Always confirm "
              "with the employer before relying on it._"]
    lines += render_review_section(meta, review_path, review_postings,
                                   overflow_path=overflow_path)
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


def build_filter_context(profile: dict, registry: Registry, args) -> dict:
    """Assemble the filter/score inputs that don't depend on the fetch itself.

    These are read fresh from the current flags + skip-logs on every run (fetch OR
    refilter), so a refilter reflects the *current* filter intent — the whole point
    of the cache. Returns a dict consumed by :func:`filter_score_rank`.
    """
    considered_urls, considered_pairs = (
        (set(), set()) if args.include_considered else load_considered(registry))
    skip_days, search_tokens = load_company_search_log(profile, registry)
    if args.search_log_skip_days is not None:
        skip_days = args.search_log_skip_days
    ai_cfg = profile.get("ai_company", {}) or {}
    ai_native_tags = ai_cfg.get("company_tags") or ["ai-lab", "ai-infra", "ai-native"]
    ai_native_keys = registry.tagged_keys(ai_native_tags) if ai_cfg else set()
    # First-search recency widening (owner decision 2026-08-01, Option B). A
    # company with no row in the company-search log has never been searched, so
    # there is no "recurring" freshness to protect: the whole board is new
    # information and the profile's narrow window would hide older-but-unseen
    # postings that are still live on the employer's ATS. `null` (the default)
    # means NO posting-age filter at all for that company's first run — "find all
    # available roles, and match older roles by default" — which is also what
    # `company_roles.py --match-only` has always done for a single company.
    log_cfg = profile.get("company_search_log") or {}
    return {
        "considered_urls": considered_urls,
        "considered_pairs": considered_pairs,
        "skip_days": skip_days,
        "search_tokens": search_tokens,
        "ignore_search_log": args.include_recent,
        "ai_native_keys": ai_native_keys,
        "widen_first_search": bool(log_cfg.get("widen_first_search", True)),
        "first_search_max_age_days": log_cfg.get("first_search_max_age_days"),
        "title_word_filter": title_filter.load_word_lists(profile),
    }


def filter_score_rank(postings, profile, ctx, *, max_age, top_k, max_per_company,
                      sponsor_index, company_levels, registry, now):
    """Run filter -> score -> dedupe -> rank on already-fetched postings.

    ``now`` anchors all posting-age math and the recently-searched window: on a fresh
    fetch it is wall-clock now; on a refilter it is the snapshot's fetch timestamp, so
    ages never drift with elapsed real time. Returns ``(kept, counts)`` where the
    pipeline is a pure function of its inputs (identical inputs -> identical output),
    which is what makes refilter byte-identical to the fetch run that wrote the cache.
    """
    as_of = now.date()
    kept, review_postings = [], []
    n_blacklisted = n_considered = n_recently_searched = n_non_ai = n_low_quality = 0
    n_occupation_ambiguous_overflow = 0
    n_title_hard_excluded = n_title_word_filter_review = n_first_search_widened = 0
    word_filter = ctx.get("title_word_filter") or title_filter.INERT
    # First-search recency widening. Inert unless a narrow window is actually in
    # force: with `max_age` None nothing is filtered by age anyway.
    widen_first_search = bool(ctx.get("widen_first_search", True))
    first_search_max_age = ctx.get("first_search_max_age_days")
    widening_active = (widen_first_search and max_age is not None
                       and first_search_max_age != max_age)
    # Decision 3a bounded-rollout guard: the residual `title.occupation_ambiguous`
    # review family (Member of Technical Staff, generalist titles, ...) preserves
    # JD semantics instead of a silent hard drop, but a lexicon miss must never
    # flood the review queue unbounded. The cap is applied only AFTER every other
    # gate, metadata enrichment, dedupe, and score ordering; applying it here would
    # let irrelevant early source rows consume the budget and hide later valid
    # roles. Overflow is counted and surfaced; a profile can tune/disable the cap.
    occupation_review_cap = (profile.get("titles") or {}).get(
        "occupation_review_cap", 300)
    ai_native_keys = ctx["ai_native_keys"]
    for p in postings:
        p.filter_assessments = {}
        p.review_reasons = []
        canonical_company = registry.canonical(p.company)
        if canonical_company:
            p.company = canonical_company
        p.age_days = days_since(p.posted_at, now)
        # Gate 0 (production order matches filter_variants.audit_postings): an
        # unfilled ATS template must never reach title/scoring as a real match.
        if not posting_quality_ok(p):
            n_low_quality += 1
            continue
        # Gate 0b — the candidate's own title word classes (title_filter.py).
        # `hard_exclude` is the ONLY class that drops, and unlike the pre-fetch
        # prefilter this drop is COUNTED, so "always drop" is never "drop without
        # saying so". `soft_exclude` / `include` never drop and never silently
        # keep: they SUPPRESS the ordinary title gate's hard no_match (a title the
        # candidate flagged for judgement must not be thrown away by the
        # include/exclude gate one line later) and they mark the row either way —
        # as a review reason when the gate would have dropped it, and as a
        # `reasons` note further down when it stays on the shortlist.
        title_verdict = word_filter.classify(p.title)
        if title_verdict.action == title_filter.ACTION_DROP:
            n_title_hard_excluded += 1
            continue
        title_flagged = title_verdict.action == title_filter.ACTION_REVIEW
        if not title_ok(p, profile):
            if not title_flagged:
                continue
            # Rescued. `title_word_filter_override` says the ordinary title gate
            # would have dropped this row and which class kept it alive, so the
            # review report carries the whole story rather than a bare row.
            p.review_reasons = list(dict.fromkeys(
                [*p.review_reasons, "title_word_filter_override",
                 *title_verdict.review_reasons]))
            n_title_word_filter_review += 1
        effective_max_age = max_age
        if widening_active and is_first_search(p, ctx["search_tokens"], registry):
            effective_max_age = first_search_max_age
            if not date_ok(p, max_age) and date_ok(p, effective_max_age):
                n_first_search_widened += 1
        if not date_ok(p, effective_max_age):
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
        if already_considered(
                p, ctx["considered_urls"], ctx["considered_pairs"], registry):
            n_considered += 1
            continue
        if not ctx["ignore_search_log"] and is_recently_searched(
                p, ctx["search_tokens"], ctx["skip_days"], as_of, registry):
            n_recently_searched += 1
            continue
        enrich_posting_metadata(p, company_levels)
        score_posting(p, profile, sponsor_index, is_ai_native_company=is_ai_native)
        # A soft/include hit must not be a SILENT keep either: whichever list the
        # posting lands on, its row names the configured word that demands a look.
        # (`score_posting` assigns `reasons`, so this has to come after it.)
        if title_flagged:
            # FIRST, not appended: the discovery table truncates this column at 100
            # characters, and a mark the reader never sees is a silent keep.
            p.reasons = [*title_verdict.reason_notes, *p.reasons]
        if p.review_reasons:
            review_postings.append(p)
        else:
            kept.append(p)

    kept = dedupe(kept)
    review_postings = dedupe(review_postings)
    kept.sort(key=lambda p: p.score, reverse=True)
    review_postings.sort(key=lambda p: p.score, reverse=True)
    # Rows the cap demotes. The cap bounds what is RENDERED and carried in the
    # bounded review list; it must not make the rows themselves disappear. They used
    # to leave nothing behind but an integer, so a measured run demoted 1,659 real
    # postings (57% engineering-role titles) that were recoverable only by knowing to
    # re-run --refilter inside the snapshot's 6h TTL with a cap the user was never
    # shown. Returned here so the caller can persist them; the cap value and the
    # order it applies in are unchanged.
    overflow_postings: list = []
    if occupation_review_cap is not None:
        cap = max(0, int(occupation_review_cap))
        bounded_review = []
        ambiguous_kept = 0
        for posting in review_postings:
            if "title_occupation_ambiguous" in posting.review_reasons:
                if ambiguous_kept >= cap:
                    n_occupation_ambiguous_overflow += 1
                    overflow_postings.append(posting)
                    continue
                ambiguous_kept += 1
            bounded_review.append(posting)
        review_postings = bounded_review
    kept = select_diverse(kept, top_k, max_per_company)
    counts = {
        "n_blacklisted": n_blacklisted,
        "n_considered": n_considered,
        "n_recently_searched": n_recently_searched,
        "n_non_ai": n_non_ai,
        "n_low_quality": n_low_quality,
        "n_occupation_ambiguous_overflow": n_occupation_ambiguous_overflow,
        "n_title_hard_excluded": n_title_hard_excluded,
        "n_title_word_filter_review": n_title_word_filter_review,
        "n_first_search_widened": n_first_search_widened,
        "first_search_max_age_days": first_search_max_age if widening_active else None,
        "widening_active": widening_active,
        "n_review": len(review_postings),
        "review_postings": review_postings,
        "overflow_postings": overflow_postings,
    }
    return kept, counts


def build_meta(profile, args, *, stage, n_companies, aggregators, n_raw, counts,
               max_age, max_per_company, errors, now, n_raw_unique=None) -> dict:
    # Counted on the FINAL review list (post-dedupe, post-cap), which is the only
    # population `n_review` describes. Derived here rather than inside
    # filter_score_rank so the report's arithmetic can never drift from the list it
    # is describing.
    review_postings = counts.get("review_postings") or []
    overflow_postings = counts.get("overflow_postings") or []
    n_word_filter_kept = sum(
        1 for p in review_postings
        if "title_word_filter_override" in (getattr(p, "review_reasons", None) or []))
    return {
        "profile": args.profile,
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "max_age_days": max_age,
        "visa_policy": (profile.get("visa", {}) or {}).get("policy", "exclude_negative"),
        "n_companies": n_companies,
        "aggregators": aggregators,
        "stage": stage,
        "n_raw": n_raw,
        # Distinct (company, title, location) rows among the scanned postings.
        # `n_raw` is pre-dedupe while every downstream count is post-dedupe.
        "n_raw_unique": n_raw_unique,
        "n_blacklisted": counts["n_blacklisted"],
        "n_considered": counts["n_considered"],
        "n_recently_searched": counts["n_recently_searched"],
        # Gate 0 is the FIRST hard drop in the pipeline and was the only one with
        # no visibility anywhere, so a false positive in assess_posting_quality
        # removed a posting leaving no trace in the meta, the markdown, or stderr.
        "n_low_quality": counts.get("n_low_quality", 0),
        "n_review": counts.get("n_review", 0),
        "n_occupation_ambiguous_overflow": counts.get(
            "n_occupation_ambiguous_overflow", 0),
        # Which RULES produced each lane. A single total cannot say that the capped
        # lane and the uncapped one are different populations.
        "review_families": reason_families(review_postings),
        "overflow_families": reason_families(overflow_postings),
        # Title word classes + first-search recency widening. Both are reported
        # because both change what the run could POSSIBLY have returned, and the
        # whole point of each is that its effect is never silent.
        "n_title_hard_excluded": counts.get("n_title_hard_excluded", 0),
        # ..._review counts RAW rescues; ..._review_kept counts the rescues that
        # actually survived into the review list the report points at.
        "n_title_word_filter_review": counts.get("n_title_word_filter_review", 0),
        "n_title_word_filter_review_kept": n_word_filter_kept,
        "n_first_search_widened": counts.get("n_first_search_widened", 0),
        "first_search_widening": counts.get("widening_active", False),
        "first_search_max_age_days": counts.get("first_search_max_age_days"),
        "max_per_company": max_per_company,
        "errors": errors,
    }


# --------------------------------------------------------------------------- #
# Compact stdout contract
# --------------------------------------------------------------------------- #
def _compact_age(posting) -> str:
    return "?" if posting.age_days is None else f"{posting.age_days:.1f}d"


def _compact_level(posting) -> str:
    return str((posting.job_level or {}).get("normalized") or "?").replace("_", " ")


def render_compact_table(kept) -> str:
    """Fixed-width top-K table: rank, company, title, score, level, age, visa, URL."""
    header = (f"{'#':>3}  {'Company':<20.20}  {'Title':<32.32}  {'Score':>6}  "
              f"{'Level':<11.11}  {'Age':>5}  {'Visa':<7.7}  URL")
    rule = "-" * len(header.split("  URL")[0]) + "  ---"
    rows = [header, rule]
    for i, p in enumerate(kept, 1):
        rows.append(
            f"{i:>3}  {p.company:<20.20}  {p.title:<32.32}  {p.score:>6g}  "
            f"{_compact_level(p):<11.11}  {_compact_age(p):>5}  "
            f"{p.visa_label:<7.7}  {p.url}")
    return "\n".join(rows)


def render_run_summary(meta, kept, *, snapshot_display, discoveries_path,
                       json_path, review_path=None, overflow_path=None,
                       store_line=None) -> str:
    """~5-line run summary printed above the compact table on default stdout."""
    aggs = meta["aggregators"]
    lines = [
        f"Stage {meta['stage']}: {meta['n_companies']} company boards + "
        f"{len(aggs)} aggregator sources reached [{', '.join(aggs) or 'none'}]",
        f"Fetched {meta['n_raw']} postings -> kept {len(kept)}"
        f" + review {meta.get('n_review', 0)}",
        f"Snapshot:    {snapshot_display}",
        f"Discoveries: {discoveries_path}",
        f"JSON:        {json_path or '-'}",
    ]
    if review_path:
        lines.append(
            f"Review:      {review_path} — {meta.get('n_review', 0)} row(s) "
            f"[{format_families(meta.get('review_families') or [], limit=3)}]")
    overflow = meta.get("n_occupation_ambiguous_overflow", 0)
    if overflow:
        # A cap that trims rows out of a lane has to say where they went; an integer
        # on stderr is not a place a posting can be read from.
        lines.append(
            f"Overflow:    {overflow_path or '-'} — {overflow} row(s) over "
            f"titles.occupation_review_cap "
            f"[{format_families(meta.get('overflow_families') or [], limit=3)}]")
    if meta.get("n_first_search_widened"):
        first = meta.get("first_search_max_age_days")
        window = f"≤ {first}d" if first is not None else "no age filter"
        lines.append(
            f"First search: {meta['n_first_search_widened']} posting(s) kept by the "
            f"widened window ({window}) at employers never searched before")
    if meta.get("n_title_hard_excluded") or meta.get("n_title_word_filter_review"):
        lines.append(
            f"Title words: {meta.get('n_title_hard_excluded', 0)} hard-excluded, "
            f"{meta.get('n_title_word_filter_review', 0)} sent to review instead of "
            "dropped (titles.word_filter)")
    # Store line (fetch path only; absent when the store is disabled → identical
    # output to pre-store-integration).
    if store_line:
        lines.append(store_line)
    return "\n".join(lines)


def _config_layer_present() -> bool:
    """True when a REAL (non-example) config layer was discovered.

    Distinguishes "no config module" / "only the tracked example config" (both
    normal — CI and a bare public checkout) from "a real config.yaml exists but
    left data_root unset", which is the actual disabled-and-silent case Decision
    1 wants surfaced.
    """
    if config is None:
        return False
    try:
        return config.config_path() != config.EXAMPLE_CONFIG
    except Exception:  # noqa: BLE001
        return False


def run_post_fetch_store_build() -> tuple[str | None, dict]:
    """Post-fetch incremental store build (FETCH path only). Totally guarded.

    Returns ``(summary_line_or_None, {canonical_url: store_key})``. A disabled store,
    a builder-lock contention (fail-fast, never block/retry), or ANY failure yields
    ``(None, {})`` — the store is memory beside the search, and missing memory is
    never an error. Store disabled ⇒ no line ⇒ byte-identical output to pre-store.
    The build can add a few minutes at scale; the ``store: building index...`` notice
    tells the user why the run is still working.

    Decision 1: ``config.data_root()`` keeps NO default (a correct CI/public-tree
    safety invariant — it must never write into a tracked dir), but a real config
    layer that simply never set ``paths.data_root``/``JOBHUNT_DATA_ROOT`` used to
    no-op in total silence. A real config layer being present now gets a loud,
    non-fatal stderr notice on this fetch path; the disabled default itself is
    unchanged (a bare/example checkout still prints nothing).
    """
    if config is None:
        return None, {}
    try:
        data_root = config.data_root()
    except Exception:  # noqa: BLE001
        return None, {}
    if data_root is None:
        if _config_layer_present():
            print(
                "store: not configured (set paths.data_root or JOBHUNT_DATA_ROOT "
                "to capture raw postings) — search results are unaffected",
                file=sys.stderr,
            )
        return None, {}
    try:
        import build_postings
        from _vendor.store.locking import DomainLock, LockContention
        from _vendor.store.paths import domain_layout
        layout = domain_layout(data_root, "jobs")
        layout.state.mkdir(parents=True, exist_ok=True)
        print("store: building index...", file=sys.stderr)
        try:
            with DomainLock(layout.lock_path()):
                build_postings.build_incremental(layout, load_registry())
        except LockContention as exc:
            print(f"store: {exc}", file=sys.stderr)  # fail-fast; ledger catches up next run
        return _read_store_status(layout)
    except Exception as exc:  # noqa: BLE001 — a store bug must never break the search
        print(f"store: incremental build skipped ({exc}); search unaffected",
              file=sys.stderr)
        return None, {}


def _read_store_status(layout) -> tuple[str | None, dict]:
    """Read the fresh index: (summary line, canonical_url→store_key map)."""
    from _vendor.store import serialization
    from _vendor.store.atomic import read_jsonl
    lines = read_jsonl(layout.index / "postings.jsonl")
    rows = lines[1:] if lines else []
    n = len(rows)
    cursor_seq = 0
    cursor_present = False
    if layout.cursors.exists():
        try:
            data = serialization.loads_yaml(layout.cursors.read_text(encoding="utf-8"))
            cur = (data or {}).get("cursors", {}).get("shortlist-review")
            if cur is not None:
                cursor_present = True
                cursor_seq = int((cur or {}).get("seq", 0))
        except Exception:  # noqa: BLE001
            cursor_seq = 0
    m = sum(1 for r in rows if int(r.get("seq", 0)) > cursor_seq)
    # Collision-safe: a canonical_url that maps to MORE THAN ONE distinct key (a
    # board posting and an aggregator shadow entity sharing a URL) resolves to NO
    # key — a wrong store_key would land durably in meta.yaml, so absent beats wrong.
    keys_by_url: dict[str, set] = {}
    for r in rows:
        cu, key = r.get("canonical_url"), r.get("key")
        if cu and key:
            keys_by_url.setdefault(cu, set()).add(key)
    url_map = {cu: next(iter(keys)) for cu, keys in keys_by_url.items()
               if len(keys) == 1}
    # Honest wording: "M new since your last review" only makes sense once a cursor
    # exists; otherwise every entity is trivially "new".
    if cursor_present:
        line = f"store: {n} tracked, {m} new since your last review"
    else:
        line = f"store: {n} tracked, {n} new (no review cursor yet — see reference)"
    return line, url_map


def _json_rows_with_store_key(kept, url_map) -> list[dict]:
    """--json-out rows = to_dict() + a store_key looked up by canonicalized URL.

    Added to the JSON payload ONLY (never to snapshots or the plain to_dict); a
    missing match is ``store_key: null``, never an error. The canonicalizer is the
    builder's own (drift-free — no second identity matcher).
    """
    try:
        from posting_identity import canonicalize_url
    except Exception:  # noqa: BLE001
        canonicalize_url = None
    rows = []
    for p in kept:
        d = p.to_dict()
        key = None
        if url_map and canonicalize_url is not None:
            key = url_map.get(canonicalize_url(p.url or ""))
        d["store_key"] = key
        rows.append(d)
    return rows


def write_json_output(path: str | Path, kept, url_map) -> Path:
    """Write handoff JSON, creating a caller-supplied output directory if needed."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_json_rows_with_store_key(kept, url_map), indent=2))
    return out


def unique_run_path(path: Path) -> Path:
    """``path``, or the first ``-2``/``-3``/... variant that does not exist yet.

    Run identity is second-resolution, so two runs finishing inside one second would
    otherwise write the same "per-run" filename — and the whole point of the stamp is
    that a run artifact is never silently replaced by the next one.
    """
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path


def reason_families(postings) -> list[tuple[str, int]]:
    """``[(review_reason, n_postings), ...]``, most frequent first.

    The review lane is several rules sharing one queue; a single total hides which
    rule is producing the volume (and which one a cap is truncating).
    """
    counter: Counter = Counter()
    for p in postings:
        for reason in dict.fromkeys(getattr(p, "review_reasons", None) or []):
            counter[str(reason)] += 1
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def format_families(families, limit: int = 6) -> str:
    """``a 900; b 714`` — the per-rule split, bounded, with the remainder counted."""
    pairs = list(families)
    if not pairs:
        return "none"
    head = "; ".join(f"{name} {n}" for name, n in pairs[:limit])
    if len(pairs) > limit:
        head += f"; +{len(pairs) - limit} more rules"
    return head


def review_payload(postings, profile: str, *, generated: str,
                   kind: str = "filter-review",
                   snapshot_path: Path | str | None = None) -> dict:
    """The filter-review JSON body (also written when there is nothing to review)."""
    rows = []
    for p in postings:
        row = p.to_dict()
        # `to_dict` clips the description to 400 chars for light JSON. A reviewer
        # judging a filter decision needs to know the text is a preview, and where
        # the untruncated JD lives — the snapshot round-trips it in full.
        row["description_truncated"] = len(p.description or "") > len(
            row.get("description") or "")
        rows.append(row)
    return {
        "schema": 2,
        "kind": kind,
        "profile": profile,
        "generated": generated,
        "snapshot": str(snapshot_path) if snapshot_path else None,
        "count": len(rows),
        # The rule ids that put each row here, rolled up. Every row also carries its
        # own `review_reasons` (and `filter_assessments`) untouched.
        "families": dict(reason_families(postings)),
        "instruction": (
            "Run validate_filter_variants.py --snapshot <snapshot> and label "
            "new structural variants before changing a hard filter. Descriptions "
            "here are 400-char previews; the snapshot named above holds the full JD."
        ),
        "postings": rows,
    }


REVIEW_KIND = "filter-review"
OVERFLOW_KIND = "filter-review-overflow"


def write_review_report(postings, cache_dir: Path, profile: str, *,
                        kind: str = REVIEW_KIND,
                        stamp: str | None = None,
                        generated: str | None = None,
                        snapshot_path: Path | str | None = None) -> tuple[Path, Path]:
    """Write uncertain filter rows to gitignored scratch, per run + a stable pointer.

    Mirrors :func:`snapshot.write_snapshot`: a per-run
    ``<label>-<kind>-<stamp>.json`` plus a ``<label>-<kind>.json`` pointer holding a
    full copy of the same body, so the path every doc and script already names keeps
    resolving to the newest run while no earlier run's evidence is overwritten.
    Returns ``(run_path, pointer_path)``.

    An EMPTY list writes an empty-but-valid report rather than deleting anything.
    This function used to ``unlink`` the pointer when a run had no review rows, which
    silently destroyed the *previous* run's artifact and left "this run flagged
    nothing" indistinguishable from "no run ever wrote one".

    ``kind`` selects the lane: the bounded review list (``filter-review``) or the rows
    the occupation cap demoted out of it (``filter-review-overflow``). The cap bounds
    what is shown; both lanes are persisted in full.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = stamp or snapshot.run_stamp(now)
    label = snapshot.safe_label(profile)
    body = json.dumps(
        review_payload(postings, profile, kind=kind,
                       generated=generated or now.isoformat(),
                       snapshot_path=snapshot_path),
        indent=2)
    run_path = unique_run_path(cache_dir / f"{label}-{kind}-{stamp}.json")
    snapshot.atomic_write(run_path, body)
    pointer_path = cache_dir / f"{label}-{kind}.json"
    snapshot.atomic_write(pointer_path, body)
    return run_path, pointer_path


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
    ap.add_argument("--all-matches", action="store_true",
                    help="Keep every passing posting; disables top-K truncation and "
                         "the per-company diversity cap. Useful for exhaustive "
                         "board batches and source-only bulk handoff.")
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
    ap.add_argument("--company-batches", default=None,
                    help="Comma-separated opt-in poll_batch values. Without this "
                         "flag, batched expansion rows are not polled.")
    ap.add_argument("--aggregators", default=None,
                    help="Comma-separated KEYLESS aggregator names (override profile). "
                         "Options: arbeitnow,jobicy,remoteok,themuse. Keyed aggregators "
                         "(adzuna,jsearch) and JobSpy LinkedIn run in stage 2.")
    ap.add_argument("--no-aggregators", action="store_true",
                    help="Board-only run: disable keyless/keyed aggregators and "
                         "JobSpy, regardless of profile settings.")
    ap.add_argument("--jobspy", action="store_true",
                    help="Force-enable the JobSpy scraper even if the profile has it off.")
    ap.add_argument("--no-jobspy", action="store_true",
                    help="Disable JobSpy for this run (quick company-board + keyless "
                         "aggregator sweep).")
    ap.add_argument("--no-companies", action="store_true",
                    help="Skip company ATS boards; use aggregators only.")
    ap.add_argument("--include-considered", action="store_true",
                    help="Do NOT skip postings already in applications-log.jsonl "
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
    ap.add_argument("--cache-dir", default=None,
                    help="Where fetch snapshots are written / read "
                         "(default: repo local/search_cache/, gitignored).")
    ap.add_argument("--refilter", nargs="?", const="latest", default=None,
                    metavar="PATH|latest",
                    help="Skip ALL fetching: load a pre-filter snapshot and re-run "
                         "filter -> score -> rank with the current filter flags. "
                         "Bare or 'latest' uses the newest snapshot for --profile; "
                         "otherwise a snapshot path. Posting age anchors to the "
                         "snapshot's fetch time, not now.")
    ap.add_argument("--allow-stale", action="store_true",
                    help="Permit --refilter on a snapshot older than the 6h TTL.")
    ap.add_argument("--print-full", action="store_true",
                    help="Print the full Markdown report to stdout (the pre-compact "
                         "behavior) instead of the compact summary + top-K table.")
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
    apply_visa_policy(profile, args.visa_policy)
    if args.ai_native_only:
        profile.setdefault("ai_company", {})["require"] = True
    top_k = (None if args.all_matches else
             (args.top_k if args.top_k is not None else profile.get("top_k", 40)))
    div_cfg = profile.get("diversity", {}) or {}
    max_per_company = (
        0 if args.all_matches else
        (args.max_per_company if args.max_per_company is not None
         else div_cfg.get("max_per_company", 3))
    )
    stage = args.stage

    sponsor_index = None
    if os.path.exists(args.sponsor_index):
        with open(args.sponsor_index) as f:
            sponsor_index = json.load(f)

    cache_dir = Path(args.cache_dir) if args.cache_dir else default_cache_dir()

    # These filter/score inputs are read fresh from the CURRENT flags + skip-logs on
    # both paths, so a refilter reflects the current filter intent.
    ctx = build_filter_context(profile, registry, args)
    word_filter = ctx["title_word_filter"]
    for warning in word_filter.warnings:
        print(f"Profile: {warning}", file=sys.stderr)
    if not word_filter.configured:
        # Not a failure — an unconfigured profile is the documented inert case —
        # but it is the difference between "your list dropped nothing" and "there
        # is no list", and a big-tech fetch is candidate-capped, so say it.
        print("Profile: no titles.word_filter block "
              "(hard_exclude / soft_exclude / include) — the coarse title filter "
              "is inert this run and titles.include/exclude decides alone. See "
              "skills/job-search/profiles/_TEMPLATE.yaml.", file=sys.stderr)

    # Identity of THIS run, taken from the wall clock — not from `now`, which the
    # refilter path anchors to the snapshot's fetch time. Two refilters of one
    # snapshot are two runs with two different answers; naming their artifacts after
    # the snapshot would make the second silently replace the first.
    run_id = snapshot.run_stamp(datetime.now(timezone.utc))

    # Store integration runs on the FETCH path only (refilter is snapshot-only and
    # never builds); defaults keep the refilter output byte-identical to today.
    store_line: str | None = None
    store_url_map: dict = {}

    if args.refilter is not None:
        # ---- REFILTER: no fetching; reuse a cached pre-filter snapshot ----
        snap_path = snapshot.resolve_snapshot_path(cache_dir, args.profile, args.refilter)
        snap = snapshot.load_snapshot(snap_path)
        fetched_at = snapshot.snapshot_fetched_at(snap)
        wall_now = datetime.now(timezone.utc)
        age = snapshot.format_age(wall_now - fetched_at)
        print(f"Refilter: snapshot {snap_path} fetched {snap['fetched_at']} "
              f"(age {age}).", file=sys.stderr)

        if snapshot.is_stale(fetched_at, wall_now) and not args.allow_stale:
            sys.exit(
                f"Refusing snapshot older than {snapshot.TTL_HOURS}h (age {age}). "
                "Freshness is the product — run a fresh search, or pass --allow-stale "
                "to refilter this stale cache anyway.")

        # Compare the PARSED namespace against the parser's own defaults, never
        # sys.argv text: argparse accepts any unambiguous prefix, so `--company-tag`
        # sets args.company_tags while a textual guard sees a flag it does not
        # know. The refilter branch never reads those values, so the run would
        # return the whole snapshot as though the selector had been applied.
        bad = [flag for flag, dest in _FETCH_AFFECTING_DESTS.items()
               if getattr(args, dest, None) != ap.get_default(dest)]
        if bad:
            sys.exit(
                "Fresh fetch required: these flags change what is FETCHED, which a "
                f"cached snapshot cannot answer: {', '.join(bad)}. Drop them to "
                "refilter, or run a fresh search (no --refilter).")
        if args.profile != snap.get("profile"):
            sys.exit(
                f"Fresh fetch required: snapshot was fetched for profile "
                f"'{snap.get('profile')}', not '{args.profile}' (a different profile "
                "fetches a different source set).")

        sel = snap.get("source_selection", {}) or {}
        fetch_max_age = sel.get("max_age_days_at_fetch")
        if (max_age is not None and fetch_max_age is not None
                and max_age > fetch_max_age):
            print(f"Note: widening --max-age-days to {max_age} beyond the snapshot's "
                  f"fetch horizon ({fetch_max_age}d) can only re-surface postings that "
                  "were actually fetched; run a fresh search for a wider crawl.",
                  file=sys.stderr)

        postings = [snapshot.posting_from_dict(d) for d in snap.get("postings", [])]
        n_raw = len(postings)
        now = fetched_at                 # anchor age math to the fetch, never now
        stage = snap.get("stage", stage)
        n_companies = sel.get("n_companies", 0)
        agg_labels = sel.get("aggregators", []) or []
        errors = snap.get("errors", []) or []
        snapshot_display = f"{snap_path} (refilter; age {age})"
        print(f"Refilter: loaded {n_raw} normalized postings from the snapshot.",
              file=sys.stderr)
    else:
        # ---- FETCH: assemble tasks (two stages), fetch, then snapshot ----
        # Tell the capture shim which profile is running (its neutral profile-NN
        # slug is allocated lazily on first capture). This is the ONLY capture hook
        # in this file; a store failure never affects the search below.
        capture_hooks.set_run_context(args.profile)
        tasks = []
        companies = []
        batches = (args.company_batches.split(",") if args.company_batches else None)
        # An explicit batch is already a bounded company selector. Do not
        # accidentally intersect it with a profile's ordinary domain tags unless
        # the caller also explicitly asks for --company-tags.
        tags = (
            args.company_tags.split(",") if args.company_tags
            else (None if batches else src_cfg.get("company_tags"))
        )
        if not args.no_companies:                     # stage 1: company ATS boards
            companies = registry.poll_companies(tags, batches)
            tasks += [(f"board:{c['name']}",
                       (lambda c=c: fetch_company(c, word_filter=word_filter)))
                      for c in companies]

        query_terms = resolve_query_terms(profile)
        query_location = src_cfg.get("query_location")
        jobspy_cfg = src_cfg.get("jobspy", {}) or {}
        jobspy_on = (
            bool(args.jobspy or jobspy_cfg.get("enabled"))
            and not args.no_jobspy
            and not args.no_aggregators
        )

        # Aggregator names from CLI (keyless override) or profile. Keyed names listed
        # anywhere are deferred to stage 2; keyless ones run in stage 1.
        prof_aggs = (
            [] if args.no_aggregators else
            ([a.lower().strip() for a in args.aggregators.split(",")]
             if args.aggregators
             else [a.lower().strip() for a in (src_cfg.get("aggregators") or [])])
        )
        extended_aggs = (
            [] if args.no_aggregators else
            [a.lower().strip() for a in (src_cfg.get("extended_aggregators") or [])]
        )
        stage1_aggs = [a for a in prof_aggs if a in KEYLESS]
        keyed_wanted = [a for a in (prof_aggs + extended_aggs) if a in KEYED]

        agg_labels = list(stage1_aggs)
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

        print(f"Stage {stage}: fetching {len(companies)} company boards + "
              f"{len(agg_labels)} aggregator sources "
              f"[{', '.join(agg_labels) or 'none'}] ({len(tasks)} tasks)...",
              file=sys.stderr)
        postings, errors, per_source = run_tasks(tasks, workers=args.workers)
        # Partial-fetch reports: a source that returned rows but could not inspect
        # everything it set out to inspect (JD detail outage, a truncated listing).
        # These are not exceptions — the rows are real — but a run that silently
        # dropped or blanked part of a board must not read as a complete one, so
        # they join `errors` and land in the snapshot and the `> Source errors:`
        # block alongside the hard failures.
        errors.extend(drain_source_warnings())
        n_raw = len(postings)
        n_companies = len(companies)
        print(f"Fetched {n_raw} raw postings "
              f"({dict(per_source)}); {len(errors)} source errors/warnings.",
              file=sys.stderr)

        now = datetime.now(timezone.utc)
        # Snapshot the normalized, PRE-filter postings so a later --refilter can
        # re-answer filter/rank questions without re-fetching (gitignored local/).
        source_selection = {
            "no_companies": bool(args.no_companies),
            "no_aggregators": bool(args.no_aggregators),
            "jobspy_on": jobspy_on,
            "company_tags": tags,
            "company_batches": batches,
            "aggregators": agg_labels,
            "n_companies": n_companies,
            "query_terms": query_terms,
            "query_location": query_location,
            "max_age_days_at_fetch": max_age,
        }
        snap_path, _ = snapshot.write_snapshot(
            cache_dir, profile=args.profile, stage=stage, fetched_at=now,
            source_selection=source_selection, postings=postings, errors=errors)
        snapshot_display = str(snap_path)
        print(f"Snapshot: wrote {n_raw} normalized postings -> {snap_path}",
              file=sys.stderr)

        # Post-fetch: update the cross-run store (raw was captured during fetch) and
        # get the "N tracked, M new" line + the URL→store_key map. Fully guarded —
        # never blocks or breaks the search; skipped cleanly when the store is off.
        store_line, store_url_map = run_post_fetch_store_build()

    # ---- shared: filter -> score -> rank -> render -> output ----
    kept, counts = filter_score_rank(
        postings, profile, ctx, max_age=max_age, top_k=top_k,
        max_per_company=max_per_company, sponsor_index=sponsor_index,
        company_levels=company_levels, registry=registry, now=now)
    review_postings = counts.get("review_postings", [])
    overflow_postings = counts.get("overflow_postings", [])
    # Always written, even at zero rows: "this run flagged nothing" is a fact worth
    # recording, and the previous run's artifact is never removed to say it.
    review_run_path, review_path = write_review_report(
        review_postings, cache_dir, args.profile, stamp=run_id,
        snapshot_path=snap_path)
    # The occupation cap bounds the review LANE; the rows it demotes are still real
    # postings, so they get their own durable artifact instead of an integer.
    overflow_run_path, overflow_path = write_review_report(
        overflow_postings, cache_dir, args.profile, kind=OVERFLOW_KIND,
        stamp=run_id, snapshot_path=snap_path)
    print(
        f"Preserved {counts['n_review']} uncertain posting(s) for manual "
        f"filter review -> {review_path} (this run: {review_run_path.name})",
        file=sys.stderr,
    )

    if (counts["n_blacklisted"] or counts["n_considered"]
            or counts["n_recently_searched"] or counts["n_non_ai"]
            or counts.get("n_low_quality")):
        extra = f" + {counts['n_non_ai']} non-AI-native" if counts["n_non_ai"] else ""
        if counts.get("n_low_quality"):
            extra += f" + {counts['n_low_quality']} unfilled-template"
        print(f"Skipped {counts['n_blacklisted']} blacklisted + "
              f"{counts['n_considered']} already-considered + "
              f"{counts['n_recently_searched']} recently-searched{extra} postings.",
              file=sys.stderr)
    if counts.get("n_occupation_ambiguous_overflow"):
        cap = (profile.get("titles") or {}).get("occupation_review_cap", 300)
        print(
            f"NOTE: {counts['n_occupation_ambiguous_overflow']} ambiguous-"
            f"occupation posting(s) exceeded the review cap ({cap}) and were "
            "omitted from the bounded review report after gating and scoring; "
            f"every one of them is written in full to {overflow_path} "
            f"(this run: {overflow_run_path.name}). Raise "
            "titles.occupation_review_cap to keep them in the main review lane.",
            file=sys.stderr,
        )

    meta = build_meta(profile, args, stage=stage, n_companies=n_companies,
                      aggregators=agg_labels, n_raw=n_raw, counts=counts,
                      max_age=max_age, max_per_company=max_per_company,
                      errors=errors, now=now,
                      # Company names are canonicalized in-place by the pipeline
                      # above, so this dedupe sees the same identities it does.
                      n_raw_unique=len(dedupe(postings)))
    md = render_markdown(kept, profile, meta, review_path=review_path,
                         review_postings=review_postings,
                         overflow_path=overflow_path)

    out_path = args.out
    run_out_path = None
    if out_path is None:
        # Default naming is fixed per (day, profile) and the refilter path dates the
        # report by the SNAPSHOT's fetch time, so refiltering yesterday's snapshot
        # today used to rewrite yesterday's report in the owner's discoveries tree.
        # Same shape as the snapshot cache: a per-run file plus a stable pointer at
        # the path every doc, skill and habit already names.
        disc = discoveries_dir()
        disc.mkdir(parents=True, exist_ok=True)
        slug = profile_slug(args.profile)
        out_path = disc / f"{now.strftime('%Y%m%d')}-{slug}.md"
        run_out_path = unique_run_path(disc / f"{run_id}-{slug}.md")
        snapshot.atomic_write(run_out_path, md)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    snapshot.atomic_write(Path(out_path), md)
    run_note = f" (this run: {run_out_path.name})" if run_out_path else ""
    print(f"Wrote {len(kept)} matches -> {out_path}{run_note}", file=sys.stderr)

    if args.json_out:
        json_path = write_json_output(args.json_out, kept, store_url_map)
        print(f"Wrote JSON -> {json_path}", file=sys.stderr)

    # Default stdout is the compact contract (5-line summary + top-K table); the full
    # Markdown report always lands in the discoveries file, and --print-full restores
    # the old full-report stdout dump.
    if args.print_full:
        print(md)
    else:
        print(render_run_summary(meta, kept, snapshot_display=snapshot_display,
                                 discoveries_path=out_path, json_path=args.json_out,
                                 review_path=review_path,
                                 overflow_path=overflow_path,
                                 store_line=store_line))
        print()
        print(render_compact_table(kept))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
