"""Cross-company job sources: keyword aggregators + optional scrapers.

Unlike company ATS boards (one board = one company), these span many employers
in a single query. They are split across the two search STAGES (see search_jobs.py):

- **Stage 1 (reliable tier, every run):** keyless aggregators (Jobicy/RemoteOK/
  The Muse) + JobSpy on its *reliable* sites (Indeed + Google) — free, no API keys,
  fast, and rarely rate-limited. This is the market-wide direct-from-board layer.
- **Stage 2 (extended tier, opt-in via --stage 2):** JobSpy on its *extended* sites
  (LinkedIn, Glassdoor — slower / rate-limited) + keyed aggregators (Adzuna, JSearch)
  that only activate when their API keys are present (`keyed_available`).

JobSpy supports per-location radius search (`distance` miles) and a list of
locations (`jobspy.locations`), so a single run can target a chosen metro
(e.g. "City, ST" @ 40mi covers the anchor city plus its surrounding suburbs) AND a
US-remote pass in one config.

All fetchers return list[JobPosting] and feed the SAME filter/score pipeline.
Stdlib + PyYAML only (JobSpy is imported lazily and is optional).
"""
from __future__ import annotations

import json
import os
import urllib.parse

import capture_hooks
from common import (JobPosting, http_get_full, http_get_json, parse_dt,
                    provided_salary_range, strip_html)


def _redact_url(url: str, drop_params: tuple[str, ...]) -> str:
    """Return ``url`` with the named query parameters removed (e.g. API keys).

    Aggregators that carry credentials IN the URL (Adzuna's app_id/app_key) must
    never store those in a manifest, so the captured URL is the redacted one while
    the real request still uses the full URL.
    """
    parts = urllib.parse.urlsplit(url)
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if k not in drop_params]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path,
         urllib.parse.urlencode(kept), parts.fragment))


def _get_scrape(source, url, *, headers=None, key=None, query=None, params=None,
                capture_url=None):
    """GET a cross-company aggregator page, capture its raw bytes as ``scrape``,
    then parse — preserving the old raise-on-HTTP-failure contract.

    Aggregators span many employers, so there is no company context (profile only).
    ``scrape`` is opinion-grade evidence per the design (the source already
    normalized the rows) — useful memory, excluded from any "rebuild fixes
    classification" claim. ``capture_url`` overrides the stored URL when the real
    URL carries a credential that must not be persisted.
    """
    resp = http_get_full(url, headers=headers)
    capture_hooks.capture_scrape(
        source, capture_url or url, resp,
        item_count=capture_hooks.safe_item_count(resp.body, key),
        query=query, params=params)
    if not resp.ok:
        raise RuntimeError(f"GET failed for {url}: {resp.error}")
    return json.loads(resp.body.decode("utf-8", "replace"))

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _remote_of(text: str, flag=None) -> str:
    if flag is True:
        return "remote"
    low = (text or "").lower()
    if "remote" in low:
        return "remote"
    if "hybrid" in low:
        return "hybrid"
    return "unknown"


def _date_bucket(max_age_days: float | None) -> str:
    """Map recency window to JSearch's date_posted enum."""
    if not max_age_days:
        return "all"
    if max_age_days <= 1:
        return "today"
    if max_age_days <= 3:
        return "3days"
    if max_age_days <= 7:
        return "week"
    return "month"


# --------------------------------------------------------------------------- #
# keyless aggregators (span many companies)
# --------------------------------------------------------------------------- #
def fetch_arbeitnow(query_terms, location, max_age_days, pages: int = 3):
    out = []
    for page in range(1, pages + 1):
        url = "https://www.arbeitnow.com/api/job-board-api?" + urllib.parse.urlencode(
            {"page": page})
        data = _get_scrape("arbeitnow", url, headers={"Accept": "application/json"},
                           key="data", query={"terms": query_terms},
                           params={"page": page})
        for j in data.get("data", []):
            out.append(JobPosting(
                source="arbeitnow",
                company=j.get("company_name", "") or "",
                title=(j.get("title") or "").strip(),
                url=j.get("url", ""),
                location=j.get("location", "") or "",
                remote=_remote_of(j.get("location", ""), j.get("remote")),
                posted_at=parse_dt(j.get("created_at")),
                description=strip_html(j.get("description")),
            ))
        if not data.get("data"):
            break
    return out


def fetch_jobicy(query_terms, location, max_age_days):
    url = "https://jobicy.com/api/v2/remote-jobs?" + urllib.parse.urlencode(
        {"count": 100, "geo": "usa"})
    data = _get_scrape("jobicy", url, key="jobs",
                       params={"count": 100, "geo": "usa"})
    out = []
    for j in data.get("jobs", []):
        out.append(JobPosting(
            source="jobicy",
            company=j.get("companyName", "") or "",
            title=(j.get("jobTitle") or "").strip(),
            url=j.get("url", ""),
            location=j.get("jobGeo", "") or "remote",
            remote="remote",
            posted_at=parse_dt(j.get("pubDate")),
            description=strip_html(j.get("jobDescription") or j.get("jobExcerpt")),
        ))
    return out


def fetch_remoteok(query_terms, location, max_age_days):
    data = _get_scrape("remoteok", "https://remoteok.com/api",
                       headers={"User-Agent": "jobs-finder/1.0 (+personal)",
                                "Accept": "application/json"})
    out = []
    for j in data if isinstance(data, list) else []:
        if not j.get("position"):        # first element is a legal notice
            continue
        out.append(JobPosting(
            source="remoteok",
            company=j.get("company", "") or "",
            title=(j.get("position") or "").strip(),
            url=j.get("url") or j.get("apply_url", ""),
            location=j.get("location", "") or "remote",
            remote="remote",
            posted_at=parse_dt(j.get("date") or j.get("epoch")),
            description=strip_html(j.get("description")),
        ))
    return out


def fetch_themuse(query_terms, location, max_age_days, pages: int = 4):
    cats = ["Software Engineering", "Data and Analytics", "IT"]
    out = []
    for page in range(0, pages):
        params = [("page", page), ("descending", "true")] + [("category", c) for c in cats]
        url = "https://www.themuse.com/api/public/jobs?" + urllib.parse.urlencode(params)
        data = _get_scrape("themuse", url, key="results",
                           params={"page": page, "categories": cats})
        results = data.get("results", [])
        for j in results:
            locs = j.get("locations") or []
            loc = ", ".join(l.get("name", "") for l in locs)
            out.append(JobPosting(
                source="themuse",
                company=(j.get("company") or {}).get("name", "") or "",
                title=(j.get("name") or "").strip(),
                url=(j.get("refs") or {}).get("landing_page", ""),
                location=loc,
                remote=_remote_of(loc),
                posted_at=parse_dt(j.get("publication_date")),
                description=strip_html(j.get("contents")),
            ))
        if not results:
            break
    return out


# --------------------------------------------------------------------------- #
# keyed aggregators (opt-in via env vars) — include LinkedIn/Indeed coverage
# --------------------------------------------------------------------------- #
def fetch_adzuna(query_terms, location, max_age_days):
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise RuntimeError("adzuna: set ADZUNA_APP_ID and ADZUNA_APP_KEY env vars "
                           "(free key at developer.adzuna.com).")
    country = os.environ.get("ADZUNA_COUNTRY", "us")
    out = []
    for term in query_terms or ["software engineer"]:
        params = {"app_id": app_id, "app_key": app_key, "what": term,
                  "results_per_page": 50, "sort_by": "date",
                  "content-type": "application/json"}
        if max_age_days:
            params["max_days_old"] = int(max_age_days)
        if location:
            params["where"] = location
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?" + \
            urllib.parse.urlencode(params)
        data = _get_scrape("adzuna", url, key="results", query={"term": term},
                           params={"sort_by": "date",
                                   "max_days_old": params.get("max_days_old"),
                                   "where": location},
                           capture_url=_redact_url(url, ("app_id", "app_key")))
        for j in data.get("results", []):
            out.append(JobPosting(
                source="adzuna",
                company=(j.get("company") or {}).get("display_name", "") or "",
                title=(j.get("title") or "").strip(),
                url=j.get("redirect_url", ""),
                location=(j.get("location") or {}).get("display_name", "") or "",
                remote=_remote_of((j.get("location") or {}).get("display_name", "")),
                posted_at=parse_dt(j.get("created")),
                description=strip_html(j.get("description")),
                salary_range=provided_salary_range(
                    j.get("salary_min"), j.get("salary_max"),
                    source="adzuna_api"),
            ))
    return out


def fetch_jsearch(query_terms, location, max_age_days):
    """RapidAPI JSearch — aggregates LinkedIn, Indeed, Glassdoor, etc."""
    key = os.environ.get("RAPIDAPI_KEY")
    if not key:
        raise RuntimeError("jsearch: set RAPIDAPI_KEY env var (subscribe to JSearch "
                           "on RapidAPI). This is the LinkedIn/Indeed aggregator route.")
    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
               "Accept": "application/json"}
    bucket = _date_bucket(max_age_days)
    out = []
    for term in query_terms or ["software engineer"]:
        query = f"{term} in {location}" if location else term
        url = "https://jsearch.p.rapidapi.com/search?" + urllib.parse.urlencode(
            {"query": query, "page": 1, "num_pages": 1, "date_posted": bucket})
        # The RapidAPI key rides in request HEADERS (not captured), so the URL is
        # safe to store verbatim.
        data = _get_scrape("jsearch", url, headers=headers, key="data",
                           query={"query": query}, params={"date_posted": bucket})
        for j in data.get("data", []):
            city = j.get("job_city") or ""
            state = j.get("job_state") or ""
            out.append(JobPosting(
                source="jsearch",
                company=j.get("employer_name", "") or "",
                title=(j.get("job_title") or "").strip(),
                url=j.get("job_apply_link") or j.get("job_google_link", ""),
                location=", ".join(x for x in [city, state] if x),
                remote=_remote_of("", j.get("job_is_remote")),
                posted_at=parse_dt(j.get("job_posted_at_timestamp")
                                   or j.get("job_posted_at_datetime_utc")),
                description=strip_html(j.get("job_description")),
                salary_range=provided_salary_range(
                    j.get("job_min_salary"), j.get("job_max_salary"),
                    currency=j.get("job_salary_currency"),
                    period=j.get("job_salary_period"),
                    source="jsearch_api"),
            ))
    return out


# --------------------------------------------------------------------------- #
# optional scraper: JobSpy (LinkedIn / Indeed / Glassdoor / Google / ZipRecruiter)
# --------------------------------------------------------------------------- #
def _json_safe(v):
    """Coerce a JobSpy/pandas cell to a JSON-serializable, deterministic value."""
    if v is None or isinstance(v, (str, bool, int)):
        return v
    if isinstance(v, float):
        return None if (v != v or v in (float("inf"), float("-inf"))) else v
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except Exception:  # noqa: BLE001
        pass
    if hasattr(v, "item"):                       # numpy scalar
        try:
            return _json_safe(v.item())
        except Exception:  # noqa: BLE001
            pass
    return str(v)


def _serialize_jobspy_rows(df) -> bytes:
    """Deterministically serialize a JobSpy result frame to canonical JSON bytes.

    JobSpy returns rows it already normalized (no raw HTTP to capture), so the
    ``scrape`` payload is those rows serialized with SORTED keys and a stable order
    — byte-stable for the same rows regardless of column insertion order.
    """
    records = [{str(k): _json_safe(v) for k, v in row.items()}
               for _idx, row in df.iterrows()]
    return json.dumps(records, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def fetch_jobspy(query_terms, max_age_days, jobspy_cfg: dict,
                 sites=None, loc_cfg=None):
    """Scrape one JobSpy `location` on the given `sites`.

    `sites`   — which boards to scrape (e.g. ["indeed","google"] for the reliable
                tier, ["linkedin"] for the extended tier). Falls back to
                jobspy_cfg["sites"] then ["indeed","google"].
    `loc_cfg` — one location dict: {location, distance (miles), is_remote}. Falls
                back to a single location from jobspy_cfg. Callers build one task
                per location via `build_jobspy_tasks`.
    """
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError("jobspy not installed. Run: "
                           ".venv/bin/python -m pip install python-jobspy") from exc
    import math
    sites = sites or jobspy_cfg.get("sites") or ["indeed", "google"]
    results_wanted = int(jobspy_cfg.get("results_wanted", 25))
    loc_cfg = loc_cfg or {"location": jobspy_cfg.get("location") or "United States"}
    loc = loc_cfg.get("location") or "United States"
    distance = loc_cfg.get("distance", jobspy_cfg.get("distance"))
    is_remote = bool(loc_cfg.get("is_remote", jobspy_cfg.get("is_remote", False)))
    hours_old = int(math.ceil(max_age_days * 24)) if max_age_days else None
    # Cap terms — each term x site is a separate (slow, rate-limited) scrape.
    terms = (query_terms or ["software engineer"])[:int(jobspy_cfg.get("max_terms", 3))]
    out = []
    for term in terms:
        kwargs = dict(
            site_name=sites,
            search_term=term,
            google_search_term=f"{term} jobs near {loc}",
            location=loc,
            results_wanted=results_wanted,
            hours_old=hours_old,
            is_remote=is_remote,
            linkedin_fetch_description=bool(jobspy_cfg.get("linkedin_fetch_description", False)),
            country_indeed=jobspy_cfg.get("country_indeed", "usa"),
            description_format="markdown",
            verbose=0,
        )
        if distance:                       # radius search (indeed/linkedin/glassdoor/zip)
            kwargs["distance"] = int(distance)
        df = scrape_jobs(**kwargs)
        # Capture the scrape as deterministic JSON bytes (there is no raw HTTP to
        # capture). tool_version already notes the store lib; the scraper is named
        # in the request params (python-jobspy — opinion-grade evidence).
        try:
            capture_hooks.capture_scrape_bytes(
                "jobspy", f"jobspy://{','.join(sites)}/{loc}?q={term}",
                _serialize_jobspy_rows(df), content_type="application/json",
                item_count=int(len(df)) if df is not None else 0,
                query={"term": term, "location": loc, "is_remote": is_remote},
                params={"scraper": "python-jobspy", "sites": list(sites),
                        "results_wanted": results_wanted, "distance": distance})
        except Exception:  # noqa: BLE001 — capture must never break the scrape
            pass
        for _, row in df.iterrows():
            def g(k):
                v = row.get(k)
                try:
                    import pandas as pd
                    if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)):
                        return None
                except Exception:
                    pass
                return v
            out.append(JobPosting(
                source=f"jobspy:{g('site') or ''}",
                company=str(g("company") or ""),
                title=str(g("title") or "").strip(),
                url=str(g("job_url") or g("job_url_direct") or ""),
                location=str(g("location") or ""),
                remote=("remote" if g("is_remote") is True
                        else _remote_of(str(g("location") or ""))),
                posted_at=parse_dt(str(g("date_posted")) if g("date_posted") else None),
                description=str(g("description") or ""),
                salary_range=provided_salary_range(
                    g("min_amount"), g("max_amount"),
                    currency=g("currency"),
                    period=g("interval"),
                    source="jobspy"),
            ))
    return out


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
KEYLESS = {
    "arbeitnow": fetch_arbeitnow,
    "jobicy": fetch_jobicy,
    "remoteok": fetch_remoteok,
    "themuse": fetch_themuse,
}
KEYED = {
    "adzuna": fetch_adzuna,
    "jsearch": fetch_jsearch,
}
ALL_AGGREGATORS = set(KEYLESS) | set(KEYED) | {"jobspy"}


def keyed_available(name: str) -> bool:
    """True if the keyed aggregator's API credentials are present in the env.

    Lets stage 2 quietly skip keyed sources whose keys aren't set instead of
    raising a noisy source error for every run without a subscription.
    """
    name = (name or "").lower().strip()
    if name == "adzuna":
        return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))
    if name == "jsearch":
        return bool(os.environ.get("RAPIDAPI_KEY"))
    return False


def jobspy_available() -> bool:
    """True if the optional JobSpy scraper package can be imported.

    JobSpy is a heavy optional dependency (pandas/numpy/tls-client). When it is
    missing, every JobSpy fetch task fails and the whole scraper tier drops out of a
    run silently. search_jobs.py calls this to emit a loud banner and skip the JobSpy
    tasks rather than degrade quietly. Mirrors the ImportError guard in ``fetch_jobspy``
    (a missing transitive dep also surfaces as ImportError / ModuleNotFoundError).
    """
    try:
        import jobspy  # noqa: F401
    except ImportError:
        return False
    return True


def build_jobspy_tasks(query_terms, jobspy_cfg, sites, max_age_days):
    """One JobSpy task per configured location, all on the given `sites`.

    Locations come from `jobspy_cfg["locations"]` (a list of
    {location, distance, is_remote} dicts); falls back to a single location so
    a bare `jobspy.location` still works. Returns [] when `sites` is empty.
    """
    if not sites:
        return []
    jobspy_cfg = jobspy_cfg or {}
    locations = jobspy_cfg.get("locations") or [{
        "location": jobspy_cfg.get("location") or "United States",
        "distance": jobspy_cfg.get("distance"),
        "is_remote": jobspy_cfg.get("is_remote", False),
    }]
    site_label = ",".join(sites)
    tasks = []
    for loc_cfg in locations:
        loc_name = (loc_cfg or {}).get("location", "")
        label = f"agg:jobspy[{site_label}@{loc_name}]"
        tasks.append((label,
                      lambda lc=loc_cfg: fetch_jobspy(query_terms, max_age_days,
                                                      jobspy_cfg, sites=sites,
                                                      loc_cfg=lc)))
    return tasks


def build_aggregator_tasks(names, query_terms, location, max_age_days, jobspy_cfg):
    """Return [(label, callable)] for the requested aggregator source names.

    Handles the keyless + keyed keyword aggregators. JobSpy is built separately
    via `build_jobspy_tasks` (site-tiered), but a bare "jobspy" name is still
    accepted here for backward compatibility (uses its default sites/locations).
    """
    tasks = []
    for name in names or []:
        name = name.lower().strip()
        if name in KEYLESS:
            fn = KEYLESS[name]
            tasks.append((f"agg:{name}",
                          lambda fn=fn: fn(query_terms, location, max_age_days)))
        elif name in KEYED:
            fn = KEYED[name]
            tasks.append((f"agg:{name}",
                          lambda fn=fn: fn(query_terms, location, max_age_days)))
        elif name == "jobspy":
            sites = (jobspy_cfg or {}).get("sites") or ["indeed", "google"]
            tasks.extend(build_jobspy_tasks(query_terms, jobspy_cfg or {},
                                            sites, max_age_days))
        else:
            tasks.append((f"agg:{name}",
                          lambda name=name: (_ for _ in ()).throw(
                              ValueError(f"unknown aggregator '{name}'"))))
    return tasks
