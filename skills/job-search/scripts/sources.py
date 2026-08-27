"""Job-posting fetchers for public ATS APIs (no auth required for reads).

Each fetcher returns list[JobPosting] with a plain-text `description`.
Supported ATS: greenhouse, ashby, lever, smartrecruiters.
Add companies in companies.yaml; validate tokens with validate_companies.py.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import capture_hooks
import title_filter
from common import (USER_AGENT, JobPosting, ashby_salary_range,
                    http_get, http_get_full, http_get_json,
                    http_post_json, http_post_json_full, parse_dt,
                    provided_salary_range, record_source_warning,
                    retry_after_seconds, strip_html)
from title_filter import TitleWordFilter

# Default search terms used by big-tech fetchers (Workday / Amazon) so we query a
# few relevant slices of a huge board instead of pulling every posting. Companies
# in companies.yaml may override with a `search_terms` list.
DEFAULT_BIGTECH_TERMS = [
    "kubernetes",
    "platform engineer",
    "infrastructure engineer",
    "ai infrastructure",
    "developer productivity",
    "site reliability",
]

_WORKDAY_DETAIL_PACE_SECONDS = 0.25
_WORKDAY_DETAIL_RECOVERY_ROUNDS = 2
_WORKDAY_RETRY_AFTER_CEILING_SECONDS = 10.0
_WORKDAY_FALLBACK_BACKOFF_SECONDS = 1.0


class _WorkdayTenantPacer:
    """Space request starts for one Workday tenant; never shared across boards."""

    def __init__(self, interval: float, *, sleep=None, monotonic=None):
        self.interval = max(float(interval), 0.0)
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._next_start = 0.0

    def wait(self) -> None:
        delay = max(self._next_start - self._monotonic(), 0.0)
        if delay:
            self._sleep(delay)
        self._next_start = self._monotonic() + self.interval

    def defer(self, delay: float) -> None:
        """Do not start another request for this tenant before ``delay``."""
        self._next_start = max(
            self._next_start, self._monotonic() + max(float(delay), 0.0))


# Coarse title prefilter: skip a title the CANDIDATE'S PROFILE declared always
# unwanted, before the (expensive) per-posting detail fetch. A dropped title never
# gets a detail fetch, so it never enters the pipeline and appears in NO count —
# which is why the words are the candidate's to choose and only the unconditional
# class (`titles.word_filter.hard_exclude`) may drop one here.
#
# The list used to be a hardcoded tuple in this file. Owner decision 2026-08-01:
# it is profile-based now, with three classes — hard_exclude (always drop),
# soft_exclude (keep + mark for AI judgement) and include (keep + mark: "check
# this one out"). Semantics, matching, precedence and the unconfigured-profile
# behaviour all live in `title_filter.py`; nothing about the policy lives here.
#
# The two classes that are NOT hard_exclude deliberately survive this gate. That
# is the recall rule the old comment block argued for at length: keeping a title
# costs one detail fetch, dropping one costs the posting, and `scoring.assess_title`
# still gates everything that survives — so on an ambiguous title the answer is
# KEEP and let the JD decide.
#
# The real title/location/visa gating still runs in scoring.py after fetch.


def _remote_from(text: str, flag=None, workplace: str | None = None) -> str:
    if workplace:
        wp = workplace.lower()
        if "remote" in wp:
            return "remote"
        if "hybrid" in wp:
            return "hybrid"
        if "site" in wp or "office" in wp:
            return "onsite"
    if flag is True:
        return "remote"
    low = (text or "").lower()
    if "remote" in low:
        return "remote"
    if "hybrid" in low:
        return "hybrid"
    return "unknown"


def fetch_greenhouse(company: str, token: str) -> list[JobPosting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    resp = http_get_full(url)
    # Capture-before-parse: a complete Greenhouse board is a `board` in a group of
    # one, attested complete only when we actually got a parseable 200. The raw
    # blob lands here — before any parse below can fail.
    # NOTE (Stage-2 normalization hook): Greenhouse `content=true` descriptions
    # arrive HTML-ENTITY-ESCAPED (see strip_html's double html.unescape); the raw
    # captures the escaped original verbatim, and Stage-2's *versioned* normalizer
    # must unescape before any semantic content hash — else every poll looks changed.
    item_count = capture_hooks.safe_item_count(resp.body, "jobs")
    data, parse_ok = None, False
    with capture_hooks.group("board", company, expected=1) as g:
        capture_hooks.capture_board(company, url, resp, source="greenhouse",
                                    item_count=item_count,
                                    params={"content": "true"}, group=g)
        # Attest complete ONLY after the body parses into the expected shape (a
        # `jobs` list) — a network-truncated non-empty 200 must never attest a
        # false complete.
        if resp.ok and resp.body:
            try:
                data = json.loads(resp.body.decode("utf-8", "replace"))
                parse_ok = True
            except ValueError:
                parse_ok = False
        shape_ok = parse_ok and isinstance(data, dict) \
            and isinstance(data.get("jobs"), list)
        g.attest(complete=shape_ok)
    if not resp.ok:
        raise RuntimeError(f"GET failed for {url}: {resp.error}")
    if not parse_ok:
        raise RuntimeError(f"greenhouse: unparseable board for {url}")
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") or ""
        # Greenhouse `content=true` is the toolkit's ONE double-entity-encoded
        # source (reference.md / LESSONS.md); every other source is single-encoded
        # and must NOT get the extra decode.
        desc = strip_html(j.get("content"), entity_encoded=True)
        out.append(JobPosting(
            source="greenhouse",
            company=company,
            title=j.get("title", "").strip(),
            url=j.get("absolute_url", ""),
            location=loc,
            # Raw location hint only; the shared full-evidence evaluator reads the
            # complete JD later and owns the final workplace/location decision.
            remote=_remote_from(loc),
            posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            description=desc,
        ))
    return out


def fetch_ashby(company: str, token: str) -> list[JobPosting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
    resp = http_get_full(url)
    item_count = capture_hooks.safe_item_count(resp.body, "jobs")
    data, parse_ok = None, False
    with capture_hooks.group("board", company, expected=1) as g:
        capture_hooks.capture_board(company, url, resp, source="ashby",
                                    item_count=item_count, group=g)
        if resp.ok and resp.body:
            try:
                data = json.loads(resp.body.decode("utf-8", "replace"))
                parse_ok = True
            except ValueError:
                parse_ok = False
        shape_ok = parse_ok and isinstance(data, dict) \
            and isinstance(data.get("jobs"), list)
        g.attest(complete=shape_ok)  # complete only after the expected shape parses
    if not resp.ok:
        raise RuntimeError(f"GET failed for {url}: {resp.error}")
    if not parse_ok:
        raise RuntimeError(f"ashby: unparseable board for {url}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location", "") or ""
        sec = j.get("secondaryLocations") or []
        if sec:
            extra = ", ".join(s.get("location", "") for s in sec if s.get("location"))
            loc = f"{loc} / {extra}" if extra else loc
        desc = j.get("descriptionPlain") or strip_html(j.get("descriptionHtml"))
        out.append(JobPosting(
            source="ashby",
            company=company,
            title=j.get("title", "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            location=loc,
            remote=_remote_from(loc, j.get("isRemote"), j.get("workplaceType")),
            posted_at=parse_dt(j.get("publishedAt")),
            description=desc,
            salary_range=ashby_salary_range(j.get("compensation")),
        ))
    return out


def fetch_lever(company: str, token: str) -> list[JobPosting]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    resp = http_get_full(url)
    item_count = capture_hooks.safe_item_count(resp.body)  # a top-level JSON array
    data, parse_ok = None, False
    with capture_hooks.group("board", company, expected=1) as g:
        capture_hooks.capture_board(company, url, resp, source="lever",
                                    item_count=item_count, params={"mode": "json"},
                                    group=g)
        if resp.ok and resp.body:
            try:
                data = json.loads(resp.body.decode("utf-8", "replace"))
                parse_ok = True
            except ValueError:
                parse_ok = False
        g.attest(complete=parse_ok and isinstance(data, list))  # complete only if list
    if not resp.ok:
        raise RuntimeError(f"GET failed for {url}: {resp.error}")
    if not parse_ok:
        raise RuntimeError(f"lever: unparseable board for {url}")
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location", "") or ""
        body = j.get("descriptionPlain") or strip_html(j.get("description"))
        additional = j.get("additionalPlain") or strip_html(j.get("additional"))
        desc = "\n\n".join(part for part in (body, additional) if part)
        salary = j.get("salaryRange") or {}
        out.append(JobPosting(
            source="lever",
            company=company,
            title=j.get("text", "").strip(),
            url=j.get("hostedUrl") or j.get("applyUrl", ""),
            location=loc,
            remote=_remote_from(loc, workplace=j.get("workplaceType")),
            posted_at=parse_dt(j.get("createdAt")),
            description=desc,
            salary_range=provided_salary_range(
                salary.get("min"),
                salary.get("max"),
                currency=salary.get("currency"),
                period=salary.get("interval"),
                source="lever_api",
            ),
        ))
    return out


def _sr_counts(body: bytes | None) -> tuple[int | None, int | None]:
    """Best-effort ``(returned_count, totalFound)`` from a SmartRecruiters listing.

    Never raises (over-capture only): returns ``(None, None)`` on any parse problem
    so it can run before capture without ever blocking capture-of-raw.
    """
    if not body:
        return None, None
    try:
        d = json.loads(body.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(d, dict):
        return None, None
    content = d.get("content")
    returned = len(content) if isinstance(content, list) else None
    total = d.get("totalFound")
    return returned, (total if isinstance(total, int) else None)


# SmartRecruiters serves its listing one PAGE at a time and hard-truncates each
# page at `limit`. VERIFIED-AT-IMPLEMENTATION (2026-07-21): probes returned
# exactly 100 rows while `totalFound` said 243 / 280. Reading one page therefore
# inspects the first 100 rows of a board and silently ignores the rest — on a
# 357-posting board that is 257 live rows that never reach the title/JD/location/
# sponsorship gates, and WHICH rows survive is the provider's page ordering.
_SR_PAGE_LIMIT = 100
# Per-board ceiling for one run. Reaching it is a DELIBERATE cap (a registry entry
# may raise it with `max_postings:`), reported as a cap and never as a source
# failure — the two mean opposite things to a reader of the run summary.
_SR_MAX_POSTINGS = 1000


def _sr_listing_rows(company: str, base: str,
                     max_postings: int) -> tuple[list[dict], dict]:
    """Page the SmartRecruiters listing; return (rows, what-we-actually-saw).

    Paging stops on the FIRST of: a short page (fewer rows than ``limit`` — the
    clean end of the board), ``offset`` reaching a sane ``totalFound``, the
    ``max_postings`` cap, or a page that contributes no id we have not already
    seen. That last one is the loop guard: a provider that ignores ``offset`` and
    replays page 1 forever cannot spin this loop, and a malformed/absent
    ``totalFound`` changes nothing because no stop condition depends on it alone.

    The FIRST page is load-bearing — a failure there means we saw no board at all
    and raises, exactly as the single-request version did. A LATER page failing is
    a partial listing: the rows already in hand are real and are kept, with the
    shortfall reported. Rows are deduped by posting id, so an overlapping page
    cannot double-count.
    """
    rows: list[dict] = []
    seen_ids: set[str] = set()
    offset = 0
    total_found: int | None = None
    pages = 0
    info = {"capped": False, "incomplete": None}
    with capture_hooks.group("search", company, expected=None) as g:
        g.attest(complete=False)   # a paged search still never attests complete
        while True:
            list_url = f"{base}?limit={_SR_PAGE_LIMIT}&offset={offset}"
            resp = http_get_full(list_url)
            returned, total = _sr_counts(resp.body)
            if total is not None:
                total_found = total
            capture_hooks.capture_search(
                company, list_url, resp, source="smartrecruiters",
                item_count=returned,
                pagination={"offset": offset, "limit": _SR_PAGE_LIMIT},
                params={"limit": _SR_PAGE_LIMIT, "offset": offset,
                        "returned": returned, "total_found": total_found},
                group=g)
            if not resp.ok:
                if not pages:
                    raise RuntimeError(f"GET failed for {list_url}: {resp.error}")
                info["incomplete"] = f"page at offset {offset} failed: {resp.error}"
                break
            try:
                data = json.loads(resp.body.decode("utf-8", "replace"))
            except ValueError as exc:
                if not pages:
                    raise RuntimeError(
                        f"smartrecruiters: unparseable listing for {list_url}") from exc
                info["incomplete"] = f"page at offset {offset} was unparseable: {exc}"
                break
            pages += 1
            content = data.get("content") if isinstance(data, dict) else None
            content = content if isinstance(content, list) else []
            fresh = 0
            for j in content:
                if not isinstance(j, dict):
                    continue
                key = str(j.get("id") or j.get("ref") or "")
                if key and key in seen_ids:
                    continue
                if key:
                    seen_ids.add(key)
                rows.append(j)
                fresh += 1
                if len(rows) >= max_postings:
                    break
            if len(rows) >= max_postings:
                info["capped"] = True
                break
            if len(content) < _SR_PAGE_LIMIT:
                break                                    # clean end of the board
            if not fresh:
                info["incomplete"] = (
                    f"the page at offset {offset} repeated rows already seen "
                    f"(the board is not paging); stopped to avoid a loop")
                break
            offset += _SR_PAGE_LIMIT
            if total_found is not None and total_found > 0 and offset >= total_found:
                break
    if (info["incomplete"] is None and not info["capped"]
            and isinstance(total_found, int) and 0 < len(rows) < total_found):
        # We walked to the end of the pages and still hold fewer rows than the
        # board advertises. That is not a clean board: it shifted under the crawl,
        # or paging stopped short. Either way the shortfall is real and must not
        # read as full coverage.
        info["incomplete"] = (
            f"the listing ended after {len(rows)} rows while totalFound said "
            f"{total_found}")
    info["total_found"] = total_found
    info["pages"] = pages
    return rows, info


def fetch_smartrecruiters(company: str, token: str,
                          max_postings: int = _SR_MAX_POSTINGS) -> list[JobPosting]:
    """List postings (paged to the end of the board), then fetch detail for each."""
    base = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    listing, info = _sr_listing_rows(company, base, max_postings)
    out = []
    attempted = 0
    failures: list[str] = []
    for j in listing:
        loc = j.get("location") or {}
        loc_str = ", ".join(x for x in [loc.get("city"), loc.get("region"),
                                        loc.get("country")] if x)
        remote = "remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid")
                                                      else "unknown")
        desc = ""
        attempted += 1
        try:
            detail = http_get_json(f"{base}/{j.get('id')}")
            sections = ((detail.get("jobAd") or {}).get("sections") or {})
            desc = strip_html(" ".join(
                (sections.get(k) or {}).get("text", "")
                for k in ("jobDescription", "qualifications", "additionalInformation")
            ))
        except Exception as exc:  # noqa: BLE001
            # A swallowed JD fetch used to emit the posting with description="",
            # which is indistinguishable from "this JD really is empty": the visa
            # gate reads `unclear` and keeps it, the YOE gate has nothing to read,
            # and the keyword score collapses, so the row survives ranked below
            # top_k and is never seen. Count it and say so instead.
            failures.append(f"{j.get('id')}: {exc}")
        out.append(JobPosting(
            source="smartrecruiters",
            company=company,
            title=j.get("name", "").strip(),
            url=(j.get("ref") or f"https://jobs.smartrecruiters.com/{token}/{j.get('id')}"),
            location=loc_str,
            remote=remote,
            posted_at=parse_dt(j.get("releasedDate")),
            description=desc,
        ))
    if failures and len(failures) == attempted:
        # Total JD outage: every posting would carry an empty description. That is
        # a failed fetch, not a board of contentless jobs — raise so run_tasks
        # records it as a source error rather than reporting a clean result.
        raise RuntimeError(
            f"smartrecruiters {company}: all {attempted} JD detail fetches failed "
            f"(first: {failures[0]})")
    if failures:
        record_source_warning(
            f"smartrecruiters:{company}: {len(failures)} of {attempted} JD detail "
            f"fetches failed (first: {failures[0]}); those postings carry an empty "
            f"description")
    if info["capped"]:
        # A CAP, not a failure — the two mean opposite things. Name the knob.
        total = info["total_found"]
        of_total = f" of {total}" if total else ""
        record_source_warning(
            f"smartrecruiters:{company}: stopped at the configured per-board cap "
            f"of {max_postings} postings{of_total}; the remainder was not "
            f"inspected. Raise it with `max_postings:` on this company's "
            f"companies.yaml row.")
    if info["incomplete"]:
        record_source_warning(
            f"smartrecruiters:{company}: listing incomplete after "
            f"{len(listing)} postings — {info['incomplete']}; the remainder was "
            f"not inspected")
    return out


def _title_prefilter(title: str, word_filter: TitleWordFilter | None = None) -> bool:
    """True if the title is worth a detail fetch.

    Only the profile's ``hard_exclude`` class answers False. ``word_filter=None``
    is the INERT filter — an unconfigured profile, or a caller (a test, an ad-hoc
    board dump) that has no profile at all — and keeps every title, leaving the
    decision entirely to ``scoring.assess_title``.
    """
    return (word_filter or title_filter.INERT).prefilter(title)


def _workday_posting(company: str, host: str, site: str, path: str,
                     detail: dict) -> JobPosting | None:
    jp = detail.get("jobPostingInfo") or {}
    title = (jp.get("title") or "").strip()
    if not title:
        return None
    loc = jp.get("location") or ""
    extra = jp.get("additionalLocations") or []
    if extra:
        loc = f"{loc} / " + " / ".join(x for x in extra if x)
    desc = strip_html(jp.get("jobDescription"))
    remote_hint = "remote" if jp.get("remoteType") and "remote" in \
        str(jp.get("remoteType")).lower() else ""
    return JobPosting(
        source="workday",
        company=company,
        title=title,
        url=jp.get("externalUrl") or f"https://{host}/{site}{path}",
        location=loc,
        remote=_remote_from(f"{loc} {remote_hint}"),
        posted_at=parse_dt(jp.get("startDate")),
        description=desc,
    )


def _fetch_workday_details(company: str, host: str, site: str, base: str,
                           paths: list[str]) -> tuple[list[JobPosting], list[str], int]:
    """Fetch each path once, then retry only misses in two bounded rounds.

    Returns ``(postings, final_failures, attempts)``. One pacer instance belongs
    to this call/tenant; the outer source executor may run other tenants without
    sharing its delay. Generic HTTP retries are disabled so a failed path remains
    visible to this recovery loop instead of sleeping invisibly inside a worker.
    """
    pacer = _WorkdayTenantPacer(_WORKDAY_DETAIL_PACE_SECONDS)
    recovered: dict[str, JobPosting] = {}
    ordered_paths = list(dict.fromkeys(paths))
    pending = list(ordered_paths)
    last_errors: dict[str, str] = {}
    attempts = 0

    for recovery_round in range(_WORKDAY_DETAIL_RECOVERY_ROUNDS + 1):
        if not pending:
            break
        missed: list[str] = []
        for path in pending:
            pacer.wait()
            url = f"{base}{path}"
            resp = http_get_full(url, retries=0)
            attempts += 1
            if resp.ok:
                try:
                    detail = json.loads(resp.body.decode("utf-8", "replace"))
                except ValueError as exc:
                    last_errors[path] = f"invalid JSON: {exc}"
                    missed.append(path)
                    continue
                posting = _workday_posting(company, host, site, path, detail)
                if posting is not None:
                    recovered[path] = posting
                # A valid JSON response with no posting is inspected and therefore
                # not a transport-coverage miss. Preserve the old skip behavior.
                last_errors.pop(path, None)
                continue

            last_errors[path] = resp.error or f"HTTP {resp.status}"
            missed.append(path)
            if resp.status == 429:
                delay = retry_after_seconds(
                    resp.headers,
                    ceiling=_WORKDAY_RETRY_AFTER_CEILING_SECONDS,
                )
                if delay is None:
                    delay = min(
                        _WORKDAY_FALLBACK_BACKOFF_SECONDS * (2 ** recovery_round),
                        _WORKDAY_RETRY_AFTER_CEILING_SECONDS,
                    )
                # The deferral applies to the tenant, not just this path: a 429 is
                # a signal that the board wants the whole caller to slow down.
                pacer.defer(delay)
        pending = missed

    failures = [f"{path}: {last_errors[path]}" for path in pending]
    # Listing order is the stable output order, and the path-keyed map guarantees
    # a recovered posting is emitted exactly once.
    postings = [recovered[path] for path in ordered_paths if path in recovered]
    return postings, failures, attempts


def fetch_workday(company: str, token: str, host: str, site: str,
                  search_terms: list[str] | None = None,
                  max_candidates: int = 60,
                  word_filter: TitleWordFilter | None = None) -> list[JobPosting]:
    """Fetch postings from a Workday CXS board.

    host   = e.g. "nvidia.wd5.myworkdayjobs.com"
    token  = Workday tenant, e.g. "nvidia"
    site   = external career site path, e.g. "NVIDIAExternalCareerSite"

    Queries the POST /jobs search endpoint per term (paged), collects unique
    postings, then fetches each posting's detail (precise location, description,
    real posted date, canonical URL). Bounded by max_candidates to keep a large
    board's fetch cheap.
    """
    base = f"https://{host}/wday/cxs/{token}/{site}"
    terms = search_terms if search_terms is not None else DEFAULT_BIGTECH_TERMS
    search_url = f"{base}/jobs"

    def _post_page(payload, group, term, offset, retries=2):
        # Capture EACH attempt (failed bodies are failure history by design) and
        # retry a 2xx body that will not parse — restoring the old http_post_json
        # ValueError-retry semantics. Returns parsed data, or None to break the
        # page loop (transport failure or exhausted retries → old raise-then-break).
        for _ in range(retries + 1):
            resp = http_post_json_full(search_url, payload)
            capture_hooks.capture_search(
                company, search_url, resp, source="workday",
                item_count=capture_hooks.safe_item_count(resp.body, "jobPostings"),
                query={"searchText": term},
                pagination={"offset": offset, "limit": 20},
                params={"searchText": term, "offset": offset, "limit": 20},
                group=group)
            if not resp.ok:
                return None
            try:
                return json.loads(resp.body.decode("utf-8", "replace"))
            except ValueError:
                continue
        return None

    seen_paths: dict[str, None] = {}
    # One `search` group per company covering ALL its POST search-page requests
    # (a keyword-sampled, capped board — never attested complete). expected is left
    # open (we do not pre-commit to a request count); achieved = the real member
    # count the group manifest records.
    with capture_hooks.group("search", company, expected=None) as g:
        for term in terms:
            offset = 0
            while offset < 40:  # up to 2 pages (20/page) per term
                payload = {"appliedFacets": {}, "limit": 20, "offset": offset,
                           "searchText": term}
                data = _post_page(payload, g, term, offset)
                if data is None:
                    break
                batch = data.get("jobPostings") or []
                for jp in batch:
                    path = jp.get("externalPath")
                    title = (jp.get("title") or "").strip()
                    if path and title and _title_prefilter(title, word_filter):
                        seen_paths.setdefault(path, None)
                if len(batch) < 20 or len(seen_paths) >= max_candidates:
                    break
                offset += 20
            if len(seen_paths) >= max_candidates:
                break
        g.attest(complete=False)

    paths = list(seen_paths)[:max_candidates]
    out, detail_failures, detail_attempts = _fetch_workday_details(
        company, host, site, base, paths)
    if paths and len(detail_failures) == len(paths):
        # Nothing was inspected. Raise so search_jobs.run_tasks records
        # `board:<company>: ...` and the run summary reports a source error,
        # instead of the board reporting cleanly that it has no matching jobs.
        raise RuntimeError(
            f"workday {company}: all {len(paths)} detail fetches failed after "
            f"{detail_attempts} bounded attempts "
            f"(first: {detail_failures[0]})")
    if detail_failures:
        record_source_warning(
            f"workday:{company}: coverage=incomplete; {len(detail_failures)} of "
            f"{len(paths)} detail fetches failed after bounded recovery "
            f"({detail_attempts} total attempts; first: {detail_failures[0]}); "
            f"those postings were not inspected")
    return out


def _parse_amazon_date(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return parse_dt(cleaned)


def fetch_amazon(company: str, search_terms: list[str] | None = None,
                 max_candidates: int = 80,
                 word_filter: TitleWordFilter | None = None) -> list[JobPosting]:
    """Fetch US postings from the amazon.jobs public search API (per term)."""
    terms = search_terms if search_terms is not None else DEFAULT_BIGTECH_TERMS
    seen: dict[str, JobPosting] = {}
    # A keyword-sampled, result-capped search — never attested complete.
    with capture_hooks.group("search", company, expected=None) as g:
        _fetch_amazon_terms(company, terms, seen, max_candidates, g, word_filter)
        g.attest(complete=False)
    return list(seen.values())


def _fetch_amazon_terms(company, terms, seen, max_candidates, group,
                        word_filter=None) -> None:
    for term in terms:
        search_url = ("https://www.amazon.jobs/en/search.json?"
                      + f"base_query={term.replace(' ', '+')}&country=USA"
                      + "&result_limit=40&sort=recent")
        resp = http_get_full(search_url)
        capture_hooks.capture_search(
            company, search_url, resp, source="amazon",
            item_count=capture_hooks.safe_item_count(resp.body, "jobs"),
            query={"base_query": term, "country": "USA"},
            params={"result_limit": 40, "sort": "recent"}, group=group)
        if not resp.ok:
            continue
        try:
            data = json.loads(resp.body.decode("utf-8", "replace"))
        except ValueError:
            continue
        for j in data.get("jobs", []):
            if j.get("is_intern") or j.get("is_manager"):
                continue
            title = (j.get("title") or "").strip()
            path = j.get("job_path") or ""
            if (not title or not path or path in seen
                    or not _title_prefilter(title, word_filter)):
                continue
            loc = j.get("normalized_location") or ", ".join(
                x for x in (j.get("city"), j.get("state"),
                            j.get("country_code")) if x)
            desc = strip_html(" ".join(x for x in (
                j.get("description"), j.get("basic_qualifications"),
                j.get("preferred_qualifications")) if x))
            seen[path] = JobPosting(
                source="amazon",
                company=company,
                title=title,
                url=f"https://www.amazon.jobs{path}",
                location=loc,
                remote=_remote_from(loc),
                posted_at=_parse_amazon_date(j.get("posted_date")),
                description=desc,
            )
            if len(seen) >= max_candidates:
                break
        if len(seen) >= max_candidates:
            break


def _opener_resp(resp, body: bytes):
    """Build a capture-shim HTTP result from a raw urllib opener response + bytes."""
    hdrs = getattr(resp, "headers", None)
    headers = dict(hdrs.items()) if hdrs else {}
    ctype = hdrs.get_content_type() if hdrs else None
    return capture_hooks.make_resp(getattr(resp, "status", 200) or 200, body,
                                   content_type=ctype, headers=headers)


def fetch_apple(company: str = "Apple", search_terms: list[str] | None = None,
                max_candidates: int = 80,
                word_filter: TitleWordFilter | None = None) -> list[JobPosting]:
    """Fetch US postings from jobs.apple.com (cookie jar + per-session CSRF token)."""
    terms = search_terms if search_terms is not None else DEFAULT_BIGTECH_TERMS
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept", "application/json, */*")]
    seen: dict[str, JobPosting] = {}
    # One `search` group per run covering the cookie/CSRF handshake AND every search
    # POST — a keyword-sampled, capped board, never attested complete.
    with capture_hooks.group("search", company, expected=None) as g:
        g.attest(complete=False)
        try:
            hs = opener.open("https://jobs.apple.com/en-us/search", timeout=25)
            hs_body = hs.read()
            capture_hooks.capture_search(company, "https://jobs.apple.com/en-us/search",
                                         _opener_resp(hs, hs_body), source="apple",
                                         params={"phase": "handshake"}, group=g)
            resp = opener.open("https://jobs.apple.com/api/v1/CSRFToken", timeout=25)
            csrf_body = resp.read()
            token = resp.headers.get("x-apple-csrf-token", "")
            capture_hooks.capture_search(company, "https://jobs.apple.com/api/v1/CSRFToken",
                                         _opener_resp(resp, csrf_body), source="apple",
                                         params={"phase": "csrf"}, group=g)
        except Exception:
            return []
        if not token:
            return []
        _fetch_apple_terms(company, terms, seen, max_candidates, opener, token, g,
                           word_filter)
    return list(seen.values())


def _fetch_apple_terms(company, terms, seen, max_candidates, opener, token, group,
                       word_filter=None):
    for term in terms:
        for page in (1, 2):
            payload = json.dumps({
                "query": term, "filters": {"locations": ["postLocation-USA"]},
                "page": page, "locale": "en-us", "sort": "newest",
                "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://jobs.apple.com/api/v1/search", data=payload, method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json",
                         "x-apple-csrf-token": token, "User-Agent": USER_AGENT,
                         "Origin": "https://jobs.apple.com",
                         "Referer": "https://jobs.apple.com/en-us/search"})
            try:
                r = opener.open(req, timeout=25)
                token = r.headers.get("x-apple-csrf-token", token)
                body = r.read()
                capture_hooks.capture_search(
                    company, "https://jobs.apple.com/api/v1/search",
                    _opener_resp(r, body), source="apple",
                    item_count=capture_hooks.safe_item_count(body),
                    query={"query": term}, pagination={"page": page},
                    params={"query": term, "page": page}, group=group)
                data = json.loads(body.decode("utf-8", "replace"))
            except Exception:
                break
            results = ((data.get("res") or {}).get("searchResults")) or []
            if not results:
                break
            for j in results:
                pid = str(j.get("positionId") or "")
                title = (j.get("postingTitle") or "").strip()
                if (not pid or not title or pid in seen
                        or not _title_prefilter(title, word_filter)):
                    continue
                locs = j.get("locations") or []
                loc = " / ".join(x.get("name", "") for x in locs if x.get("name"))
                country = " / ".join(x.get("countryName", "") for x in locs
                                     if x.get("countryName"))
                slug = j.get("transformedPostingTitle") or ""
                team = (j.get("team") or {}).get("teamCode", "")
                url = f"https://jobs.apple.com/en-us/details/{pid}/{slug}"
                if team:
                    url += f"?team={team}"
                seen[pid] = JobPosting(
                    source="apple", company=company, title=title, url=url,
                    location=f"{loc} {country}".strip(),
                    remote=_remote_from(f"{loc} {country} "
                                        f"{'remote' if j.get('homeOffice') else ''}"),
                    posted_at=_parse_amazon_date(j.get("postingDate")),
                    description=strip_html(j.get("jobSummary")))
                if len(seen) >= max_candidates:
                    break
            if len(seen) >= max_candidates:
                break
        if len(seen) >= max_candidates:
            break


_META_LSD_RE = re.compile(r'"LSD",\[\],\{"token":"([^"]+)"')
_META_HSI_RE = re.compile(r'"hsi":"(\d+)"')


def fetch_meta(company: str = "Meta", search_terms: list[str] | None = None,
               max_candidates: int = 80,
               doc_id: str = "27807005005556827",
               word_filter: TitleWordFilter | None = None) -> list[JobPosting]:
    """Fetch postings from metacareers.com (Relay GraphQL; needs LSD/hsi from HTML).

    The search operation returns title + locations + id only (no description); the
    location gate still applies and tailoring fetches the full JD from the job URL.
    """
    terms = search_terms if search_terms is not None else DEFAULT_BIGTECH_TERMS
    seen: dict[str, JobPosting] = {}
    # One `search` group covering the HTML bootstrap GET (for LSD/hsi) and every
    # GraphQL POST — keyword-sampled, never attested complete.
    with capture_hooks.group("search", company, expected=None) as g:
        g.attest(complete=False)
        page_resp = http_get_full("https://www.metacareers.com/jobs")
        capture_hooks.capture_search(company, "https://www.metacareers.com/jobs",
                                     page_resp, source="meta",
                                     params={"phase": "bootstrap"}, group=g)
        if not page_resp.ok:
            return []
        page_html = page_resp.body.decode("utf-8", "replace")
        lm = _META_LSD_RE.search(page_html)
        if not lm:
            return []
        lsd = lm.group(1)
        hm = _META_HSI_RE.search(page_html)
        hsi = hm.group(1) if hm else "0"
        _fetch_meta_terms(company, terms, seen, max_candidates, doc_id, lsd, hsi, g,
                          word_filter)
    return list(seen.values())


def _fetch_meta_terms(company, terms, seen, max_candidates, doc_id, lsd, hsi, group,
                      word_filter=None):
    url = "https://www.metacareers.com/api/graphql/"
    for term in terms:
        form = {
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "CPJobSearchSourceQuery",
            "variables": json.dumps({"search_input": {
                "q": term, "results_per_page": "FIFTEEN"}}),
            "doc_id": doc_id, "lsd": lsd, "__a": "1", "__user": "0", "__hsi": hsi,
        }
        req = urllib.request.Request(
            url, data=urllib.parse.urlencode(form).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "X-FB-LSD": lsd, "User-Agent": USER_AGENT,
                     "Origin": "https://www.metacareers.com",
                     "Referer": "https://www.metacareers.com/jobs"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                body = r.read()
                capture_hooks.capture_search(company, url, _opener_resp(r, body),
                                             source="meta", query={"q": term},
                                             params={"q": term, "doc_id": doc_id},
                                             group=group)
                data = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            continue
        node = (data.get("data") or {}).get("job_search_with_featured_jobs") or {}
        jobs = node.get("all_jobs") or node.get("jobs") or []
        for j in jobs:
            jid = str(j.get("id") or "")
            title = (j.get("title") or "").strip()
            if (not jid or not title or jid in seen
                    or not _title_prefilter(title, word_filter)):
                continue
            locs = j.get("locations") or []
            loc = " / ".join(x for x in locs if isinstance(x, str))
            seen[jid] = JobPosting(
                source="meta", company=company, title=title,
                url=f"https://www.metacareers.com/jobs/{jid}/", location=loc,
                remote=_remote_from(loc), posted_at=None, description="")
            if len(seen) >= max_candidates:
                break
        if len(seen) >= max_candidates:
            break


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "ashby": fetch_ashby,
    "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters,
}


def fetch_company(entry: dict,
                  word_filter: TitleWordFilter | None = None) -> list[JobPosting]:
    """Fetch one registry entry's board.

    ``word_filter`` is the candidate profile's ``titles.word_filter`` (see
    ``title_filter.py``). Only the big-tech fetchers consult it, because only they
    pay a per-posting detail fetch that a coarse title decision can save; every
    other ATS returns its whole board in one request, so their titles reach the
    pipeline and are classified there alongside the aggregator rows. Omitted (or
    ``None``) means the inert filter: nothing is dropped before the title gate.
    """
    ats = entry.get("ats", "").lower()
    name = entry.get("name", entry.get("token", "?"))
    if ats == "workday":
        return fetch_workday(name, entry["token"], entry["host"], entry["site"],
                             entry.get("search_terms"), word_filter=word_filter)
    if ats == "amazon":
        return fetch_amazon(name, entry.get("search_terms"),
                            word_filter=word_filter)
    if ats == "apple":
        return fetch_apple(name, entry.get("search_terms"),
                           word_filter=word_filter)
    if ats == "meta":
        return fetch_meta(name, entry.get("search_terms"),
                          word_filter=word_filter)
    if ats == "smartrecruiters":
        # The only ATS here that PAGES. `max_postings` is the per-board ceiling a
        # very large employer's row can raise; reaching it is reported as a cap.
        return fetch_smartrecruiters(
            name, entry["token"],
            max_postings=int(entry.get("max_postings") or _SR_MAX_POSTINGS))
    fetcher = FETCHERS.get(ats)
    if not fetcher:
        raise ValueError(f"Unknown ATS '{ats}' for {entry.get('name')}")
    return fetcher(name, entry["token"])
