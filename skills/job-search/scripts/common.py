"""Shared helpers for the job-search skill: HTTP, HTML->text, datetime, records.

Stdlib-only (plus PyYAML, already in the repo venv) so the skill runs on
`.venv/bin/python` without extra installs.
"""
from __future__ import annotations

import html
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache

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
# Partial-fetch reporting
#
# A fetcher that could not inspect part of what it set out to inspect must SAY SO
# rather than return a quietly shorter list. A total outage raises (the caller's
# error path already reports that); a PARTIAL outage still has real rows worth
# returning, so it records a one-line warning here and the run summary prints it
# alongside the source errors. Without this channel, "20 of 20 JD fetches got a
# 503" and "this employer has no matching jobs" are the same observation.
#
# Fetchers run on a thread pool, so the sink is lock-protected. Draining empties
# it, so a long-lived process (tests, --refilter) never re-reports a stale line.
# --------------------------------------------------------------------------- #
_SOURCE_WARNINGS: list[str] = []
_SOURCE_WARNINGS_LOCK = threading.Lock()
_SOURCE_WARNINGS_CAP = 500      # a caller that never drains cannot grow unbounded


def record_source_warning(message: str) -> None:
    """Record one 'I could not inspect all of this' line from inside a fetcher."""
    if not message:
        return
    with _SOURCE_WARNINGS_LOCK:
        if len(_SOURCE_WARNINGS) < _SOURCE_WARNINGS_CAP:
            _SOURCE_WARNINGS.append(message)


def drain_source_warnings() -> list[str]:
    """Return and clear the recorded partial-fetch warnings."""
    with _SOURCE_WARNINGS_LOCK:
        drained = list(_SOURCE_WARNINGS)
        _SOURCE_WARNINGS.clear()
    return drained


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def strip_html(raw: str | None, *, entity_encoded: bool = False) -> str:
    """Turn HTML into readable plain text. Tags are stripped BEFORE entities decode.

    ORDER MATTERS, and it is per-source. Every ATS/aggregator this skill reads
    hands us SINGLE-encoded HTML — real tags, with `<` inside prose written as
    the entity `&lt;` ("teams of &lt; 12", "p99 &lt; 200ms"). Unescaping first
    turns that prose entity into a real `<`, and ``_TAG_RE`` (``<[^>]+>``) then
    eats everything up to the next `>` — i.e. to the end of the enclosing
    element. A sponsorship denial sitting in that span disappears and the
    posting reads as visa-"unclear" instead of "no". So: strip tags on the
    markup as it arrived, then decode entities once, when nothing can eat them.

    ``entity_encoded=True`` is the ONE documented exception: Greenhouse
    ``content=true`` bodies arrive DOUBLE entity-encoded (``&lt;p&gt;...``), so
    that caller — and only that caller — asks for one extra decode up front to
    recover the real markup before the tags are stripped. Turning that decode on
    for a single-encoded source re-creates the bug; leaving it off for Greenhouse
    leaves literal ``<p>`` markup in the text.
    """
    if not raw:
        return ""
    text = raw
    if entity_encoded:
        text = html.unescape(text)     # &lt;p&gt; -> <p>  (Greenhouse only)
    text = _TAG_RE.sub(" ", text)      # drop tags while entities are still escaped
    text = html.unescape(text)         # now decode &lt; / &amp; in the prose
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


# A profile term and the text it is matched against must share ONE alphabet, and
# a hyphen must never be a different word than a space.
#
# ``normalize()`` runs on the TEXT; the term used to arrive raw, so any character
# ``normalize()`` folds away could never match (`fp&a analyst` became `fp a
# analyst` in the text and stayed `fp&a analyst` as the term — an include phrase
# that can never fire). Both sides now go through ``normalize()``.
#
# Separators are then EQUIVALENT, not literal: ``front end``, ``front-end`` and
# the Unicode-dash spellings ``normalize()`` already folds to ``-`` are one
# phrase, because hyphenation is a board's formatting choice and not a different
# occupation (issue #298: a profile listing BOTH `frontend engineer` and `front
# end engineer` still lost every `Front-End Engineer` posting to review). They are
# equivalent, never ELIDABLE: ``front end`` still does not match *frontend*, so a
# profile that wants the closed spelling lists it — as the shipped example
# profile already does for `fullstack` / `full stack`.
#
# This cuts BOTH ways and is meant to: the same widening makes an `exclude: data
# scientist` rule drop `Data-Scientist`, which is the same "hyphen is formatting"
# reading applied to the drop side.
_TERM_SEPARATOR_RE = re.compile(r"[ \-]+")


@lru_cache(maxsize=4096)
def _term_spec(term: str) -> tuple[str, re.Pattern | None]:
    """Normalize one profile term and compile (once) its bounded phrase pattern.

    Returns the normalized term plus its pattern, or ``(norm, None)`` when the
    term carries no matchable content. Cached because scoring calls this for every
    profile keyword on every posting.
    """
    norm = normalize(term)
    parts = [p for p in _TERM_SEPARATOR_RE.split(norm) if p]
    if not parts:
        return norm, None
    # Boundaries are asserted only where the phrase's own edge is alphanumeric, so
    # a symbol term such as ``c++`` or ``.net`` keeps matching on that edge.
    #
    # The right edge allows ``_INFLECTION``, the SAME allowance
    # ``bounded_phrase_re`` makes below and for the same reason: a multiword term
    # used to be matched as a bare SUBSTRING, which got plurals and gerunds for
    # free, and a strict boundary would silently lose them. Measured over the
    # corpus + test titles with the example profile, a strict right edge dropped
    # 11 include matches (`software engineer` stopped matching *Software
    # Engineering, Backend* / *Software Engineers, Platform*) and 2 exclude
    # matches (`data scientist` stopped matching *Data Scientists, Ads* — a
    # widening that LEAKS a posting the profile rejects). With the allowance the
    # change is additive in both directions: nothing that matched before stops.
    # `-al` (*Internal*), `-y` (*Directory*) and `-force` (*Salesforce*) are still
    # nothing like an inflection, so the `\b` protections the old single-token
    # path gave — `intern` is not *Internal*, `java` is not *javascript* — hold.
    prefix = r"(?<![a-z0-9])" if parts[0][0].isalnum() else ""
    suffix = _INFLECTION + r"(?![a-z0-9])" if parts[-1][-1].isalnum() else ""
    core = _TERM_SEPARATOR_RE.pattern.join(re.escape(p) for p in parts)
    return norm, re.compile(prefix + core + suffix)


def term_matches(term: str, normalized_text: str) -> bool:
    """Bounded, separator-insensitive phrase match for one profile term.

    ``term`` is a raw profile string (an include/exclude title phrase, a keyword,
    an AI-company signal); ``normalized_text`` has already been through
    ``normalize()``. Both sides are normalized, separators (space/hyphen) are
    interchangeable, and the match is bounded apart from a trailing English
    inflection — ``java`` does not match *javascript* and ``intern`` does not
    match *Internal*, but ``data scientist`` still matches *Data Scientists*.

    A handful of terms are BOTH an ordinary English word and a technology name.
    For those the bounded match is necessary but not sufficient: the occurrence
    must also read as the technology (``_AMBIGUOUS_TERM_GUARDS``). See
    ``_go_is_the_language`` for the one shipped case.
    """
    norm, pattern = _term_spec(term)
    if pattern is None:
        return False
    if pattern.search(normalized_text) is None:
        return False
    guard = _AMBIGUOUS_TERM_GUARDS.get(norm)
    return True if guard is None else guard(normalized_text)


# --------------------------------------------------------------------------- #
# Ambiguous terms: a word that is both ordinary English and a technology
# --------------------------------------------------------------------------- #
# Issue #279. ``go`` is the whole family in one token: a profile that means the
# programming language scored `strong: go` on "you'll **go** through a unified
# interview process" (a C++/Python/Java posting) and on three counts of
# "**go**-to-market" in a payments JD — and, because the same helper backs the
# title gate, `title include signal: go` rescued a financial-analyst posting the
# occupation lexicon had correctly rejected.
#
# The fix is context, not a new profile field: an occurrence counts as the
# technology only when the words around it read that way. Order matters, and the
# order is deliberate — the token AFTER the word disambiguates far better than the
# token before it, because "go <particle>" is always the English verb while "go
# <technical noun>" is always the language:
#
#   1. followed by a technical noun            -> the language   ("go developer")
#   2. followed by an English particle/idiom   -> ordinary English ("go to", "go live")
#   3. preceded by a technology frame          -> the language   ("written in go")
#   4. preceded by an English subject/idiom    -> ordinary English ("you'll go", "ready to go")
#   5. another technology name within the window -> the language ("go, python, rust")
#   6. otherwise                               -> NOT evidence
#
# Step 6 is the load-bearing default: silence is not evidence, so an English use
# that nobody listed still fails to score. Steps 2 and 4 exist only to beat step 5
# — without them "watch your code go live" would score on the neighbouring "code".
#
# Adding another ambiguous term (``r``, ``c``, ``swift``, ``rust``) means adding a
# guard here; the remaining design question — letting a PROFILE declare its own
# ambiguous terms — stays in
# ``tasks/0_backlog/2026-07-31-ambiguous-short-keywords-rank-on-english-prose``.
_WORD_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_VERSION_TOKEN_RE = re.compile(r"^\d+\.\d")

# Technical nouns that, following the word, name the language outright.
_GO_LANGUAGE_NEXT = frozenset("""
lang golang language languages developer developers dev devs engineer engineers
engineering programmer programmers programming code codebase codebases coding
service services microservice microservices backend api apis sdk sdks module
modules routine routines goroutines goroutine concurrency channels generics
compiler runtime toolchain binary binaries template templates stdlib standard
library libraries based application applications server servers tooling testing
experience expertise proficiency skills
""".split())

# Particles, prepositions and idiom heads that make it the English verb.
_GO_ENGLISH_NEXT = frozenset("""
to live through beyond above back forward ahead out into over up down on off
away home public global dark deep deeper wide big fast far further wrong right
first straight viral remote hybrid unnoticed unanswered smoothly well getter
get the a an all hand head toe no nowhere somewhere anywhere where when hunting
""".split())

# Frames that introduce a technology as their object.
_GO_LANGUAGE_PREV = frozenset("""
in with using use uses used write writes writing written wrote learn learns
learning learned know knows knowledge proficiency proficient expertise
experienced fluent fluency familiarity familiar prefer prefers preferred
preferably plus bonus language languages stack backend engineer engineers
developer developers sre including includes include especially primarily mainly
mostly mastery strong solid deep as like e.g. eg ie golang python java rust
kotlin scala ruby elixir erlang typescript javascript
""".split()) | {
    "written in", "rewritten in", "migrating to", "migrate to", "migrated to",
    "moving to", "move to", "moved to", "porting to", "port to", "ported to",
    "switch to", "switched to", "switching to", "introduction to", "new to",
    "exposure to", "transition to", "transitioning to", "such as", "familiar with",
}

# Subjects and idioms that make it the English verb.
_GO_ENGLISH_PREV = frozenset("""
we you i they he she it ll let lets things that which who must can cannot cant
could would should will wont may might never always often usually rarely no not
everyone everything customers users people teams candidates applicants
""".split()) | {
    "ready to", "able to", "want to", "wants to", "wanted to", "need to",
    "needs to", "needed to", "have to", "has to", "had to", "how to", "where to",
    "willing to", "going to", "used to", "eager to", "try to", "trying to",
    "tried to", "chance to", "time to", "place to", "allowed to", "let s",
    "here we", "on the", "it a", "we ll", "you ll", "they ll",
}

# Neighbouring technology names that make an unframed occurrence credible — a
# language list ("Go, Python, Rust") or a stack sentence, never a job word like
# "engineer" or "experience" that every JD carries.
_GO_CONTEXT = frozenset("""
golang goroutines python java javascript typescript rust kotlin scala ruby php
perl elixir erlang haskell clojure swift c++ c# node nodejs sql grpc protobuf
kubernetes docker terraform microservices microservice backend concurrency
compiler compiled runtime programming stdlib
""".split())
_GO_CONTEXT_WINDOW = 4


def _go_is_the_language(normalized_text: str) -> bool:
    """True when at least one ``go`` in the text reads as the Go language."""
    tokens = [t for t in (m.group(0).strip(".")
                          for m in _WORD_TOKEN_RE.finditer(normalized_text)) if t]
    for i, token in enumerate(tokens):
        if token != "go":
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        prev = tokens[i - 1] if i else ""
        prev_bigram = f"{tokens[i - 2]} {prev}" if i >= 2 else ""
        if nxt in _GO_LANGUAGE_NEXT or _VERSION_TOKEN_RE.match(nxt):
            return True
        if nxt in _GO_ENGLISH_NEXT:
            continue
        if prev in _GO_LANGUAGE_PREV or prev_bigram in _GO_LANGUAGE_PREV:
            return True
        if prev in _GO_ENGLISH_PREV or prev_bigram in _GO_ENGLISH_PREV:
            continue
        window = tokens[max(0, i - _GO_CONTEXT_WINDOW):i + _GO_CONTEXT_WINDOW + 1]
        if any(w in _GO_CONTEXT for w in window):
            return True
    return False


_AMBIGUOUS_TERM_GUARDS = {"go": _go_is_the_language}


# A lexicon phrase is matched BOUNDED — never as a bare substring. An unanchored
# ``phrase in text`` reads "intern" inside *Internal*, "director" inside *Active
# Directory*, "sales" inside *Salesforce*, "ote" inside "rem-ote-", "confirmed"
# inside "unconfirmed". The boundary is the toolkit's established bounded-phrase
# idiom (``job_metadata._bounded_phrase_matches``): refuse a match glued to a
# surrounding letter or digit.
#
# One deliberate allowance: a trailing English inflection. Substring matching got
# plurals and gerunds for free, and a strict boundary would silently lose them —
# "recruit" would stop matching *Recruiter* / *Recruiting Coordinator*, which is
# the entire reason "recruit" is in the skip list. So the right edge accepts a
# short inflectional suffix, which is still nothing like "-al" (*Internal*),
# "-y" (*Directory*) or "-force" (*Salesforce*).
#
# The boundary is asserted only where the phrase's own edge is alphanumeric, so a
# phrase such as ".ics" still matches inside "invite.ics".
#
# ``_term_spec`` above shares this allowance, for the same reason: profile
# include/exclude phrases were substrings too, and tightening them without it
# would silently stop matching *Software Engineers* and *Data Scientists*.
_INFLECTION = r"(?:s|es|d|ed|ing|er|ers)?"


@lru_cache(maxsize=4096)
def bounded_phrase_re(phrase: str) -> re.Pattern:
    """Compile (and cache) the bounded pattern for one lexicon phrase."""
    prefix = r"(?<![a-z0-9])" if phrase[:1].isalnum() else ""
    suffix = _INFLECTION + r"(?![a-z0-9])" if phrase[-1:].isalnum() else ""
    return re.compile(prefix + re.escape(phrase) + suffix, re.I)


def bounded_phrase_hit(text: str, phrases) -> bool:
    """True if any phrase occurs in ``text`` as a bounded phrase, not a substring."""
    if not text:
        return False
    return any(bounded_phrase_re(p).search(text) for p in phrases if p)


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
