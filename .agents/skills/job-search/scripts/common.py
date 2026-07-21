"""Shared helpers for the job-search skill: HTTP, HTML->text, datetime, records.

Stdlib-only (plus PyYAML, already in the repo venv) so the skill runs on
`.venv/bin/python` without extra installs.
"""
from __future__ import annotations

import html
import json
import re
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
# --------------------------------------------------------------------------- #
def http_get(url: str, timeout: int = 25, headers: dict | None = None,
             retries: int = 2) -> str:
    """GET a URL and return the decoded body. Raises on final failure."""
    last_err: Exception | None = None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_err = exc
    raise RuntimeError(f"GET failed for {url}: {last_err}")


def http_get_json(url: str, timeout: int = 25, headers: dict | None = None):
    return json.loads(http_get(url, timeout=timeout, headers=headers))


def http_post_json(url: str, payload: dict, timeout: int = 25,
                   headers: dict | None = None, retries: int = 2):
    """POST a JSON body and return the parsed JSON response. Raises on failure.

    Used by ATS APIs that only accept POST search queries (e.g. Workday CXS).
    """
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json",
            "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                ValueError) as exc:
            last_err = exc
    raise RuntimeError(f"POST failed for {url}: {last_err}")


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
