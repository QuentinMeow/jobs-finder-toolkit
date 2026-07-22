"""Builder-side payload parsers + the versioned JD-text normalizer (Stage 2).

Pure functions that turn one captured raw payload's **bytes** into a list of
normalized row dicts — the builder's view of "what postings did this fetch
observe". These live on the *builder* side (not the live fetchers) so a parser
improvement re-labels history on the next rebuild without touching the
battle-tested fetch path; a parity harness (``tests/test_posting_parsers.py``)
feeds the same fixture bytes through both a parser here and the live fetcher's
parsing path and asserts the payload-derived fields agree, catching silent drift.

Each parser returns ``list[Row]`` where a ``Row`` is a plain dict with the keys::

    source, operation, native_id, title, url, location,
    posted_at (isoformat|None), company_name (source-claimed|None),
    description (plain text), workplace_raw, salary_text

``native_id`` is the platform identifier the identity layer keys on
(``posting_identity``); ``description`` is already ``strip_html``-flattened plain
text (the readable JD body used both for ``jd.md`` and as classifier input).

The normalizer is **versioned** (``NORMALIZER_VERSION``): the semantic
``content_hash`` used for JD change-detection is computed over normalized text
only, so a normalizer improvement is treated like a schema bump (recorded in the
entity; hashes are recomputed on rebuild by construction, never retroactively
"changed"). Greenhouse ``content=true`` bodies arrive HTML-entity-ESCAPED, so the
normalizer (like ``common.strip_html``) unescapes twice before hashing — else
every poll would look "changed".
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import urllib.parse

from common import parse_dt, strip_html


def _flex_date(value) -> str | None:
    """ISO string for a date; also parses the ``Month D, YYYY`` form Amazon/Apple use."""
    dt = parse_dt(value)
    if dt is None and value:
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                dt = _dt.datetime.strptime(cleaned, fmt).replace(tzinfo=_dt.timezone.utc)
                break
            except ValueError:
                continue
    return dt.isoformat() if dt else None

# ── versioned JD-text normalizer ─────────────────────────────
# Bump = schema-change treatment (recorded per entity; a bump invalidates nothing
# retroactively because hashes are recomputed on every rebuild).
NORMALIZER_VERSION = 1

_WS_RE = re.compile(r"\s+")


def normalize_text(raw: str | None) -> str:
    """Normalize JD text for hashing: entity-unescape (twice), tag-strip, collapse.

    Reuses ``common.strip_html`` (double ``html.unescape`` + tag strip) so the
    normalizer can never drift from the live plain-text extraction, then lowercases
    and collapses ALL whitespace (including newlines) so trivial reflowing does not
    read as a content change.
    """
    text = strip_html(raw)
    return _WS_RE.sub(" ", text).strip().lower()


def content_hash(raw: str | None) -> str:
    """Semantic content hash of JD text — sha256 over the *normalized* text."""
    return hashlib.sha256(normalize_text(raw).encode("utf-8")).hexdigest()


# ── row helper ───────────────────────────────────────────────
def _row(source, operation, *, native_id, title, url, location,
         posted_at, company_name=None, description="", workplace_raw=None,
         salary_text=None) -> dict:
    dt = parse_dt(posted_at)
    return {
        "source": source,
        "operation": operation,
        "native_id": (str(native_id) if native_id not in (None, "") else None),
        "title": (title or "").strip(),
        "url": url or "",
        "location": location or "",
        "posted_at": dt.isoformat() if dt else None,
        "company_name": (company_name or None),
        "description": description or "",
        "workplace_raw": (workplace_raw or None),
        "salary_text": (salary_text or None),
    }


def _loads(payload_bytes: bytes):
    return json.loads(payload_bytes.decode("utf-8", "replace"))


def _loads_safe(payload_bytes: bytes):
    """Tolerant JSON load — returns ``None`` on non-JSON (used by mixed HTML/JSON
    sources whose captures legitimately include HTML members)."""
    try:
        return json.loads(payload_bytes.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return None


# ── board parsers (attested-complete sources) ────────────────
def parse_greenhouse(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("jobs", []) or []:
        loc = (j.get("location") or {}).get("name", "") or ""
        meta = {m.get("name"): m.get("value")
                for m in (j.get("metadata") or []) if isinstance(m, dict)}
        salary = meta.get("Salary Range") or meta.get("Compensation")
        out.append(_row(
            "greenhouse", "board",
            native_id=j.get("id"),
            title=j.get("title", ""),
            url=j.get("absolute_url", ""),
            location=loc,
            posted_at=(j.get("first_published") or j.get("updated_at")),
            company_name=j.get("company_name"),
            description=strip_html(j.get("content")),
            salary_text=salary,
        ))
    return out


def parse_ashby(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("jobs", []) or []:
        if j.get("isListed") is False:
            continue
        loc = j.get("location", "") or ""
        sec = j.get("secondaryLocations") or []
        if sec:
            extra = ", ".join(s.get("location", "") for s in sec if s.get("location"))
            loc = f"{loc} / {extra}" if extra else loc
        comp = j.get("compensation") or {}
        salary = comp.get("compensationTierSummary") or \
            comp.get("scrapeableCompensationSalarySummary")
        out.append(_row(
            "ashby", "board",
            native_id=j.get("id"),
            title=j.get("title", ""),
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            location=loc,
            posted_at=j.get("publishedAt"),
            description=(j.get("descriptionPlain")
                        or strip_html(j.get("descriptionHtml"))),
            workplace_raw=j.get("workplaceType"),
            salary_text=salary,
        ))
    return out


def parse_lever(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        if not isinstance(j, dict):
            continue
        cats = j.get("categories") or {}
        rng = j.get("salaryRange") or {}
        salary = None
        if rng.get("min") is not None or rng.get("max") is not None:
            salary = (f"{rng.get('currency', '')} {rng.get('min')}"
                      f"-{rng.get('max')}").strip()
        out.append(_row(
            "lever", "board",
            native_id=j.get("id"),
            title=j.get("text", ""),
            url=j.get("hostedUrl") or j.get("applyUrl", ""),
            location=cats.get("location", "") or "",
            posted_at=j.get("createdAt"),
            description=(j.get("descriptionPlain")
                        or strip_html(j.get("description"))),
            workplace_raw=j.get("workplaceType"),
            salary_text=salary,
        ))
    return out


# ── search parser (keyword-sampled, capped — absence means nothing) ──
_WD_REQ_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _workday_req(jp: dict) -> str | None:
    """Extract the Workday requisition token (unique per company) from a row.

    ``bulletFields[0]`` is the clean req id (e.g. ``JR1980360``); the tail of
    ``externalPath`` (after the final ``_``) is the fallback.
    """
    bullets = jp.get("bulletFields") or []
    for b in bullets:
        b = str(b).strip()
        if b and _WD_REQ_RE.match(b) and any(c.isdigit() for c in b):
            return b
    path = jp.get("externalPath") or ""
    tail = path.rsplit("/", 1)[-1]
    if "_" in tail:
        cand = tail.rsplit("_", 1)[-1]
        if cand and any(c.isdigit() for c in cand):
            return cand
    return tail or None


def parse_workday(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, dict):
        return []
    base = ((env or {}).get("request") or {}).get("url") or ""
    # base is https://<host>/wday/cxs/<token>/<site> ; the human posting page drops
    # the /wday/cxs segment: https://<host>/<site><externalPath>.
    host = site = ""
    m = re.match(r"^(https?://[^/]+)/wday/cxs/[^/]+/([^/?]+)", base)
    if m:
        host, site = m.group(1), m.group(2)
    out = []
    for jp in data.get("jobPostings", []) or []:
        path = jp.get("externalPath") or ""
        url = f"{host}/{site}{path}" if (host and site and path) else path
        out.append(_row(
            "workday", "search",
            native_id=_workday_req(jp),
            title=jp.get("title", ""),
            url=url,
            location=jp.get("locationsText", "") or "",
            posted_at=None,  # search rows carry only a relative "Posted N days ago"
        ))
    return out


# ── scrape parsers (aggregators — opinion-grade, already normalized) ──
def parse_jobicy(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("jobs", []) or []:
        out.append(_row(
            "jobicy", "scrape",
            native_id=j.get("id"),
            title=j.get("jobTitle", ""),
            url=j.get("url", ""),
            location=j.get("jobGeo", "") or "remote",
            posted_at=j.get("pubDate"),
            company_name=j.get("companyName"),
            description=strip_html(j.get("jobDescription") or j.get("jobExcerpt")),
            workplace_raw="remote",
        ))
    return out


def parse_remoteok(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue  # the first element is a legal notice, not a job
        out.append(_row(
            "remoteok", "scrape",
            native_id=j.get("id"),
            title=j.get("position", ""),
            url=j.get("url") or j.get("apply_url", ""),
            location=j.get("location", "") or "remote",
            posted_at=(j.get("date") or j.get("epoch")),
            company_name=j.get("company"),
            description=strip_html(j.get("description")),
            workplace_raw="remote",
        ))
    return out


def parse_themuse(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("results", []) or []:
        locs = j.get("locations") or []
        loc = ", ".join(l.get("name", "") for l in locs if isinstance(l, dict))
        out.append(_row(
            "themuse", "scrape",
            native_id=j.get("id"),
            title=j.get("name", ""),
            url=(j.get("refs") or {}).get("landing_page", ""),
            location=loc,
            posted_at=j.get("publication_date"),
            company_name=(j.get("company") or {}).get("name"),
            description=strip_html(j.get("contents")),
        ))
    return out


# ── big-tech / SmartRecruiters search parsers (keyword-sampled, capped) ──
def parse_smartrecruiters(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("content", []) or []:
        loc = j.get("location") or {}
        loc_str = ", ".join(x for x in (loc.get("city"), loc.get("region"),
                                        loc.get("country")) if x)
        wp = "remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else None)
        out.append(_row(
            "smartrecruiters", "search",
            native_id=j.get("id"),
            title=j.get("name", ""),
            url=j.get("ref", "") or "",
            location=loc_str,
            posted_at=j.get("releasedDate"),
            company_name=(j.get("company") or {}).get("name"),
            workplace_raw=wp,
        ))
    return out


def parse_amazon(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("jobs", []) or []:
        path = j.get("job_path") or ""
        loc = j.get("normalized_location") or ", ".join(
            x for x in (j.get("city"), j.get("state"), j.get("country_code")) if x)
        desc = strip_html(" ".join(x for x in (
            j.get("description"), j.get("basic_qualifications"),
            j.get("preferred_qualifications")) if x))
        out.append(_row(
            "amazon", "search",
            native_id=j.get("id"),
            title=j.get("title", ""),
            url=(f"https://www.amazon.jobs{path}" if path else ""),
            location=loc,
            posted_at=_flex_date(j.get("posted_date")),
            company_name=j.get("company_name"),
            description=desc,
        ))
    return out


def parse_apple(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    # Apple captures include HTML handshake/CSRF members (which json-fail → []) and
    # the search-POST JSON where the postings live.
    data = _loads_safe(payload_bytes)
    if not isinstance(data, dict):
        return []
    results = ((data.get("res") or {}).get("searchResults")) or []
    out = []
    for j in results:
        pid = str(j.get("positionId") or "")
        locs = j.get("locations") or []
        loc = " / ".join(x.get("name", "") for x in locs
                         if isinstance(x, dict) and x.get("name"))
        country = " / ".join(x.get("countryName", "") for x in locs
                             if isinstance(x, dict) and x.get("countryName"))
        slug = j.get("transformedPostingTitle") or ""
        team = (j.get("team") or {}).get("teamCode", "")
        url = f"https://jobs.apple.com/en-us/details/{pid}/{slug}"
        if team:
            url += f"?team={team}"
        out.append(_row(
            "apple", "search",
            native_id=pid or None,
            title=j.get("postingTitle", ""),
            url=url if pid else "",
            location=f"{loc} {country}".strip(),
            posted_at=_flex_date(j.get("postingDate")),
            description=strip_html(j.get("jobSummary")),
            workplace_raw=("remote" if j.get("homeOffice") else None),
        ))
    return out


def parse_meta(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    # Meta captures include an HTML bootstrap member (json-fails → []) and the
    # Relay GraphQL JSON where the postings live.
    data = _loads_safe(payload_bytes)
    if not isinstance(data, dict):
        return []
    node = (data.get("data") or {}).get("job_search_with_featured_jobs") or {}
    jobs = node.get("all_jobs") or node.get("jobs") or []
    out = []
    for j in jobs:
        jid = str(j.get("id") or "")
        locs = j.get("locations") or []
        loc = " / ".join(x for x in locs if isinstance(x, str))
        out.append(_row(
            "meta", "search",
            native_id=jid or None,
            title=j.get("title", ""),
            url=(f"https://www.metacareers.com/jobs/{jid}/" if jid else ""),
            location=loc,
            posted_at=None,  # the GraphQL search returns no posted date
        ))
    return out


_PARSERS = {
    "greenhouse": parse_greenhouse,
    "ashby": parse_ashby,
    "lever": parse_lever,
    "workday": parse_workday,
    "smartrecruiters": parse_smartrecruiters,
    "amazon": parse_amazon,
    "apple": parse_apple,
    "meta": parse_meta,
    "jobicy": parse_jobicy,
    "remoteok": parse_remoteok,
    "themuse": parse_themuse,
}

# Sources whose parser is implemented (others capture raw but are not yet
# materialized — a parser can be added later and a rebuild picks them up).
SUPPORTED_SOURCES = frozenset(_PARSERS)


def parse_manifest(env: dict, payload_bytes: bytes | None) -> list[dict]:
    """Dispatch to the per-source parser; never raises (a bad payload → no rows).

    Group-attestation manifests and unparseable/absent payloads yield ``[]`` so the
    builder treats them as "observed nothing new", never an error.
    """
    if payload_bytes is None:
        return []
    if env.get("operation") == "group" or env.get("kind") == "group":
        return []
    parser = _PARSERS.get(env.get("source"))
    if parser is None:
        return []
    try:
        return parser(payload_bytes, env)
    except Exception:  # noqa: BLE001 — a malformed payload is never build-fatal
        return []
