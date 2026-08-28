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
    keyed_available, resolve_reliable_sites,
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


# Profile keys that exist in the schema but that NOTHING reads. A salary floor is
# the worst possible thing to accept silently: the user sets `comp.min_base` to
# the number below which they will not interview, sees a shortlist, and concludes
# every row on it clears that floor. Nothing filtered anything. It is listed here
# rather than implemented because the compensation parser cannot yet carry a gate
# — a posting that merely fails to state pay in a shape `extract_salary_range`
# recognises parses as `None`, and a floor built on that would drop every such
# role for "not enough pay" rather than "pay unknown". Implementing the gate is a
# separate decision (it needs a stated policy for the unparsed case); telling the
# user their setting does nothing is not.
UNIMPLEMENTED_PROFILE_KEYS = (("comp", "min_base"), ("comp", "min_total"))

# Every key the pipeline actually READS, by position in the profile. A mapping
# value lists that block's own keys; `None` is a leaf whose VALUE nothing here
# inspects (a scalar or a list).
#
# This exists because a profile carries the run's hard constraints — sponsorship,
# location, posting age, YOE, pay — and a misspelled key was accepted in silence:
# `max_required_years: 7` parses as valid YAML, reaches nothing, filters nothing,
# and the run looks completely normal. The user reads a shortlist believing a cap
# they never applied. Anything absent from this table is reported by
# :func:`unknown_profile_key_warnings`, with the nearest real key named.
#
# Keeping it accurate is part of adding a profile key: a key read by the pipeline
# but missing here produces a false "nothing reads it" warning, which is why the
# test suite asserts the shipped example profile and the template validate clean.
PROFILE_SCHEMA: dict = {
    "name": None,
    "label": None,
    "updated": None,
    "max_age_days": None,
    "max_years_experience": None,
    "years_experience": None,
    "top_k": None,
    "titles": {
        "include": None,
        "primary": None,
        "exclude": None,
        "exclude_neutralize": None,
        "occupation_review_cap": None,
        "word_filter": {"hard_exclude": None, "soft_exclude": None, "include": None},
    },
    "seniority": {"target": None, "fit_weight": None, "yoe_fit_weight": None},
    "keywords": {"strong": None, "good": None, "negative": None},
    "location": {"preferred": None, "allow_remote": None, "us_only": None,
                 "require_match": None},
    "visa": {"needs_sponsorship": None, "h1b_transfer": None, "perm_greencard": None,
             "policy": None},
    "company_search_log": {"skip_within_days": None, "widen_first_search": None,
                           "first_search_max_age_days": None},
    "comp": {"min_base": None, "min_total": None},
    "ai_company": {"require": None, "company_tags": None, "signals": None,
                   "boost_per_hit": None, "max_boost": None, "company_boost": None},
    "diversity": {"max_per_company": None},
    "sources": {
        "company_tags": None, "aggregators": None, "extended_aggregators": None,
        "query_terms": None, "query_location": None,
        "jobspy": {"enabled": None, "reliable_sites": None, "sites": None,
                   "extended_sites": None, "location": None, "locations": None,
                   "distance": None, "is_remote": None, "results_wanted": None,
                   "max_terms": None, "linkedin_fetch_description": None,
                   "country_indeed": None},
    },
}


def _schema_paths(schema: dict, prefix: str = "") -> list[str]:
    """Every dotted key path in ``schema`` (``sources.jobspy.max_terms``, ...)."""
    paths = []
    for key, sub in schema.items():
        path = f"{prefix}{key}"
        paths.append(path)
        if isinstance(sub, dict):
            paths.extend(_schema_paths(sub, f"{path}."))
    return paths


def _nearest_key(unknown: str, siblings, schema: dict = PROFILE_SCHEMA) -> str | None:
    """The real key an unknown one was most likely meant to be, or None.

    Two passes, because neither alone is enough. Shared underscore-separated
    WORDS go first: they answer the typo shape a hand-written profile actually
    produces (``max_required_years`` for ``max_years_experience``, which edit
    distance scores far below any usable cutoff) and they reach across blocks,
    so a key invented at the wrong level (``per_company``) is pointed at its real
    home (``diversity.max_per_company``) rather than at whichever sibling happens
    to share letters. Edit distance then catches a slip INSIDE one word, where
    there are no shared words to find — ``locations`` for ``location``.
    """
    import difflib

    words = {w for w in unknown.split("_") if w}
    best, best_score = None, 0
    for path in _schema_paths(schema):
        leaf = path.rsplit(".", 1)[-1]
        shared = len(words & {w for w in leaf.split("_") if w})
        # Two shared words is the floor: one ("max", "company") matches half the
        # schema and would hand the user a confident, wrong suggestion.
        if shared >= 2 and shared > best_score:
            best, best_score = path, shared
    if best:
        return best
    close = difflib.get_close_matches(unknown, list(siblings), n=1, cutoff=0.6)
    return close[0] if close else None


def unknown_profile_key_warnings(profile: dict, schema: dict = PROFILE_SCHEMA,
                                 prefix: str = "") -> list[str]:
    """One warning per profile key that no part of the pipeline reads.

    WARNS rather than exits, deliberately. The failure this catches is silence,
    not permissiveness: the user needs to be TOLD the key does nothing, and
    they can be told while the run still returns its postings. Exiting would
    also make this table a single point of failure for every profile in
    existence — including the private overlay's, which this tree cannot see —
    so one forgotten entry here would take down searches that are entirely
    correct. A warning that is wrong costs a line of stderr; an exit that is
    wrong costs the run.
    """
    warnings = []
    for key, value in (profile or {}).items():
        path = f"{prefix}{key}"
        if key not in schema:
            suggestion = _nearest_key(str(key), schema.keys())
            hint = f" Did you mean `{suggestion}`?" if suggestion else ""
            warnings.append(
                f"UNKNOWN KEY `{path}` — no filter, score, gate, or report reads "
                f"it, so it changed NOTHING about this run.{hint} Fix the spelling "
                f"or delete the key; a constraint you believe is active but is not "
                f"is worse than no constraint."
            )
            continue
        sub = schema[key]
        if isinstance(sub, dict) and isinstance(value, dict):
            warnings.extend(unknown_profile_key_warnings(value, sub, f"{path}."))
    return warnings


def unimplemented_profile_warnings(profile: dict) -> list[str]:
    """One warning per profile key that is SET but read by nothing.

    Two populations, one list, because from the user's seat they are the same
    surprise — "I set this and it did nothing": keys the schema DECLARES but no
    code implements (``comp.min_base``), and keys the schema does not declare at
    all (a typo, or an invented name).
    """
    warnings = []
    for section, key in UNIMPLEMENTED_PROFILE_KEYS:
        block = profile.get(section)
        if isinstance(block, dict) and block.get(key) is not None:
            warnings.append(
                f"{section}.{key} is set to {block[key]!r} but is not implemented "
                f"— no filter, score, or report reads it, and this run applied no "
                f"pay floor. Remove it, or check pay by hand on each row."
            )
    return warnings + unknown_profile_key_warnings(profile)


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


# A JD body is identity once it is long enough to BE one. Below this many
# characters (after normalization) a "description" is a stub — a one-line teaser,
# an equal-opportunity boilerplate, an empty ATS field — and thousands of unrelated
# postings share it, so grouping on it would fuse real openings.
MIN_BODY_FINGERPRINT_CHARS = 400
_BODY_NOISE_RE = re.compile(r"[^a-z0-9]+")


def body_fingerprint(posting) -> str | None:
    """Content identity for a posting's JD body, or None when it is too thin.

    Normalizes away everything a re-post can change without changing the job:
    case, whitespace, dash typography, punctuation and heading markup. Two
    staffing agencies syndicating one client requisition differ in exactly those
    (issue #281), so after this they hash the same.

    Cached on the posting because ``dedupe`` runs on each lane and again for the
    report's unique-row count.
    """
    import hashlib

    cached = getattr(posting, "_body_fingerprint", False)
    if cached is not False:
        return cached
    text = _BODY_NOISE_RE.sub(" ", (posting.description or "").casefold()).strip()
    fingerprint = (hashlib.sha256(text.encode("utf-8")).hexdigest()
                   if len(text) >= MIN_BODY_FINGERPRINT_CHARS else None)
    posting._body_fingerprint = fingerprint
    return fingerprint


def _group_duplicate_bodies(rows, collapsed_out=None):
    """Collapse rows whose JD bodies are the same text, keeping the best-scoring.

    Returns the survivors. When ``collapsed_out`` is given, each collapsed group
    is appended to it as ``(survivor, [others])`` so the CALLER can attach the
    provenance — nothing is deleted silently, and the report prints both
    employers and both links, which is what an audit needs to see that two
    "different" openings are one requisition.

    The annotation is deliberately not done here: ``dedupe`` also runs over the
    RAW posting list to count unique rows, and marking postings from that pass
    would credit a shortlist row with siblings that a gate had already dropped.
    """
    groups: dict[str, list] = {}
    order: list = []
    for p in rows:
        fingerprint = body_fingerprint(p)
        if fingerprint is None:
            order.append(p)
            continue
        if fingerprint not in groups:
            groups[fingerprint] = [p]
            order.append(p)
        else:
            groups[fingerprint].append(p)
    if not any(len(g) > 1 for g in groups.values()):
        return rows
    out = []
    for p in order:
        fingerprint = getattr(p, "_body_fingerprint", None)
        group = groups.get(fingerprint) if fingerprint else None
        if not group or len(group) == 1:
            out.append(p)
            continue
        best = max(group, key=lambda row: row.score)
        if collapsed_out is not None:
            collapsed_out.append((best, [row for row in group if row is not best]))
        out.append(best)
    return out


def annotate_duplicate_bodies(collapsed) -> None:
    """Record on each survivor the postings that shared its JD body.

    ``duplicate_sources`` keeps the collapsed rows' employer, title and URL as
    provenance; the ``reasons`` note makes the collapse visible in the shortlist
    row itself rather than only in a footnote nobody scrolls to.
    """
    for best, others in collapsed:
        if not others:
            continue
        best.duplicate_sources = [
            {"company": row.company, "title": row.title, "url": row.url,
             "location": row.location, "source": row.source} for row in others]
        note = (f"same JD body as {len(others)} other posting(s) "
                "— collapsed; see Duplicate JD bodies")
        if note not in best.reasons:
            best.reasons = [*best.reasons, note]


def dedupe(postings, *, group_bodies: bool = True, collapsed_out=None):
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

    That key cannot see the OTHER duplicate shape (issue #281): one client
    requisition syndicated by two staffing firms, or one JD posted under two
    titles, differs in company/title/URL and is identical in the only field that
    describes the JOB — the body. A second pass groups rows whose normalized JD
    body is the same text (:func:`body_fingerprint`), which is why two Snowflake
    "Data Engineer" copies stopped taking two of eight shortlist slots. Pass
    ``group_bodies=False`` for a key-only dedupe; ``collapsed_out`` receives
    ``(survivor, [others])`` per collapsed group so the caller can keep the
    provenance.
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
    rows = [best[key] for key in order]
    if not group_bodies:
        return rows
    return _group_duplicate_bodies(rows, collapsed_out)


def select_diverse(
    postings,
    top_k: int | None,
    max_per_company: int | None,
    *,
    capped_out=None,
):
    """Pick the top_k highest-scoring postings, capped at max_per_company each.

    `postings` must already be sorted best-first. The cap is a CAP: no employer
    ever occupies more than `max_per_company` rows of the returned shortlist.
    `max_per_company` <= 0 (or None) disables it, and `top_k` None returns
    everything. `capped_out`, when given, receives the rows the cap removed from
    the shortlist the run would otherwise have returned, so the report can say
    how many and from whom.

    It used to BACKFILL: rows the cap had excluded were added back whenever the
    distinct-employer pool could not fill top_k. A report headed
    `per-employer cap: 3/company` then listed seven rows from one employer and
    four from another (issue #278), and because backfill runs in score order from
    the bottom of the pool it also promoted negative-score known mis-fits purely
    to reach the requested row count. A shortlist that is honestly short is worth
    more than a full one that contradicts its own header; raise
    `--max-per-company`, or set it to 0, to get the rows back deliberately.
    """
    if top_k is None:
        return postings
    if not max_per_company or max_per_company <= 0:
        return postings[:top_k]
    counts: Counter = Counter()
    primary = []
    for p in postings:
        key = (p.company or "").strip().lower()
        if counts[key] < max_per_company:
            primary.append(p)
            counts[key] += 1
            if len(primary) >= top_k:
                break
    if capped_out is not None:
        # What the CAP cost, measured against the same shortlist size: the rows
        # that would have made an uncapped top-K and did not survive the cap.
        chosen = {id(p) for p in primary}
        capped_out.extend(p for p in postings[:top_k] if id(p) not in chosen)
    return primary


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


# The unit suffix printed after a non-annual band. An annual band gets no
# suffix: the column has always meant USD/year, so adding "/yr" to every row
# would cost width without telling the reader anything new.
_COMP_PERIOD_SUFFIX = {"hour": "/hr", "day": "/day", "week": "/wk", "month": "/mo"}


def _format_comp(value: dict | None) -> str:
    """Compact salary range for the discovery table, WITH its unit.

    An aggregator's structured pay field may be hourly, and this column used to
    print such a band as a bare ``30-35`` — the exact rendering a $30k-$35k
    annual band gets. Two different pay scales printed the same string, so the
    reader had no way to tell a contract hourly rate from a (very low) annual
    salary. A band that states a period other than ``year`` now carries it, and
    a currency other than USD is named rather than implied.
    """
    if not value:
        return "?"
    low, high = value.get("min"), value.get("max")
    if low is None and high is None:
        return "?"
    period = str(value.get("period") or "").strip().lower()
    suffix = _COMP_PERIOD_SUFFIX.get(period, "")
    currency = str(value.get("currency") or "").strip().upper()
    if currency and currency != "USD":
        suffix += f" {currency}"

    # Thousands-compaction reads as an annual figure; a sub-annual rate is small
    # and exact, so print it as stated.
    sub_annual = period in _COMP_PERIOD_SUFFIX

    def compact(number):
        if number is None:
            return "?"
        if sub_annual:
            return f"{number:g}"
        return f"{number / 1000:g}k" if number >= 1000 else f"{number:g}"

    return f"{compact(low)}-{compact(high)}{suffix}"


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
    elif meta.get("first_search_widening_suppressed"):
        # The other direction of the same rule. The profile widens the window on
        # a company's first-ever search; an age bound typed for THIS run does not
        # get quietly widened past. Naming the cost is the point — silence in
        # either direction is what made a 30-day request return 557-day rows.
        held = meta.get("n_first_search_widening_suppressed", 0)
        age_desc += (" (explicit bound: the profile's first-search widening is NOT "
                     f"applied; it would have reached up to {held} older "
                     "posting(s) at never-searched employers)")
    cap = meta.get("max_per_company")
    cap_desc = (f"{cap}/company" if cap and cap > 0 else "off")
    n_capped = meta.get("n_employer_capped", 0) or 0
    if cap and cap > 0 and n_capped:
        # The cap is enforced, so the shortlist can be shorter than top_k. Say by
        # how much and for whom, or a short list reads as a thin market.
        who = ", ".join(meta.get("employer_capped_companies") or [])
        cap_desc += (f" — held back {n_capped} row(s)"
                     + (f" ({who})" if who else "")
                     + "; raise --max-per-company or set 0 to include them")
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
    for warning in (meta.get("profile_warnings") or []):
        lines += [f"> **Profile warning:** {warning}", ""]
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
    lines += render_duplicate_body_section(meta)
    lines += render_funnel_section(meta)
    return "\n".join(lines)


def render_duplicate_body_section(meta) -> list[str]:
    """The ``## Duplicate JD bodies`` block: what was collapsed, and its links.

    Collapsing a duplicate is only safe if the evidence survives (issue #281):
    the reader has to be able to see that two differently-named staffing firms
    posted ONE client requisition, and to reach either posting. So the shortlist
    keeps one row and this section keeps every URL.
    """
    groups = [g for g in (meta.get("duplicate_body_groups") or []) if g.get("collapsed")]
    if not groups:
        return []
    total = sum(len(g["collapsed"]) for g in groups)
    lines = ["", f"## Duplicate JD bodies ({total} row(s) collapsed into "
                 f"{len(groups)} posting(s))", "",
             "Postings whose job-description text is the same after normalization — "
             "one requisition syndicated under different employers, titles or URLs. "
             "The shortlist keeps the highest-scoring copy; every other copy's link "
             "is here, not deleted.", ""]
    for group in groups:
        kept_row = group["kept"]
        lines.append(f"- **{kept_row['company']} — {kept_row['title']}** "
                     f"([kept]({kept_row['url']}))")
        for other in group["collapsed"]:
            lines.append(f"  - also posted as {other['company']} — {other['title']}"
                         + (f" ({other['location']})" if other.get("location") else "")
                         + f" ([link]({other['url']}))")
    return lines


def render_funnel_section(meta) -> list[str]:
    """The ``## Funnel`` block: one disposition per scanned posting, summing to input.

    This is the answer to "kept 17 + review 361 + 7,291 hard-rejected = 7,669 out
    of 7,662" (issue #253). Every scanned posting appears in exactly one row of
    this table; anything that describes a row's JOURNEY rather than its END is
    listed underneath as a diagnostic, where it cannot be added into the total.
    """
    funnel = meta.get("funnel")
    if not funnel:
        return []
    rows = [(label, n) for label, n in funnel.get("dispositions", []) if n]
    lines = ["", "## Funnel", "",
             f"Every one of the {funnel['input']} scanned postings has exactly one "
             "disposition below, and they sum to that total.", "",
             "| Disposition | Postings |", "|-------------|----------|"]
    lines += [f"| {label} | {n} |" for label, n in rows]
    lines.append(f"| **Total** | **{funnel['accounted']}** |")
    if not funnel.get("balanced", True):
        lines += ["",
                  f"> **The funnel does not balance**: {funnel['unaccounted']} "
                  "posting(s) reached no counted disposition. This is a bug in the "
                  "pipeline's accounting, not in the search — report it."]
    diagnostics = {k: v for k, v in (funnel.get("diagnostics") or {}).items() if v}
    if diagnostics:
        lines += ["", "Diagnostics — these describe rows that ALSO appear in exactly "
                      "one row above, so they are never added to the total:", ""]
        lines += [f"- `{name}`: {n}" for name, n in sorted(diagnostics.items())]
    return lines


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
    reliable = resolve_reliable_sites(jobspy_cfg, stream=stream)
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
        # Whether an age bound was typed for THIS run, as opposed to inherited
        # from the profile. Not the same question as `max_age`, which `main`
        # resolves to the profile's value when no flag is given: the widening
        # above is a profile behaviour and must not silently outrank a flag
        # (issue #243). None means "no flag" and leaves the widening in place.
        "cli_max_age_days": getattr(args, "max_age_days", None),
        "title_word_filter": title_filter.load_word_lists(profile),
    }


# --------------------------------------------------------------------------- #
# Filter-stage progress
#
# Issue #292: a legitimate 14,508-row public-board cohort spent 159 seconds inside
# the filter loop printing NOTHING between "loaded 14508 normalized postings" and
# the result. A novice cannot tell a slow run from a hung one, and the documented
# reaction — interrupt and retry — throws away a completed fetch.
#
# Only a corpus big enough to be slow says anything, so an ordinary search, the
# test suite, and every scripted caller keep their exact current output.
# --------------------------------------------------------------------------- #
PROGRESS_MIN_ROWS = 2000
PROGRESS_SECONDS = 5.0


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


class _FilterProgress:
    """Periodic `filtering N/M` lines on stderr, with an ETA, for a big corpus."""

    def __init__(self, total: int, *, stream=None, min_rows: int = PROGRESS_MIN_ROWS,
                 interval: float = PROGRESS_SECONDS):
        import time

        self._clock = time.monotonic
        self.total = int(total or 0)
        self.stream = stream if stream is not None else sys.stderr
        self.interval = float(interval)
        self.enabled = self.total >= int(min_rows) and self.interval >= 0
        self.started = self._clock()
        self.last = self.started

    def tick(self, seen: int, n_kept: int, n_review: int) -> None:
        if not self.enabled:
            return
        elapsed = self._clock() - self.started
        if self._clock() - self.last < self.interval:
            return
        self.last = self._clock()
        pct = (seen * 100) // self.total if self.total else 100
        rate = seen / elapsed if elapsed > 0 else 0
        eta = ((self.total - seen) / rate) if rate > 0 else 0
        print(f"Filtering {seen}/{self.total} ({pct}%) — {n_kept} matches, "
              f"{n_review} for review — {_format_duration(elapsed)} elapsed, "
              f"~{_format_duration(eta)} left", file=self.stream, flush=True)

    def done(self, n_kept: int, n_review: int) -> None:
        if not self.enabled:
            return
        print(f"Filtered {self.total} postings in "
              f"{_format_duration(self._clock() - self.started)} — {n_kept} matches, "
              f"{n_review} for review.", file=self.stream, flush=True)


def filter_score_rank(postings, profile, ctx, *, max_age, top_k, max_per_company,
                      sponsor_index, company_levels, registry, now,
                      progress_stream=None, progress_min_rows=PROGRESS_MIN_ROWS,
                      progress_seconds=PROGRESS_SECONDS):
    """Run filter -> score -> dedupe -> rank on already-fetched postings.

    ``now`` anchors all posting-age math and the recently-searched window: on a fresh
    fetch it is wall-clock now; on a refilter it is the snapshot's fetch timestamp, so
    ages never drift with elapsed real time. Returns ``(kept, counts)`` where the
    pipeline is a pure function of its inputs (identical inputs -> identical output),
    which is what makes refilter byte-identical to the fetch run that wrote the cache.

    ``counts["funnel"]`` is the run's RECONCILIATION: one terminal disposition per
    input posting, summing exactly to ``len(postings)``. Progress lines go to
    ``progress_stream`` (default stderr) only for a corpus of at least
    ``progress_min_rows`` rows, so nothing changes for an ordinary search or a test.
    """
    as_of = now.date()
    progress = _FilterProgress(len(postings), stream=progress_stream,
                               min_rows=progress_min_rows, interval=progress_seconds)
    kept, review_postings = [], []
    n_blacklisted = n_considered = n_recently_searched = n_non_ai = n_low_quality = 0
    n_occupation_ambiguous_overflow = 0
    n_title_hard_excluded = n_title_word_filter_review = n_first_search_widened = 0
    # Gates that dropped postings without ever being counted. `kept + review +
    # every counted drop` used to come out BELOW the input (a location or YOE
    # rejection left no number anywhere), and the validator's census counted the
    # same rows a second time, so the two surfaces could not be reconciled at all.
    n_date = n_location = n_visa = n_experience = n_title_no_match_other = 0
    n_first_search_widening_suppressed = 0
    # The ordinary title gate's two HARD drops. Both were entirely uncounted: on
    # the shipped example profile they are together the largest drop in the whole
    # pipeline (thousands of postings per run) and neither appeared in `counts`,
    # the meta, the markdown, or stderr — so a wrong `titles.exclude` term or a
    # lexicon false positive cost the candidate real postings with no number
    # anywhere to notice it by. `title_excluded_terms` breaks the exclude drop
    # down per term, because "your excludes dropped 1155" is only actionable when
    # you know WHICH word did it.
    n_title_excluded = n_title_nontechnical = 0
    title_excluded_terms: Counter[str] = Counter()
    word_filter = ctx.get("title_word_filter") or title_filter.INERT
    # First-search recency widening. Inert unless a narrow window is actually in
    # force: with `max_age` None nothing is filtered by age anyway.
    widen_first_search = bool(ctx.get("widen_first_search", True))
    first_search_max_age = ctx.get("first_search_max_age_days")
    # An age bound typed on the COMMAND LINE for this run beats the profile's
    # standing first-search widening. The owner decision (2026-08-02,
    # memory/decisions/first-search-finds-every-open-role.md) widens the PROFILE's
    # recency gate on a company's first-ever search, and that still holds — the
    # widening is a property of the profile's window, not a licence to ignore an
    # instruction given for this run. Honouring the profile over `--max-age-days
    # 30` returned postings 557 days old under a header that said 30 (issue #243).
    # Read from ctx rather than compared against the profile's own value: the two
    # are equal whenever the flag merely restates the profile, and a guess there
    # would silence widening for callers that never passed a flag at all.
    explicit_age_bound = ctx.get("cli_max_age_days") is not None
    widening_active = (widen_first_search and max_age is not None
                       and first_search_max_age != max_age
                       and not explicit_age_bound)
    widening_suppressed = (widen_first_search and max_age is not None
                           and first_search_max_age != max_age
                           and explicit_age_bound)
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
    for n_seen, p in enumerate(postings, 1):
        progress.tick(n_seen, len(kept), len(review_postings))
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
                # Name the gate before dropping the row. `assess_title` already
                # recorded WHY on the posting; reading its rule ids here is what
                # turns the pipeline's biggest silent loss into a number the run
                # summary can print.
                rule_ids = (p.filter_assessments.get("title") or {}).get(
                    "rule_ids") or []
                terms = [r.split(".", 2)[2] for r in rule_ids
                         if r.startswith("title.excluded.")]
                if terms:
                    n_title_excluded += 1
                    title_excluded_terms.update(terms)
                elif any(r.startswith("title.nontechnical_occupation.")
                         for r in rule_ids):
                    n_title_nontechnical += 1
                else:
                    # A no_match the two named families do not explain (no include
                    # term hit, no rule id). Uncounted, this was the single biggest
                    # hole in the funnel on a broad profile.
                    n_title_no_match_other += 1
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
            # Say how much the explicit bound cost. Widening that is silently ON
            # produced 557-day-old rows under a 30-day header; widening silently
            # OFF would be the same defect pointing the other way.
            if (widening_suppressed and date_ok(p, first_search_max_age)
                    and is_first_search(p, ctx["search_tokens"], registry)):
                n_first_search_widening_suppressed += 1
            n_date += 1
            continue
        if not location_ok(p, profile):
            n_location += 1
            continue
        if not visa_ok(p, profile):
            n_visa += 1
            continue
        if not experience_ok(p, profile):
            n_experience += 1
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

    n_survived = len(kept) + len(review_postings)
    collapsed_bodies: list = []
    kept = dedupe(kept, collapsed_out=collapsed_bodies)
    review_postings = dedupe(review_postings, collapsed_out=collapsed_bodies)
    annotate_duplicate_bodies(collapsed_bodies)
    n_duplicate = n_survived - len(kept) - len(review_postings)
    n_duplicate_body = sum(len(others) for _best, others in collapsed_bodies)
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
    n_ranked = len(kept)
    employer_capped: list = []
    kept = select_diverse(kept, top_k, max_per_company, capped_out=employer_capped)
    # Whatever the cap and top-K did not take. Split so the report can say which
    # of the two removed a row: "the cap held it back" is a configuration the user
    # can change, "it ranked below the cut" is not.
    n_employer_capped = len(employer_capped)
    n_below_top_k = n_ranked - len(kept) - n_employer_capped
    counts = {
        "n_blacklisted": n_blacklisted,
        "n_considered": n_considered,
        "n_recently_searched": n_recently_searched,
        "n_non_ai": n_non_ai,
        "n_low_quality": n_low_quality,
        "n_occupation_ambiguous_overflow": n_occupation_ambiguous_overflow,
        "n_title_hard_excluded": n_title_hard_excluded,
        "n_title_word_filter_review": n_title_word_filter_review,
        "n_title_excluded": n_title_excluded,
        # Sorted highest-first so the summary's top-N slice names the terms that
        # actually cost the candidate postings.
        "title_excluded_terms": dict(
            sorted(title_excluded_terms.items(), key=lambda kv: (-kv[1], kv[0]))),
        "n_title_nontechnical_occupation": n_title_nontechnical,
        "n_title_no_match_other": n_title_no_match_other,
        "n_date": n_date,
        "n_location": n_location,
        "n_visa": n_visa,
        "n_experience": n_experience,
        "n_duplicate": n_duplicate,
        "n_duplicate_body": n_duplicate_body,
        "n_employer_capped": n_employer_capped,
        "n_below_top_k": n_below_top_k,
        "n_first_search_widened": n_first_search_widened,
        "n_first_search_widening_suppressed": n_first_search_widening_suppressed,
        "first_search_max_age_days": first_search_max_age if widening_active else None,
        "widening_active": widening_active,
        "widening_suppressed_by_explicit_bound": widening_suppressed,
        "n_review": len(review_postings),
        "review_postings": review_postings,
        "overflow_postings": overflow_postings,
        "employer_capped_postings": employer_capped,
        "duplicate_body_groups": collapsed_bodies,
    }
    counts["funnel"] = build_funnel(len(postings), counts, len(kept))
    progress.done(len(kept), len(review_postings))
    return kept, counts


# --------------------------------------------------------------------------- #
# Funnel reconciliation
#
# Issue #253: a search summary said `Fetched 7662 -> kept 17 + review 361` while
# the validator's census said `7291 of 7662 postings hard-rejected`. Read as
# disjoint buckets those total 7,669 — seven MORE than the input — and neither
# surface said whether seven rows were double-counted, rescued, or lost. Nobody
# could tell, because most gates were counted nowhere at all.
#
# The rule this table enforces: **every scanned posting has exactly one terminal
# disposition, and they sum to the input.** Anything that is a DIAGNOSTIC — a row
# that was rescued, widened, or flagged on its way through — is reported beside
# the funnel and never inside it, because a row can carry several diagnostics but
# only ever ends in one place.
# --------------------------------------------------------------------------- #
# (disposition label, counts key). Order is the pipeline's own order, so the
# rendered table reads as the journey a posting takes.
FUNNEL_DROPS = (
    ("unfilled-template", "n_low_quality"),
    ("title hard-excluded (titles.word_filter)", "n_title_hard_excluded"),
    ("title excluded (titles.exclude)", "n_title_excluded"),
    ("title non-technical occupation", "n_title_nontechnical_occupation"),
    ("title no match", "n_title_no_match_other"),
    ("older than the age window", "n_date"),
    ("location out of policy", "n_location"),
    ("sponsorship excluded", "n_visa"),
    ("required experience out of range", "n_experience"),
    ("not AI-native", "n_non_ai"),
    ("blacklisted employer", "n_blacklisted"),
    ("already considered", "n_considered"),
    ("employer searched recently", "n_recently_searched"),
)


def build_funnel(n_input: int, counts: dict, n_shortlist: int) -> dict:
    """One terminal disposition per input posting, summing exactly to ``n_input``.

    ``balanced`` is False and ``unaccounted`` non-zero only if a gate is added
    without a row in :data:`FUNNEL_DROPS` — which is the whole point: the funnel
    reports its own drift instead of quietly mis-stating the total.
    """
    dispositions = [(label, int(counts.get(key, 0) or 0))
                    for label, key in FUNNEL_DROPS]
    dispositions += [
        ("duplicate of another row", int(counts.get("n_duplicate", 0) or 0)),
        ("held back by the per-employer cap",
         int(counts.get("n_employer_capped", 0) or 0)),
        ("ranked below the top-K cut", int(counts.get("n_below_top_k", 0) or 0)),
        ("preserved for manual review", int(counts.get("n_review", 0) or 0)),
        ("over the occupation review cap",
         int(counts.get("n_occupation_ambiguous_overflow", 0) or 0)),
        ("in the shortlist", int(n_shortlist)),
    ]
    accounted = sum(n for _label, n in dispositions)
    return {
        "input": int(n_input),
        "dispositions": dispositions,
        "accounted": accounted,
        "unaccounted": int(n_input) - accounted,
        "balanced": accounted == int(n_input),
        # Diagnostics: overlapping views of rows that ALSO have a disposition
        # above. Named separately so they can never be added into the total.
        "diagnostics": {
            "title_word_filter_rescued": int(
                counts.get("n_title_word_filter_review", 0) or 0),
            "first_search_widened": int(counts.get("n_first_search_widened", 0) or 0),
            "first_search_widening_suppressed": int(
                counts.get("n_first_search_widening_suppressed", 0) or 0),
            "duplicate_jd_body_grouped": int(counts.get("n_duplicate_body", 0) or 0),
        },
    }


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
        # The ordinary title gate's own hard drops (`titles.exclude` per term, and
        # the generic non-technical-occupation lexicon). Reported for the same
        # reason `n_low_quality` is: a hard drop nobody counts is a loss nobody
        # can see.
        "n_title_excluded": counts.get("n_title_excluded", 0),
        "title_excluded_terms": counts.get("title_excluded_terms", {}),
        "n_title_nontechnical_occupation": counts.get(
            "n_title_nontechnical_occupation", 0),
        "n_first_search_widened": counts.get("n_first_search_widened", 0),
        "first_search_widening": counts.get("widening_active", False),
        "first_search_max_age_days": counts.get("first_search_max_age_days"),
        # The explicit-bound half of the same rule: an age bound typed on the
        # command line suppresses the profile's widening, and the number it cost
        # is stated rather than left for the reader to wonder about.
        "first_search_widening_suppressed": counts.get(
            "widening_suppressed_by_explicit_bound", False),
        "n_first_search_widening_suppressed": counts.get(
            "n_first_search_widening_suppressed", 0),
        "max_per_company": max_per_company,
        # How many shortlist rows the per-employer cap held back, and from whom.
        # The header claims a cap; without this the reader cannot tell whether the
        # cap bound at all, and a shortlist shorter than top_k looks like a thin
        # market rather than a setting.
        "n_employer_capped": counts.get("n_employer_capped", 0),
        "employer_capped_companies": [
            f"{name} {n}" for name, n in Counter(
                p.company for p in (counts.get("employer_capped_postings") or [])
            ).most_common(5)],
        # Groups of postings whose JD bodies were the same text (issue #281).
        # Carried as data, not a count, because the whole point is that the
        # collapsed rows' employers and URLs stay readable.
        "duplicate_body_groups": [
            {"kept": {"company": best.company, "title": best.title, "url": best.url},
             "collapsed": list(getattr(best, "duplicate_sources", []) or [])}
            for best, others in (counts.get("duplicate_body_groups") or []) if others],
        "n_duplicate_body": counts.get("n_duplicate_body", 0),
        # One terminal disposition per scanned posting; sums to n_raw.
        "funnel": counts.get("funnel"),
        # Profile keys that did nothing this run — unimplemented, or unknown.
        # In the meta as well as on stderr because a scrolled-past warning about a
        # constraint the user believes is active is barely a warning at all.
        "profile_warnings": unimplemented_profile_warnings(profile),
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


def _render_title_gate_drops(meta, *, top_terms: int = 3) -> str | None:
    """One summary line for the title gate's hard drops, or None when there were none.

    Phrased in the second person because the exclude list is the CANDIDATE's, and
    the number is only useful if it reads as "this is what your own configuration
    removed". The per-term breakdown is truncated to the biggest few terms: the
    full map lives in the meta/JSON for anyone who needs the tail.
    """
    n_excluded = meta.get("n_title_excluded", 0)
    n_lexicon = meta.get("n_title_nontechnical_occupation", 0)
    if not n_excluded and not n_lexicon:
        return None
    parts = []
    if n_excluded:
        terms = list((meta.get("title_excluded_terms") or {}).items())[:top_terms]
        breakdown = ", ".join(f"{term} {n}" for term, n in terms)
        parts.append(f"Your excludes dropped {n_excluded} postings"
                     + (f" ({breakdown})" if breakdown else ""))
    if n_lexicon:
        parts.append(f"the non-technical occupation lexicon dropped {n_lexicon}"
                     + (" more" if n_excluded else " postings"))
    return "; ".join(parts)


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
    title_gate_line = _render_title_gate_drops(meta)
    if title_gate_line:
        lines.append(title_gate_line)
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


def read_store_status_for_replay() -> tuple[str | None, dict]:
    """Store status for the ``--refilter`` path: READ the index, never build it.

    The fetch path writes its snapshot BEFORE the store build runs, so the rows a
    snapshot preserves carry no store identity. Replaying one therefore used to emit
    ``store_key: null`` on every row while a fresh run of the byte-identical postings
    emitted real keys — the replay silently lost the identity linkage that meta.yaml,
    the skip-log and every store-keyed consumer join on.

    Reading the already-built index restores it deterministically: one file read, NO
    lock, no write — a replay is not a fetch, so it must never build. Same total guard
    as the fetch path: a disabled, absent, or broken store yields ``(None, {})`` and
    the search is unaffected.
    """
    if config is None:
        return None, {}
    try:
        data_root = config.data_root()
    except Exception:  # noqa: BLE001
        return None, {}
    if data_root is None:
        return None, {}
    try:
        from _vendor.store.paths import domain_layout
        layout = domain_layout(data_root, "jobs")
        if not (layout.index / "postings.jsonl").exists():
            # A configured store that has never been built is not an error: the
            # replay simply has no identity to restore, exactly as before.
            return None, {}
        return _read_store_status(layout)
    except Exception as exc:  # noqa: BLE001 — a store bug must never break a refilter
        print(f"store: identity lookup skipped ({exc}); search unaffected",
              file=sys.stderr)
        return None, {}


def snapshot_row_map(postings) -> dict[int, int]:
    """``{id(posting): row}`` — where each raw posting sits in the run's snapshot.

    The snapshot's ``postings`` array is written from (and, on a refilter, read into)
    exactly this list, so its index is the stable per-row locator that points an
    auditor at one untruncated JD. Keyed by object identity rather than URL because
    two aggregator rows legitimately share one generic URL (RemoteOK), and a locator
    that resolves to two postings is not a locator.
    """
    return {id(p): i for i, p in enumerate(postings or [])}


def full_description_command(snapshot_path, row) -> str:
    """A copy-pasteable command that prints ONE snapshot row's untruncated JD."""
    import shlex
    program = ("import json,sys;print(json.load(open(sys.argv[1]))"
               "['postings'][int(sys.argv[2])]['description'])")
    return f'python3 -c "{program}" {shlex.quote(str(snapshot_path))} {row}'


def _json_rows_with_store_key(kept, url_map, *, snapshot_path=None, run_id=None,
                              snapshot_rows=None) -> list[dict]:
    """--json-out rows = to_dict() + store identity + a locator for the FULL JD.

    All of it is added to the JSON payload ONLY (never to snapshots or the plain
    to_dict); a missing store match is ``store_key: null``, never an error. The
    canonicalizer is the builder's own (drift-free — no second identity matcher).

    ``to_dict`` clips ``description`` to 400 characters to keep the handoff light,
    and a JD's deciding clause — excluded states, clearance/citizenship, "no
    sponsorship", a 10+ YOE line — routinely sits past that cut. A row that shows a
    preview without saying so reads as the whole posting, so every row now states
    that its text is a preview (``description_is_preview``), how long the real one is
    (``description_full_chars``), and exactly where that text lives:
    ``source_snapshot`` + ``source_snapshot_row``, plus ``full_description_command``,
    which prints it. ``run_id`` names the run that emitted the row, so two results
    over one snapshot can be told apart and each joined to its own report.
    """
    try:
        from posting_identity import canonicalize_url
    except Exception:  # noqa: BLE001
        canonicalize_url = None
    snapshot_rows = snapshot_rows or {}
    snapshot_str = str(snapshot_path) if snapshot_path else None
    rows = []
    for p in kept:
        d = p.to_dict()
        key = None
        if url_map and canonicalize_url is not None:
            key = url_map.get(canonicalize_url(p.url or ""))
        d["store_key"] = key
        d["run_id"] = run_id
        full = p.description or ""
        is_preview = len(full) > len(d.get("description") or "")
        d["description_is_preview"] = is_preview
        d["description_full_chars"] = len(full)
        row = snapshot_rows.get(id(p))
        d["source_snapshot"] = snapshot_str
        d["source_snapshot_row"] = row
        # Only a clipped row has anything to retrieve; on a full-text row the
        # command would be noise repeated once per posting.
        d["full_description_command"] = (
            full_description_command(snapshot_str, row)
            if is_preview and snapshot_str and row is not None else None)
        rows.append(d)
    return rows


def write_json_output(path: str | Path, kept, url_map, *, snapshot_path=None,
                      run_id=None, postings=None) -> Path:
    """Write handoff JSON, creating a caller-supplied output directory if needed.

    The payload stays a bare LIST of posting records — ``handoff.py`` consumes it
    that way — so the run's provenance (source snapshot, run id, row locator) rides
    on every row instead of in an envelope that would break that contract.
    ``postings`` is the run's raw pre-filter list, i.e. the snapshot's row order.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = _json_rows_with_store_key(
        kept, url_map, snapshot_path=snapshot_path, run_id=run_id,
        snapshot_rows=snapshot_row_map(postings))
    out.write_text(json.dumps(rows, indent=2))
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
                   snapshot_path: Path | str | None = None,
                   run_id: str | None = None,
                   snapshot_rows: dict | None = None) -> dict:
    """The filter-review JSON body (also written when there is nothing to review).

    This is the surface the skill asks a human to adjudicate, so naming the snapshot
    is not enough on its own: without a per-row locator the reviewer has to invent a
    join (company/title/URL) back into a snapshot of thousands of rows, and generic
    aggregator URLs make that join ambiguous. Each row therefore carries the exact
    snapshot index of its untruncated JD, and ``instruction`` carries the command
    that prints one.
    """
    snapshot_rows = snapshot_rows or {}
    snapshot_str = str(snapshot_path) if snapshot_path else None
    rows = []
    for p in postings:
        row = p.to_dict()
        # `to_dict` clips the description to 400 chars for light JSON. A reviewer
        # judging a filter decision needs to know the text is a preview, and where
        # the untruncated JD lives — the snapshot round-trips it in full.
        full = p.description or ""
        row["description_truncated"] = len(full) > len(row.get("description") or "")
        row["description_full_chars"] = len(full)
        row["source_snapshot_row"] = snapshot_rows.get(id(p))
        rows.append(row)
    retrieve = (
        f"Print one row's untruncated JD with: "
        f"{full_description_command(snapshot_str, '<source_snapshot_row>')}"
        if snapshot_str else
        "No snapshot was recorded for this run, so the full JD cannot be "
        "retrieved from this file."
    )
    return {
        "schema": 3,
        "kind": kind,
        "profile": profile,
        "generated": generated,
        # Which RUN wrote this body. The stable pointer copy is otherwise anonymous:
        # its filename carries no stamp, so "which run produced the artifact I am
        # reading" had no answer inside the file.
        "run_id": run_id,
        "snapshot": snapshot_str,
        "count": len(rows),
        # The rule ids that put each row here, rolled up. Every row also carries its
        # own `review_reasons` (and `filter_assessments`) untouched.
        "families": dict(reason_families(postings)),
        "instruction": (
            "Run validate_filter_variants.py --snapshot <snapshot> and label "
            "new structural variants before changing a hard filter. Descriptions "
            "here are 400-char previews; the snapshot named above holds the full "
            f"JD, and each row's source_snapshot_row indexes it. {retrieve}"
        ),
        "postings": rows,
    }


REVIEW_KIND = "filter-review"
OVERFLOW_KIND = "filter-review-overflow"


def write_review_report(postings, cache_dir: Path, profile: str, *,
                        kind: str = REVIEW_KIND,
                        stamp: str | None = None,
                        generated: str | None = None,
                        snapshot_path: Path | str | None = None,
                        snapshot_rows: dict | None = None) -> tuple[Path, Path]:
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
                       snapshot_path=snapshot_path, run_id=stamp,
                       snapshot_rows=snapshot_rows),
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
    for warning in unimplemented_profile_warnings(profile):
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
    #
    # The random tail is what makes it an IDENTITY rather than a timestamp: a
    # refilter of a small snapshot finishes in well under a second, so two runs
    # collide on a second-resolution stamp. `unique_run_path` de-collides the
    # FILENAME, but the id recorded inside the artifacts (and now on every --json-out
    # row) would still report one identity for two different answers — the exact
    # confusion the id exists to prevent. Timestamp first, so run artifacts still
    # sort chronologically; same shape the raw store uses for a fetch id.
    run_id = f"{snapshot.run_stamp(datetime.now(timezone.utc))}-{os.urandom(2).hex()}"

    # The store BUILD runs on the FETCH path only (a refilter is snapshot-only and
    # must never build). Store identity is read on both paths — see
    # read_store_status_for_replay: a replay that dropped store_key made the two
    # paths disagree about who a posting is.
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
        # Restore store identity for the replay. The snapshot was written before its
        # run's store build, so these rows have none of their own; without this a
        # no-change refilter emitted store_key: null for postings the store knows,
        # weakening exactly the provenance the user is told to refilter before using.
        store_line, store_url_map = read_store_status_for_replay()
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
            hint = registry.explain_empty_selection(tags, batches)
            sys.exit("No sources selected. Check company_tags / aggregators / --stage."
                     + (f"\n{hint}" if hint else ""))

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
    # Taken BEFORE the pipeline runs: this is the snapshot's own row order, and it is
    # what lets every emitted row name the exact snapshot index of its full JD.
    snapshot_rows = snapshot_row_map(postings)
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
        snapshot_path=snap_path, snapshot_rows=snapshot_rows)
    # The occupation cap bounds the review LANE; the rows it demotes are still real
    # postings, so they get their own durable artifact instead of an integer.
    overflow_run_path, overflow_path = write_review_report(
        overflow_postings, cache_dir, args.profile, kind=OVERFLOW_KIND,
        stamp=run_id, snapshot_path=snap_path, snapshot_rows=snapshot_rows)
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
        json_path = write_json_output(args.json_out, kept, store_url_map,
                                      snapshot_path=snap_path, run_id=run_id,
                                      postings=postings)
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
