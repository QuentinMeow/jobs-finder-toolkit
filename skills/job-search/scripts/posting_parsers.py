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
    description (plain text), workplace_raw, salary_text, salary_range

``native_id`` is the platform identifier the identity layer keys on
(``posting_identity``); ``description`` is already ``strip_html``-flattened plain
text (the readable JD body used both for ``jd.md`` and as classifier input).

The normalizer is **versioned** (``NORMALIZER_VERSION``): the semantic
``content_hash`` used for JD change-detection is computed over normalized text
only, so a normalizer improvement is treated like a schema bump (recorded in the
entity; hashes are recomputed on rebuild by construction, never retroactively
"changed"). Entity decoding happens once, at PARSE time, where the source's
encoding is known: Greenhouse ``content=true`` bodies arrive DOUBLE
entity-encoded and are parsed with ``strip_html(..., entity_encoded=True)``;
every other source is single-encoded and is not. The normalizer therefore
receives text that is already flattened and already decoded, and only folds
whitespace/case — it must not re-run a tag strip over prose that legitimately
contains "&lt;" ("teams of < 12"), which would delete the rest of the line from
the hash and hide a real JD edit inside it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import urllib.parse

from common import ashby_salary_range, parse_dt, provided_salary_range, strip_html
from posting_identity import url_identifies_a_posting


# ── source-quality repair (shared with the live fetchers) ────
# Mojibake: text that was UTF-8 when it was written and got decoded as Latin-1 /
# CP1252 somewhere upstream, so "Φ" arrives as "Î¦" and "软" as "è½¯". RemoteOK
# serves rows already in that state, and no amount of correct decoding on OUR
# side recovers them — the damage is in the bytes we are handed. Re-encoding to
# the byte sequence the mangling implies and decoding it as UTF-8 does.
#
# The signature is a UTF-8 lead byte followed by a continuation byte, both read
# as single Latin-1 characters (U+00C2-U+00F4 then U+0080-U+00BF). Repair is
# attempted ONLY when that signature is present, is accepted only when the strict
# UTF-8 decode succeeds AND the signature count strictly drops, and is otherwise
# abandoned — so text that merely looks unusual is returned untouched. Text that
# mixes real non-Latin-1 characters with mojibake cannot be re-encoded at all and
# is likewise returned as-is: never mangle what we cannot prove is mangled.
_MOJIBAKE_RE = re.compile("[\u00c2-\u00f4][\u0080-\u00bf]")
_MOJIBAKE_MAX_ROUNDS = 3        # double-encoded text needs more than one pass


def repair_mojibake(text: str | None) -> str:
    """Return ``text`` with UTF-8-read-as-Latin-1 damage undone (or unchanged)."""
    out = text or ""
    for _round in range(_MOJIBAKE_MAX_ROUNDS):
        before = len(_MOJIBAKE_RE.findall(out))
        if not before:
            break
        repaired = None
        for codec in ("latin-1", "cp1252"):
            try:
                candidate = out.encode(codec).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if len(_MOJIBAKE_RE.findall(candidate)) < before:
                repaired = candidate
                break
        if repaired is None:
            break
        out = repaired
    return out


# RemoteOK builds a row's ``url`` from a slug of its title. A title with no
# ASCII in it slugs to nothing, and the URL degenerates to the bare listing root
# — the SAME string for every such row. Those rows cannot be opened as postings,
# they collide with each other on any URL-keyed dedupe, and they reached the
# human-review queue as garbled text behind a link that goes to a job board.
# ``apply_url`` (the employer's own link) is checked as the fallback it was
# always meant to be: the old ``url or apply_url`` never consulted it, because a
# generic listing root is a perfectly truthy string.
_REMOTEOK_LINK_FIELDS = ("url", "apply_url")


def remoteok_posting_link(row: dict) -> str:
    """The row's first link that names ONE posting; ``""`` when it has none."""
    for field in _REMOTEOK_LINK_FIELDS:
        candidate = str(row.get(field) or "").strip()
        if candidate and url_identifies_a_posting(candidate):
            return candidate
    return ""


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
# v3: entity decoding moved to parse time (per-source), and the normalizer no
# longer re-strips tags over already-flattened text — see the module docstring.
NORMALIZER_VERSION = 3

_WS_RE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Normalize already-flattened JD text for hashing: collapse whitespace, lowercase.

    The input is a parser ``description`` — ``common.strip_html`` output, so tags
    are gone and entities are decoded. This lowercases and collapses ALL
    whitespace (including newlines) so trivial reflowing does not read as a
    content change, and does nothing else: a second tag strip here would eat from
    a literal "<" in JD prose to the next ">", so an edit inside that span would
    not change the hash.
    """
    return _WS_RE.sub(" ", text or "").strip().lower()


def content_hash(text: str | None) -> str:
    """Semantic content hash of flattened JD text — sha256 over the normalized text."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


# ── row helper ───────────────────────────────────────────────
def _row(source, operation, *, native_id, title, url, location,
         posted_at, company_name=None, description="", workplace_raw=None,
         salary_text=None, salary_range=None) -> dict:
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
        "salary_range": (salary_range or None),
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
            # The one double-entity-encoded source in the toolkit (see strip_html).
            description=strip_html(j.get("content"), entity_encoded=True),
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
        postal = ((j.get("address") or {}).get("postalAddress") or {})
        country = (postal.get("addressCountry") or "").strip()
        region = (postal.get("addressRegion") or "").strip()
        if (country and country.casefold() != "united states"
                and country.casefold() not in loc.casefold()):
            suffix = [x for x in (region, country)
                      if x.casefold() not in loc.casefold()]
            loc = ", ".join(x for x in (loc, *suffix) if x)
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
            salary_range=ashby_salary_range(comp),
        ))
    return out


_LEVER_COUNTRY_NAMES = {
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "CA": "Canada",
    "IN": "India",
    "SG": "Singapore",
    "AU": "Australia",
    "IE": "Ireland",
    "NL": "Netherlands",
    "ES": "Spain",
    "PT": "Portugal",
    "PL": "Poland",
    "IT": "Italy",
    "BR": "Brazil",
    "MX": "Mexico",
    "JP": "Japan",
    "KR": "South Korea",
    "CN": "China",
    "IL": "Israel",
    "CH": "Switzerland",
    "SE": "Sweden",
    "DK": "Denmark",
    "RO": "Romania",
    "PH": "Philippines",
    "AR": "Argentina",
    "CO": "Colombia",
    "NG": "Nigeria",
    "KE": "Kenya",
    "NZ": "New Zealand",
    "VN": "Vietnam",
    "ID": "Indonesia",
    "MY": "Malaysia",
    "AE": "United Arab Emirates",
    "GR": "Greece",
    "UA": "Ukraine",
    "TR": "Turkey",
    "EG": "Egypt",
    "ZA": "South Africa",
    "CZ": "Czech Republic",
    "RS": "Serbia",
    "FI": "Finland",
    "AT": "Austria",
    "EE": "Estonia",
    "LV": "Latvia",
    "LT": "Lithuania",
    "QA": "Qatar",
    "SA": "Saudi Arabia",
    "IS": "Iceland",
    "NO": "Norway",
    "HU": "Hungary",
    "HK": "Hong Kong",
    "CL": "Chile",
    "CR": "Costa Rica",
    "TW": "Taiwan",
    "TH": "Thailand",
    "LU": "Luxembourg",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "HR": "Croatia",
    "BG": "Bulgaria",
    "BE": "Belgium",
    "PK": "Pakistan",
    "BD": "Bangladesh",
    "LK": "Sri Lanka",
    "UY": "Uruguay",
    "EC": "Ecuador",
    "GT": "Guatemala",
    "PA": "Panama",
    "KW": "Kuwait",
    "BH": "Bahrain",
}


def parse_lever(payload_bytes: bytes, env: dict | None = None) -> list[dict]:
    data = _loads(payload_bytes)
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        if not isinstance(j, dict):
            continue
        cats = j.get("categories") or {}
        loc = cats.get("location", "") or ""
        all_locs = [x.strip() for x in (cats.get("allLocations") or [])
                    if isinstance(x, str) and x.strip()]
        if len(all_locs) > 1:
            loc = " / ".join(dict.fromkeys(all_locs))
        country = _LEVER_COUNTRY_NAMES.get(
            str(j.get("country") or "").strip().upper())
        if country and country.casefold() not in loc.casefold():
            loc = f"{loc}, {country}" if loc else country
        rng = j.get("salaryRange") or {}
        salary = None
        salary_range = None
        if rng.get("min") is not None or rng.get("max") is not None:
            salary = (f"{rng.get('currency', '')} {rng.get('min')}"
                      f"-{rng.get('max')}").strip()
            salary_range = provided_salary_range(
                rng.get("min"),
                rng.get("max"),
                currency=rng.get("currency"),
                period=rng.get("interval"),
                source="lever_api",
            )
        out.append(_row(
            "lever", "board",
            native_id=j.get("id"),
            title=j.get("text", ""),
            url=j.get("hostedUrl") or j.get("applyUrl", ""),
            location=loc,
            posted_at=j.get("createdAt"),
            description="\n\n".join(part for part in (
                j.get("descriptionPlain") or strip_html(j.get("description")),
                j.get("additionalPlain") or strip_html(j.get("additional")),
            ) if part),
            workplace_raw=j.get("workplaceType"),
            salary_text=salary,
            salary_range=salary_range,
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
        link = remoteok_posting_link(j)
        if not link:
            # No link that names one posting: nothing downstream can open it, and
            # every such row carries the SAME generic listing root, so any
            # URL-keyed dedupe folds unrelated jobs together. The raw payload
            # still holds the row verbatim — only materialization is skipped.
            continue
        out.append(_row(
            "remoteok", "scrape",
            native_id=j.get("id"),
            title=repair_mojibake(j.get("position", "")),
            url=link,
            location=repair_mojibake(j.get("location", "")) or "remote",
            posted_at=(j.get("date") or j.get("epoch")),
            company_name=repair_mojibake(j.get("company")) or None,
            description=repair_mojibake(strip_html(j.get("description"))),
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
        loc_parts = []
        for x in locs:
            if not isinstance(x, dict) or not x.get("name"):
                continue
            name = x["name"]
            country = x.get("countryName")
            loc_parts.append(f"{name}, {country}" if country else name)
        loc = " / ".join(loc_parts)
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
            location=loc,
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
