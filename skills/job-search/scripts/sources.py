"""Job-posting fetchers for public ATS APIs (no auth required for reads).

Each fetcher returns list[JobPosting] with a plain-text `description`.
Supported ATS: greenhouse, ashby, lever, smartrecruiters.
Add companies in companies.yaml; validate tokens with validate_companies.py.
"""
from __future__ import annotations

import concurrent.futures
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import capture_hooks
from common import (USER_AGENT, JobPosting, ashby_salary_range, http_get,
                    http_get_full, http_get_json, http_post_json,
                    http_post_json_full, parse_dt, provided_salary_range,
                    strip_html)

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

# Coarse title prefilter: only skip clearly-excluded titles before the (expensive)
# per-posting detail fetch. This never drops a title the pipeline's title gate would
# keep — it only avoids detailing obvious non-matches. The real title/location/visa
# gating still runs in scoring.py after fetch.
_BIGTECH_TITLE_SKIP = (
    "intern", "internship", "co-op", "new grad", "graduate program", "apprentice",
    " manager", "director", "principal", "distinguished", "fellow", "vice president",
    " vp ", "sales", "marketing", "recruit", "designer", "data scientist",
    "research scientist", "account executive", "customer success",
)


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
        desc = strip_html(j.get("content"))
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


def fetch_smartrecruiters(company: str, token: str) -> list[JobPosting]:
    """List postings, then fetch detail (description) for each."""
    base = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    list_url = f"{base}?limit=100"
    resp = http_get_full(list_url)
    returned, total_found = _sr_counts(resp.body)
    # VERIFIED-AT-IMPLEMENTATION (2026-07-21): SmartRecruiters hard-truncates the
    # listing at the `limit` cap — probes returned exactly 100 while `totalFound`
    # was 243 / 280. So this is a `search` (absence means nothing), never attested
    # complete; `totalFound > returned` (and, as a fallback, returned == cap) is the
    # truncation signal, recorded verbatim in the request params.
    truncated = bool(
        (total_found is not None and returned is not None and total_found > returned)
        or (returned is not None and returned >= 100))
    with capture_hooks.group("search", company, expected=None) as g:
        capture_hooks.capture_search(
            company, list_url, resp, source="smartrecruiters", item_count=returned,
            params={"limit": 100, "returned": returned, "total_found": total_found,
                    "truncated": truncated}, group=g)
        g.attest(complete=False)
    if not resp.ok:
        raise RuntimeError(f"GET failed for {list_url}: {resp.error}")
    data = json.loads(resp.body.decode("utf-8", "replace"))
    out = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        loc_str = ", ".join(x for x in [loc.get("city"), loc.get("region"),
                                        loc.get("country")] if x)
        remote = "remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid")
                                                      else "unknown")
        desc = ""
        try:
            detail = http_get_json(f"{base}/{j.get('id')}")
            sections = ((detail.get("jobAd") or {}).get("sections") or {})
            desc = strip_html(" ".join(
                (sections.get(k) or {}).get("text", "")
                for k in ("jobDescription", "qualifications", "additionalInformation")
            ))
        except Exception:
            pass
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
    return out


def _title_prefilter(title: str) -> bool:
    """True if the title is worth a detail fetch (drops only obvious non-matches)."""
    t = f" {title.lower()} "
    return not any(skip in t for skip in _BIGTECH_TITLE_SKIP)


def fetch_workday(company: str, token: str, host: str, site: str,
                  search_terms: list[str] | None = None,
                  max_candidates: int = 60) -> list[JobPosting]:
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
                    if path and title and _title_prefilter(title):
                        seen_paths.setdefault(path, None)
                if len(batch) < 20 or len(seen_paths) >= max_candidates:
                    break
                offset += 20
            if len(seen_paths) >= max_candidates:
                break
        g.attest(complete=False)

    def _detail(path: str) -> JobPosting | None:
        try:
            detail = http_get_json(f"{base}{path}")
        except Exception:
            return None
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

    paths = list(seen_paths)[:max_candidates]
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(_detail, paths):
            if res is not None:
                out.append(res)
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
                 max_candidates: int = 80) -> list[JobPosting]:
    """Fetch US postings from the amazon.jobs public search API (per term)."""
    terms = search_terms if search_terms is not None else DEFAULT_BIGTECH_TERMS
    seen: dict[str, JobPosting] = {}
    # A keyword-sampled, result-capped search — never attested complete.
    with capture_hooks.group("search", company, expected=None) as g:
        _fetch_amazon_terms(company, terms, seen, max_candidates, g)
        g.attest(complete=False)
    return list(seen.values())


def _fetch_amazon_terms(company, terms, seen, max_candidates, group) -> None:
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
            if not title or not path or path in seen or not _title_prefilter(title):
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
                max_candidates: int = 80) -> list[JobPosting]:
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
        _fetch_apple_terms(company, terms, seen, max_candidates, opener, token, g)
    return list(seen.values())


def _fetch_apple_terms(company, terms, seen, max_candidates, opener, token, group):
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
                if not pid or not title or pid in seen or not _title_prefilter(title):
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
               doc_id: str = "27807005005556827") -> list[JobPosting]:
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
        _fetch_meta_terms(company, terms, seen, max_candidates, doc_id, lsd, hsi, g)
    return list(seen.values())


def _fetch_meta_terms(company, terms, seen, max_candidates, doc_id, lsd, hsi, group):
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
            if not jid or not title or jid in seen or not _title_prefilter(title):
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


def fetch_company(entry: dict) -> list[JobPosting]:
    ats = entry.get("ats", "").lower()
    name = entry.get("name", entry.get("token", "?"))
    if ats == "workday":
        return fetch_workday(name, entry["token"], entry["host"], entry["site"],
                             entry.get("search_terms"))
    if ats == "amazon":
        return fetch_amazon(name, entry.get("search_terms"))
    if ats == "apple":
        return fetch_apple(name, entry.get("search_terms"))
    if ats == "meta":
        return fetch_meta(name, entry.get("search_terms"))
    fetcher = FETCHERS.get(ats)
    if not fetcher:
        raise ValueError(f"Unknown ATS '{ats}' for {entry.get('name')}")
    return fetcher(name, entry["token"])
