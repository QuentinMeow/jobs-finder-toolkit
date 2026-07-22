"""Shared helpers for the job-search skill: HTTP, HTML->text, datetime, records.

Stdlib-only (plus PyYAML, already in the repo venv) so the skill runs on
`.venv/bin/python` without extra installs.
"""
from __future__ import annotations

import html
import json
import math
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "jobs-finder-skill/1.0 (personal job search; +https://github.com/)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTINL_RE = re.compile(r"\n{3,}")


# --------------------------------------------------------------------------- #
# HTTP
#
# Two layers: full-fidelity variants (``*_full``) return an ``HttpResult`` with the
# raw body BYTES + status + response headers + duration + error info WITHOUT raising
# (so a fetcher can capture the raw — including a failed/empty response — BEFORE it
# parses or re-raises); the classic string/JSON helpers are thin wrappers over them
# that preserve the old raise-on-failure contract so no existing caller breaks.
# --------------------------------------------------------------------------- #
@dataclass
class HttpResult:
    """One HTTP exchange, captured whole: bytes + metadata, success or failure.

    ``status`` is the HTTP status (or ``0`` when the transport failed before any
    response). ``body`` is the raw response bytes (an HTTP error response body is
    captured too — failure history is data). ``ok`` is True only for a 2xx.
    """
    url: str
    status: int
    body: bytes
    headers: dict
    duration_ms: int
    ok: bool
    error: str | None = None
    method: str = "GET"
    content_type: str | None = None


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _do_request(req: urllib.request.Request, timeout: int, method: str,
                retries: int) -> HttpResult:
    """Perform ``req`` (with retries) and return an ``HttpResult`` — never raises."""
    last: HttpResult | None = None
    for _attempt in range(retries + 1):
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                headers = dict(resp.headers.items()) if resp.headers else {}
                ctype = resp.headers.get_content_type() if resp.headers else None
                return HttpResult(req.full_url, getattr(resp, "status", 200) or 200,
                                  body, headers, _elapsed_ms(start), ok=True,
                                  error=None, method=method, content_type=ctype)
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:  # noqa: BLE001
                body = b""
            headers = dict(exc.headers.items()) if exc.headers else {}
            ctype = exc.headers.get_content_type() if exc.headers else None
            last = HttpResult(req.full_url, exc.code, body, headers,
                              _elapsed_ms(start), ok=False,
                              error=f"HTTP {exc.code} {exc.reason}", method=method,
                              content_type=ctype)
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            last = HttpResult(req.full_url, 0, b"", {}, _elapsed_ms(start),
                              ok=False, error=str(reason), method=method)
    return last  # type: ignore[return-value]  (retries >= 0 => always set)


def http_get_full(url: str, timeout: int = 25, headers: dict | None = None,
                  retries: int = 2) -> HttpResult:
    """GET ``url`` and return the whole exchange (bytes + metadata), never raising."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    if headers:
        hdrs.update(headers)
    return _do_request(urllib.request.Request(url, headers=hdrs), timeout, "GET",
                       retries)


def http_post_json_full(url: str, payload: dict, timeout: int = 25,
                        headers: dict | None = None,
                        retries: int = 2) -> HttpResult:
    """POST a JSON body and return the whole exchange (bytes + metadata), never raising."""
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json",
            "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    return _do_request(req, timeout, "POST", retries)


def http_get(url: str, timeout: int = 25, headers: dict | None = None,
             retries: int = 2) -> str:
    """GET a URL and return the decoded body. Raises on final failure."""
    r = http_get_full(url, timeout=timeout, headers=headers, retries=retries)
    if not r.ok:
        raise RuntimeError(f"GET failed for {url}: {r.error}")
    return r.body.decode("utf-8", "replace")


def http_get_json(url: str, timeout: int = 25, headers: dict | None = None):
    return json.loads(http_get(url, timeout=timeout, headers=headers))


def http_post_json(url: str, payload: dict, timeout: int = 25,
                   headers: dict | None = None, retries: int = 2):
    """POST a JSON body and return the parsed JSON response. Raises on failure.

    Used by ATS APIs that only accept POST search queries (e.g. Workday CXS).
    """
    r = http_post_json_full(url, payload, timeout=timeout, headers=headers,
                            retries=retries)
    if not r.ok:
        raise RuntimeError(f"POST failed for {url}: {r.error}")
    try:
        return json.loads(r.body.decode("utf-8", "replace"))
    except ValueError as exc:
        raise RuntimeError(f"POST failed for {url}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def strip_html(raw: str | None) -> str:
    """Turn (possibly entity-encoded) HTML into readable plain text."""
    if not raw:
        return ""
    text = html.unescape(raw)          # decode &lt; -> <  (Greenhouse double-encodes)
    text = _TAG_RE.sub(" ", text)      # drop tags
    text = html.unescape(text)         # decode remaining &amp; etc.
    text = _WS_RE.sub(" ", text)
    text = _MULTINL_RE.sub("\n\n", text)
    return text.strip()


def normalize(text: str | None) -> str:
    """Lowercase + normalize separators for phrase/keyword matching."""
    if not text:
        return ""
    t = text.lower()
    t = t.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[^a-z0-9\-+/.# ]+", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def term_matches(term: str, normalized_text: str) -> bool:
    """Word-boundary match for plain tokens, substring for multiword/symbol terms."""
    term = term.lower().strip()
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9]+", term):
        return re.search(rf"\b{re.escape(term)}\b", normalized_text) is not None
    return term in normalized_text


# --------------------------------------------------------------------------- #
# Datetime
# --------------------------------------------------------------------------- #
def parse_dt(value) -> datetime | None:
    """Parse ISO-8601, epoch seconds, epoch millis, or RFC-822 into aware UTC."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        secs = float(value)
        if secs > 1e12:      # milliseconds
            secs /= 1000.0
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        secs = float(s)
        if secs > 1e12:
            secs /= 1000.0
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_since(dt: datetime | None, now: datetime | None = None) -> float | None:
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 86400.0


# --------------------------------------------------------------------------- #
# Structured, source-native compensation (shared by every fetcher/aggregator
# that reads a STRUCTURED pay field off a board API — never an invented value).
# --------------------------------------------------------------------------- #
def provided_salary_range(low, high, *, currency=None, period=None,
                          source="source_api"):
    """Normalize an API-provided salary range without guessing missing bounds.

    Accepts a range ONLY when it carries an explicit currency AND an explicit
    period; either missing means ``None`` (stay unknown) — the same no-invented-
    currency/period safeguard used for JD-text compensation parsing, so a
    source-native structured range can never be more permissive than a JD-body
    one. Shared by the cross-company aggregators (Adzuna/JSearch/JobSpy) and any
    company-board fetcher with its own structured comp field (e.g. Ashby).
    """
    try:
        lo = float(low) if low is not None else None
        hi = float(high) if high is not None else None
    except (TypeError, ValueError):
        return None
    if lo is None and hi is None:
        return None
    if any(
        value is not None and (not math.isfinite(value) or value < 0)
        for value in (lo, hi)
    ):
        return None
    if lo is not None and hi is not None and lo > hi:
        return None
    currency_code = str(currency or "").strip().upper()
    if len(currency_code) != 3 or not currency_code.isalpha():
        return None
    raw_period = str(period or "").strip().lower()
    period_map = {
        "annual": "year",
        "annually": "year",
        "yearly": "year",
        "yr": "year",
        "monthly": "month",
        "weekly": "week",
        "daily": "day",
        "hourly": "hour",
        "hr": "hour",
    }
    normalized_period = period_map.get(raw_period, raw_period)
    if normalized_period not in {"year", "month", "week", "day", "hour"}:
        return None
    limit = 100_000 if normalized_period == "hour" else 100_000_000
    if any(value is not None and value > limit for value in (lo, hi)):
        return None
    return {
        "min": int(lo) if lo is not None and lo.is_integer() else lo,
        "max": int(hi) if hi is not None and hi.is_integer() else hi,
        "currency": currency_code,
        "period": normalized_period,
        "source": source,
        "provenance": {
            "tier": "market_benchmark",
            "provider": source,
            "confidence": "medium",
            "method": "structured_source_field",
        },
    }


_COMP_PERIOD_UNIT_RE = re.compile(r"(year|month|week|day|hour)", re.I)


def ashby_salary_range(compensation: dict | None) -> dict | None:
    """Normalize Ashby's explicit salary component without guessing.

    Some boards expose ``summaryComponents`` while others expose only the
    per-tier ``components`` list. Both carry the same source-native fields.
    Only a salary component with bounds, currency, and interval is accepted.
    """
    if not isinstance(compensation, dict):
        return None
    components = list(compensation.get("summaryComponents") or [])
    if not components:
        for tier in compensation.get("compensationTiers") or []:
            if isinstance(tier, dict):
                components.extend(tier.get("components") or [])
    for component in components:
        if not isinstance(component, dict):
            continue
        if str(component.get("compensationType") or "").lower() != "salary":
            continue
        match = _COMP_PERIOD_UNIT_RE.search(str(component.get("interval") or ""))
        parsed = provided_salary_range(
            component.get("minValue"),
            component.get("maxValue"),
            currency=component.get("currencyCode"),
            period=match.group(1).lower() if match else None,
            source="ashby_api",
        )
        if parsed:
            return parsed
    return None


# --------------------------------------------------------------------------- #
# Canonical record
# --------------------------------------------------------------------------- #
@dataclass
class JobPosting:
    source: str
    company: str
    title: str
    url: str
    location: str = ""
    remote: str = "unknown"          # remote | hybrid | onsite | unknown
    posted_at: datetime | None = None
    description: str = ""
    # enrichment (filled by the pipeline)
    age_days: float | None = None
    visa_label: str = "unclear"       # yes | no | unclear
    visa_hits: list[str] = field(default_factory=list)
    workplace: str = ""               # onsite | hybrid | remote | unknown
    sponsorship: str = ""             # likely | unlikely | unknown
    job_level: dict = field(default_factory=dict)
    required_yoe: dict = field(default_factory=dict)
    salary_range: dict | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    filter_assessments: dict = field(default_factory=dict)
    review_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        d["description"] = self.description[:400]  # keep output light
        return d
