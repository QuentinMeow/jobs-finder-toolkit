"""Pure helpers for structured, human-readable job metadata (schema v4).

An application ``meta.yaml`` is something a person reads to decide "what is this
posting and should I apply?". The per-posting facts are deliberately flat and
small:

``job_level``
    ``{normalized, min, max, confidence, source}`` — a plain-English seniority
    word plus an approximate Google-equivalent ladder range (floats, because the
    cross-company mapping is an estimate).
``required_yoe``
    ``{min, max, confidence, source}`` — years of experience the posting asks
    for (``min``/``max`` may be ``null``).
``salary_range``
    ``{min, max, confidence, source}`` or ``None`` — posted pay, assumed USD/year.
``workplace``
    one word — ``onsite`` / ``hybrid`` / ``remote`` / ``unknown`` — the work
    arrangement (separate from the ``location`` city string).
``sponsorship``
    one word — ``likely`` / ``unlikely`` / ``unknown`` — a heuristic read of
    whether the posting offers visa sponsorship (advisory; always confirm).

Every application uses a ``jobs:`` list (one entry per posting), even a
single-role application (a one-element list). There is no per-field provenance,
no per-field dates, and no per-field links: the only dates are the top-level
``research_date`` (search date) and each posting's ``posted_date``. The
company-scope ``channel`` field (how the lead was found) is intentionally named
apart from the per-fact ``source`` (provenance) so the two never collide.

This module is config-free and stdlib-only (plus PyYAML). The optional
``company-levels.yaml`` reference cache — a separately maintained, sourced level
database — is consumed here for leveling; it keeps its own richer provenance
shape, which is intentionally NOT copied into the human-facing ``meta.yaml``.
"""

from __future__ import annotations

import hashlib
import re
import math
from datetime import date
from pathlib import Path
from typing import Any

import yaml

try:  # Sibling shared module; layout is pure (stdlib + yaml), so no import cycle.
    from .layout import status_label_for_dir
    from .location import assess_location
except ImportError:  # Direct top-level import (tests + vendored self-contained skills).
    from layout import status_label_for_dir
    from location import assess_location

# The per-posting structured (mapping) fields, in display order. These carry the
# nested ``{min, max, confidence, source}`` shape (job_level adds ``normalized``).
METADATA_FIELDS = (
    "job_level",
    "required_yoe",
    "salary_range",
)
# Everything ``analyze_job_metadata`` derives for one posting, in insert/display
# order: the two scalar reads first (workplace, sponsorship), then the structured
# mapping fields. This is what the formatting-preserving editor may insert.
POSTING_METADATA_FIELDS = (
    "workplace",
    "sponsorship",
    *METADATA_FIELDS,
)
APPLICATION_SCHEMA_VERSION = 4

WORKPLACE_VALUES = {"onsite", "hybrid", "remote", "unknown"}
SPONSORSHIP_VALUES = {"likely", "unlikely", "unknown"}

# Per-job status values (exactly the status-folder labels), ordered by ROLLUP
# PRECEDENCE — highest first. ``derive_status`` walks this order and returns the
# first tier that any job occupies, so one interviewing role lifts the whole
# application to ``in_progress`` even if its siblings were rejected:
#   in_progress > applied > drafted > rejected > ignored
STATUS_VALUES = ("in_progress", "applied", "drafted", "rejected", "ignored")


def derive_status(jobs: list[dict]) -> str:
    """Roll a ``jobs`` list up to one overall status by ``STATUS_VALUES`` precedence.

    The per-job ``status`` fields are the fine-grained source of truth; the overall
    status (and thus the status folder an application belongs in) is DERIVED as the
    highest-precedence per-job status. Raises ``ValueError`` on an empty list or any
    job whose ``status`` is missing or not a known ``STATUS_VALUES`` label — the
    validator guarantees valid per-job statuses upstream, so a raise here flags a
    caller that skipped validation rather than a routine data condition.
    """
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("derive_status requires a non-empty jobs list")
    present: set[str] = set()
    for index, job in enumerate(jobs):
        status = job.get("status") if isinstance(job, dict) else None
        if status not in STATUS_VALUES:
            raise ValueError(
                f"jobs[{index}].status must be one of {', '.join(STATUS_VALUES)}; "
                f"got {status!r}"
            )
        present.add(status)
    for candidate in STATUS_VALUES:
        if candidate in present:
            return candidate
    raise ValueError("no derivable status")  # unreachable: every status is valid

NORMALIZED_LEVELS = {
    "intern",
    "entry",
    "mid",
    "senior",
    "staff",
    "senior_staff",
    "principal",
    "distinguished",
    "unknown",
}

CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}

# Generic fallback used only when no company-specific reference matches. Decimal
# bounds communicate approximate equivalence without pretending that companies'
# ladders align exactly at integer boundaries.
GENERIC_GOOGLE_EQUIVALENTS = {
    "intern": {"min": 2.0, "max": 2.8},
    "entry": {"min": 3.0, "max": 3.8},
    "mid": {"min": 4.0, "max": 4.8},
    "senior": {"min": 5.0, "max": 5.8},
    "staff": {"min": 6.0, "max": 6.8},
    "senior_staff": {"min": 7.0, "max": 7.8},
    "principal": {"min": 8.0, "max": 8.8},
    "distinguished": {"min": 9.0, "max": 10.0},
    "unknown": {"min": None, "max": None},
}

# ---------------------------------------------------------------------------
# Company-levels reference cache (a separate, sourced level database).
#
# The cache keeps richer provenance so its facts stay auditable; this section
# loads and looks up that cache. The values we surface into the human-facing
# meta.yaml are reduced to the flat schema above.
# ---------------------------------------------------------------------------
SOURCE_TIERS = (
    "live_jd",
    "employer_official",
    "market_benchmark",
    "generic_heuristic",
)
TIER_RANK = {tier: index for index, tier in enumerate(SOURCE_TIERS)}
# Map a fact's flat ``source`` label (the schema enum the extractor emits)
# to a provenance tier, used when a fact carries no explicit ``tier``.
SOURCE_TIER_MAP = {
    "job_description": "live_jd",
    "company_reference": "employer_official",
    "title": "generic_heuristic",
    "required_yoe": "generic_heuristic",
}

_WS_RE = re.compile(r"\s+")
_RANGE_SEP = r"(?:-|–|—|to|through)"
_YOE_RANGE_RE = re.compile(
    rf"\b(\d{{1,2}}(?:\.\d+)?)\s*{_RANGE_SEP}\s*"
    r"(\d{1,2}(?:\.\d+)?)\s*(?:\+?\s*)?(?:years?|yrs?\.?)"
    r"(?:\s+(?:of\s+)?(?:professional\s+)?experience)?",
    re.I,
)
_YOE_MIN_PATTERNS = [
    re.compile(
        r"\b(?:minimum|min\.?)\s*(?:of\s*)?(\d{1,2}(?:\.\d+)?)\s*\+?\s*"
        r"(?:years?|yrs?\.?)(?:\s+(?:of\s+)?(?:professional\s+)?experience)?",
        re.I,
    ),
    re.compile(
        r"\bat least\s+(\d{1,2}(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?\.?)",
        re.I,
    ),
    re.compile(
        r"\b(\d{1,2}(?:\.\d+)?)\+\s*(?:years?|yrs?\.?)"
        r"(?:\s+(?:of\s+)?(?:[\w-]+\s+){0,4}experience)?",
        re.I,
    ),
    re.compile(
        r"\b(\d{1,2}(?:\.\d+)?)\s*(?:or more)\s*(?:years?|yrs?\.?)",
        re.I,
    ),
    re.compile(
        r"\b(\d{1,2}(?:\.\d+)?)\s*(?:years?|yrs?\.?)(?:['’]\s*)?\s+"
        r"(?:of\s+)?"
        r"(?:[\w-]+\s+){0,3}experience",
        re.I,
    ),
]
_PREFERRED_YOE_RE = re.compile(
    r"\b(preferred|ideally|nice[- ]to[- ]have|bonus|a plus|desired|optional)\b",
    re.I,
)
_REQUIRED_YOE_RE = re.compile(
    r"\b(required|requirements?|must|minimum|at least|should have|you(?:'ll| will)? "
    r"(?:need|have)|qualifications?)\b",
    re.I,
)
_GENERAL_EXPERIENCE_RE = re.compile(
    r"\b(professional|industry|work|relevant|software engineering|engineering)\s+"
    r"experience\b",
    re.I,
)

_AMOUNT = (
    r"(?:(USD|CAD|EUR|GBP)\s*)?([$€£])?\s*"
    r"(\d{1,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?)\s*([kK])?"
)
_PER_AMOUNT_PERIOD = (
    r"(?:\s*(per\s+(?:year|month|week|day|hour)|"
    r"annually|monthly|weekly|daily|hourly|/(?:year|month|week|day|hour|hr)))?"
)
_MONEY_RANGE_RE = re.compile(
    rf"{_AMOUNT}{_PER_AMOUNT_PERIOD}\s*{_RANGE_SEP}\s*"
    rf"{_AMOUNT}{_PER_AMOUNT_PERIOD}",
    re.I,
)
_TOTAL_TERMS = (
    "total compensation",
    "total annual compensation",
    "total cash compensation",
    "total comp",
    "on-target earnings",
    "on target earnings",
    "ote",
)
_SALARY_TERMS = (
    "base salary",
    "base pay",
    "salary range",
    "pay range",
    "annual salary",
    "annual base",
    "base compensation",
)

# "Member of Technical Staff" (MTS) is a role-family name, not a Staff-level (L6)
# signal — the trailing "Staff" must not trip the bare ``\bstaff\b`` rule below.
# Neutralized before the level rules run, so "Member of Technical Staff" reads as
# unknown while "Senior Member of Technical Staff" still resolves via "senior".
_MTS_NEUTRALIZE_RE = re.compile(
    r"\bmembers?\s+of\s+(?:the\s+)?technical\s+staff\b", re.I)

_LEVEL_RULES = [
    ("distinguished", re.compile(r"\b(distinguished|fellow)\b", re.I)),
    ("senior_staff", re.compile(r"\b(senior staff|sr\.?\s+staff)\b", re.I)),
    ("principal", re.compile(r"\bprincipal\b", re.I)),
    ("staff", re.compile(r"\bstaff\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|software engineer iii|swe iii)\b", re.I)),
    ("entry", re.compile(
        r"\b(intern|new grad(?:uate)?|entry[- ]level|junior|jr\.?|associate|"
        r"software engineer i|swe i)\b",
        re.I,
    )),
    ("mid", re.compile(
        r"\b(mid[- ]level|intermediate|software engineer ii|swe ii|engineer ii)\b",
        re.I,
    )),
]


def _clean(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "").strip().lower())


def _company_key(value: Any) -> str:
    key = _clean(value)
    key = re.sub(
        r"\b(?:incorporated|inc|llc|ltd|corp|corporation|company)\b\.?",
        " ",
        key,
    )
    key = re.sub(r"[^a-z0-9]+", " ", key)
    return _WS_RE.sub(" ", key).strip()


def _number(value: str | float | int) -> int | float:
    n = float(value)
    return int(n) if n.is_integer() else n


def _num_or_none(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return _number(value)
    except (TypeError, ValueError):
        return None


def _money(value: str, suffix: str | None) -> int:
    amount = float(value.replace(",", ""))
    if suffix:
        amount *= 1000
    return int(round(amount))


def _source_text(value: str | None) -> str:
    """Undo common Markdown escapes before running JD regexes."""
    return re.sub(r"\\([+$])", r"\1", value or "")


def source_to_tier(source: str | None) -> str | None:
    """Map a fact's ``source`` label to a reference-cache precedence tier."""
    if not source:
        return None
    value = str(source).strip().lower()
    if value in SOURCE_TIERS:
        return value
    if value.endswith("_api"):
        return "market_benchmark"
    return SOURCE_TIER_MAP.get(value)


def normalize_provenance(
    value: Any,
    *,
    fact_source: str | None = None,
    defaults: dict | None = None,
) -> dict:
    """Return a normalized provenance mapping for the reference cache."""
    provenance = dict(value) if isinstance(value, dict) else {}
    for key, default in (defaults or {}).items():
        if default is not None and provenance.get(key) in (None, ""):
            provenance[key] = default
    tier = provenance.get("tier") or source_to_tier(fact_source)
    if tier:
        provenance["tier"] = tier
    if not provenance.get("confidence"):
        provenance["confidence"] = "unknown"
    return provenance


def _candidate_tier(fact: dict | None) -> str | None:
    if not isinstance(fact, dict):
        return None
    provenance = normalize_provenance(
        fact.get("provenance"), fact_source=fact.get("source"))
    return provenance.get("tier")


def _candidate_date(fact: dict | None) -> int:
    if not isinstance(fact, dict):
        return 0
    raw = normalize_provenance(
        fact.get("provenance"), fact_source=fact.get("source")
    ).get("retrieved_at")
    if not raw:
        return 0
    try:
        return date.fromisoformat(str(raw).strip()[:10]).toordinal()
    except ValueError:
        return 0


def _manual_override(fact: dict | None) -> bool:
    if not isinstance(fact, dict):
        return False
    provenance = fact.get("provenance")
    return bool(
        isinstance(provenance, dict)
        and provenance.get("manual_override") is True
    )


def _candidate_has_value(fact: dict | None) -> bool:
    """Whether a fact mapping carries data, not only metadata."""
    if not isinstance(fact, dict):
        return False
    if "min" in fact or "max" in fact or "bands" in fact:
        if fact.get("min") is not None or fact.get("max") is not None:
            return True
        bands = fact.get("bands")
        return bool(
            isinstance(bands, list)
            and any(_candidate_has_value(band) for band in bands)
        )
    return True


def pick_candidate(*facts: dict | None) -> dict | None:
    """Resolve reference-cache facts by manual override, tier, then freshness."""
    candidates = [
        fact for fact in facts
        if _candidate_has_value(fact) or _manual_override(fact)
    ]
    if not candidates:
        return None
    return min(
        enumerate(candidates),
        key=lambda item: (
            0 if _manual_override(item[1]) else 1,
            TIER_RANK.get(_candidate_tier(item[1]) or "", len(TIER_RANK)),
            -_candidate_date(item[1]),
            item[0],
        ),
    )[1]


def _reference_provenance(company: dict, *, benchmark_first: bool) -> dict:
    sources = [str(url) for url in (company.get("sources") or []) if url]
    benchmark = next((url for url in sources if "levels.fyi" in url.lower()), "")
    official = next((url for url in sources if "levels.fyi" not in url.lower()), "")
    if benchmark_first and benchmark:
        tier, provider, url, confidence = (
            "market_benchmark", "levels_fyi", benchmark, "medium")
    elif official:
        tier, provider, url, confidence = (
            "employer_official", "employer_careers", official, "high")
    elif benchmark:
        tier, provider, url, confidence = (
            "market_benchmark", "levels_fyi", benchmark, "medium")
    else:
        tier, provider, url, confidence = (
            "employer_official", "company_reference", "", "unknown")
    return {
        "tier": tier,
        "provider": provider,
        "url": url,
        "retrieved_at": str(company.get("last_verified") or ""),
        "confidence": confidence,
    }


def _companies(reference: dict) -> list[dict]:
    raw = reference.get("companies") or []
    if isinstance(raw, dict):
        return [
            {"name": name, **(entry if isinstance(entry, dict) else {})}
            for name, entry in raw.items()
        ]
    return [entry for entry in raw if isinstance(entry, dict)]


def normalize_company_levels(data: dict) -> dict:
    """Normalize a company cache to the provenance-aware v2 shape in memory."""
    out = dict(data)
    normalized_companies = []
    for raw_company in _companies(out):
        company = dict(raw_company)
        levels = []
        for raw_level in company.get("levels") or []:
            if not isinstance(raw_level, dict):
                continue
            level = dict(raw_level)
            google = level.get("google_equivalent")
            if isinstance(google, dict):
                google = dict(google)
                google["provenance"] = normalize_provenance(
                    google.get("provenance"),
                    defaults=_reference_provenance(
                        company, benchmark_first=True),
                )
                level["google_equivalent"] = google
            required = level.get("required_yoe")
            if isinstance(required, dict):
                required = dict(required)
                required["provenance"] = normalize_provenance(
                    required.get("provenance"),
                    defaults=_reference_provenance(
                        company, benchmark_first=False),
                )
                level["required_yoe"] = required
            compensation = dict(level.get("compensation") or {})
            for field in (
                "salary_range",
                "stock_range",
                "bonus_range",
                "total_compensation_range",
            ):
                value = compensation.get(field)
                if isinstance(value, dict):
                    value = dict(value)
                    value["provenance"] = normalize_provenance(
                        value.get("provenance"),
                        defaults=_reference_provenance(
                            company, benchmark_first=(field == "total_compensation_range")),
                    )
                    bands = []
                    for raw_band in value.get("bands") or []:
                        if not isinstance(raw_band, dict):
                            continue
                        band = dict(raw_band)
                        band["provenance"] = normalize_provenance(
                            band.get("provenance"),
                            defaults=value["provenance"],
                        )
                        band.setdefault("source", value.get("source", "company_reference"))
                        bands.append(band)
                    if bands:
                        value["bands"] = bands
                    compensation[field] = value
            if compensation:
                level["compensation"] = compensation
            levels.append(level)
        company["levels"] = levels
        normalized_companies.append(company)
    out["companies"] = normalized_companies
    out["schema_version"] = 2
    out.setdefault("tier_precedence", list(SOURCE_TIERS))
    return out


def load_company_levels(path: str | Path | None) -> dict:
    """Load and normalize the optional reusable company-level reference cache."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return normalize_company_levels(data) if isinstance(data, dict) else {}


def lookup_company_level(company: str, title: str, reference: dict) -> tuple[dict, dict] | None:
    """Find the longest matching company-specific level title pattern."""
    company_key = _company_key(company)
    title_key = _clean(title)
    best: tuple[int, dict, dict] | None = None
    for company_entry in _companies(reference):
        names = [company_entry.get("name"), *(company_entry.get("aliases") or [])]
        if company_key not in {_company_key(name) for name in names if name}:
            continue
        for level in company_entry.get("levels") or []:
            if not isinstance(level, dict):
                continue
            patterns = [
                level.get("name"),
                *(level.get("aliases") or []),
                *(level.get("title_patterns") or []),
            ]
            for pattern in patterns:
                key = _clean(pattern)
                if key and re.search(rf"\b{re.escape(key)}\b", title_key):
                    score = len(key)
                    if best is None or score > best[0]:
                        best = (score, company_entry, level)
    return (best[1], best[2]) if best else None


# ---------------------------------------------------------------------------
# JD text extraction (years of experience, pay, seniority).
# ---------------------------------------------------------------------------
def _yoe_match_context(blob: str, start: int, end: int) -> tuple[str, str, str]:
    line_start = max(blob.rfind("\n", 0, start), blob.rfind(".", 0, start)) + 1
    newline_end = blob.find("\n", end)
    sentence_end = blob.find(".", end)
    ends = [value for value in (newline_end, sentence_end) if value >= 0]
    line_end = min(ends) if ends else len(blob)
    local = blob[line_start:line_end]
    before = blob[max(line_start, start - 100):start]
    after = blob[end:min(line_end, end + 100)]
    return local, before, after


def _yoe_candidate_confidence(blob: str, match: re.Match) -> tuple[str, str] | None:
    """Classify a YOE match as required/general or contextual.

    Preferred/nice-to-have statements are excluded from ``required_yoe``. Tool- or
    domain-specific experience is retained as medium-confidence context only, so it
    can be displayed but cannot hard-filter a job-search result.
    """
    local, before, after = _yoe_match_context(blob, match.start(), match.end())
    preference_window = f"{before[-60:]} {match.group(0)} {after[:30]}"
    if _PREFERRED_YOE_RE.search(preference_window):
        return None
    matched = match.group(0)
    match_context = f"{matched} {after[:80]}"
    contextual = bool(re.search(
        r"\byears?(?:\s+of\s+experience)?\s+"
        r"(?:working\s+with|using|in)\s+"
        r"(?!software engineering\b|engineering\b|industry\b|professional\b)|"
        r"\byears?\s+(?:of\s+)?(?!professional\b|industry\b|work\b|relevant\b|"
        r"software engineering\b|engineering\b)[a-z0-9+#.-]+\s+experience\b",
        match_context,
        re.I,
    ))
    requirement_window = f"{before[-80:]} {matched} {after[:30]}"
    required_signal = bool(_REQUIRED_YOE_RE.search(requirement_window))
    general = bool(_GENERAL_EXPERIENCE_RE.search(match_context))
    first_line_end = blob.find("\n")
    title_signal = first_line_end >= 0 and match.start() < first_line_end
    confidence = "high" if (required_signal or general or title_signal) and not contextual \
        else "medium"
    return confidence, "contextual" if contextual else "required"


def extract_required_yoe_details(text: str | None) -> dict:
    """Extract required YOE with requirement kind and confidence.

    High-confidence general requirements take precedence over contextual
    technology/domain requirements. Within one confidence class, the greatest
    lower bound wins; a finite upper bound is retained only from that same range.
    """
    blob = _source_text(text)
    candidates: list[tuple[float, float | None, str, str, str]] = []
    range_spans: list[tuple[int, int]] = []
    for match in _YOE_RANGE_RE.finditer(blob):
        low = float(match.group(1))
        high = float(match.group(2))
        classified = _yoe_candidate_confidence(blob, match)
        if 0 <= low <= high <= 50 and classified:
            confidence, kind = classified
            candidates.append((low, high, match.group(0), confidence, kind))
            range_spans.append(match.span())
    for pattern in _YOE_MIN_PATTERNS:
        for match in pattern.finditer(blob):
            if any(start <= match.start() < end for start, end in range_spans):
                continue
            low = float(match.group(1))
            classified = _yoe_candidate_confidence(blob, match)
            if 0 <= low <= 50 and classified:
                confidence, kind = classified
                candidates.append((low, None, match.group(0), confidence, kind))

    if not candidates:
        return {
            "min": None,
            "max": None,
            "source": "not_stated",
            "confidence": "unknown",
            "requirement_kind": "not_stated",
        }

    strongest = "high" if any(item[3] == "high" for item in candidates) else "medium"
    eligible = [item for item in candidates if item[3] == strongest]
    greatest = max(item[0] for item in eligible)
    same_min = [item for item in eligible if item[0] == greatest]
    chosen = next((item for item in same_min if item[1] is not None), same_min[0])
    return {
        "min": _number(chosen[0]),
        "max": _number(chosen[1]) if chosen[1] is not None else None,
        "source": "job_description",
        "confidence": chosen[3],
        "requirement_kind": chosen[4],
    }


def extract_required_yoe(text: str | None) -> dict:
    """Compatibility view of required YOE without extraction diagnostics."""
    details = extract_required_yoe_details(text)
    return {key: details[key] for key in ("min", "max", "source")}


def assess_required_yoe(text: str | None, *, cap: int | float | None = None) -> dict:
    """Canonical tri-state required-YOE assessment.

    One shared decision consumed by both production hard-filtering
    (``scoring.experience_ok``) and the variant corpus/audit
    (``filter_variants``), so the two can never drift:

    - only a HIGH-confidence general requirement is decisive;
    - with a ``cap`` a decisive minimum above the cap is ``no_match``;
    - any other decisive requirement is ``match``;
    - preferred / tool-specific / contextual / missing (non-high-confidence)
      requirements are ``review`` — retained as metadata, never a hard drop.
    """
    details = extract_required_yoe_details(text)
    if details.get("confidence") != "high":
        decision = "review"
    elif (
        cap is not None
        and details.get("min") is not None
        and float(details["min"]) > float(cap)
    ):
        decision = "no_match"
    else:
        decision = "match"
    return {"domain": "yoe", "decision": decision, "result": decision, **details}


def _amount_currency(code: str | None, symbol: str | None) -> str | None:
    symbol_currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(symbol or "")
    code_currency = str(code or "").upper() or None
    if code_currency and symbol_currency and code_currency != symbol_currency:
        return None
    return code_currency or symbol_currency


def _normalize_period(value: str | None) -> str | None:
    text = _clean(value)
    if not text:
        return None
    if "hour" in text or text.endswith("/hr"):
        return "hour"
    for period in ("year", "month", "week", "day"):
        if period in text or text.startswith(period[:-1]):
            return period
    return None


def _compensation_period(match: re.Match, context: str) -> str | None:
    periods = {
        period for period in (
            _normalize_period(match.group(5)),
            _normalize_period(match.group(10)),
        )
        if period
    }
    if len(periods) > 1:
        return None
    if periods:
        return next(iter(periods))
    cues = set()
    low = context.lower()
    if any(value in low for value in ("/hour", "/hr", "per hour", "hourly")):
        cues.add("hour")
    if any(value in low for value in (
        "/year", "per year", "annually", "annual salary", "annual base",
        "total annual compensation",
    )):
        cues.add("year")
    return next(iter(cues)) if len(cues) == 1 else None


def _compensation_geography(before: str) -> str:
    """Best-effort label for a location-specific band, without inventing scope."""
    tail = before[-120:]
    labeled = re.search(r"([A-Za-z][A-Za-z0-9 ,/&().-]{1,80})\s*:\s*$", tail)
    if labeled:
        return _WS_RE.sub(" ", labeled.group(1)).strip(" ,;-")
    scoped = re.search(
        r"\b(?:for|in)\s+([A-Za-z][A-Za-z0-9 ,/&().-]{1,60})\s*$", tail, re.I)
    return _WS_RE.sub(" ", scoped.group(1)).strip(" ,;-") if scoped else ""


def _compensation_range(text: str | None, *, total: bool) -> dict | None:
    """Find a base-salary (``total=False``) or total-comp (``total=True``) range.

    Returns a rich internal dict (currency/period/bands are used to tell salary
    apart from total comp and to reject hourly/annual mixups). ``analyze_job_metadata``
    reduces the salary result to the flat ``{min, max}`` shape.
    """
    blob = _source_text(text)
    matches: list[dict] = []
    for match in _MONEY_RANGE_RE.finditer(blob):
        before = blob[max(0, match.start() - 120):match.start()].lower()
        after = blob[match.end():min(len(blob), match.end() + 80)].lower()
        context = before + " " + after
        nearest_total = max((before.rfind(term) for term in _TOTAL_TERMS), default=-1)
        nearest_salary = max((before.rfind(term) for term in _SALARY_TERMS), default=-1)
        if nearest_total >= 0 or nearest_salary >= 0:
            has_total = nearest_total > nearest_salary
            has_salary = nearest_salary > nearest_total
        else:
            has_total = any(term in after for term in _TOTAL_TERMS)
            has_salary = any(term in after for term in _SALARY_TERMS)
        if total:
            if not has_total:
                continue
        elif has_total or not has_salary:
            continue
        first_currency = _amount_currency(match.group(1), match.group(2))
        second_currency = _amount_currency(match.group(6), match.group(7))
        currencies = {value for value in (first_currency, second_currency) if value}
        if not currencies or len(currencies) != 1:
            continue
        currency = next(iter(currencies))
        low = _money(match.group(3), match.group(4))
        high = _money(match.group(8), match.group(9))
        if low > high:
            low, high = high, low
        if low <= 0 or high > 10_000_000:
            continue
        period = _compensation_period(match, context + " " + match.group(0))
        if not period:
            continue
        if period == "hour" and high > 100_000:
            continue
        matches.append({
            "min": low,
            "max": high,
            "currency": currency,
            "period": period,
            "geography": _compensation_geography(
                blob[max(0, match.start() - 120):match.start()]),
        })

    if not matches:
        return None
    if len(matches) > 1:
        return {
            "min": None,
            "max": None,
            "bands": matches,
            "source": "job_description",
        }
    only = matches[0]
    return {
        "min": only["min"],
        "max": only["max"],
        "currency": only["currency"],
        "period": only["period"],
        **({"geography": only["geography"]} if only["geography"] else {}),
        "source": "job_description",
    }


def extract_salary_range(text: str | None) -> dict | None:
    """Rich internal base-salary range (currency/period/bands) or ``None``."""
    return _compensation_range(text, total=False)


def classify_level(title: str | None) -> tuple[str, str]:
    """Return ``(normalized_level, stated_signal)`` from a generic title."""
    value = title or ""
    # Drop "Member of Technical Staff" so its trailing "Staff" can't mislabel an
    # MTS role as Staff-level; any real seniority word (senior/principal/...) that
    # prefixes the MTS phrase still survives and classifies normally.
    scan = _MTS_NEUTRALIZE_RE.sub(" ", value)
    for normalized, pattern in _LEVEL_RULES:
        match = pattern.search(scan)
        if match:
            return normalized, match.group(0)
    return "unknown", value.strip() or "Not stated"


def infer_level_from_yoe(minimum: int | float | None) -> str:
    """Conservative generic level fallback when a title has no seniority signal."""
    if minimum is None:
        return "unknown"
    years = float(minimum)
    if years < 2:
        return "entry"
    if years < 5:
        return "mid"
    if years < 9:
        return "senior"
    if years < 13:
        return "staff"
    return "senior_staff"


# ---------------------------------------------------------------------------
# Workplace arrangement (onsite / hybrid / remote) — a scalar read that is
# separate from the ``location`` city string. The location string is the primary
# signal (e.g. "Remote (US)", "San Francisco (Hybrid)", "Seattle, WA"); the JD body
# is only a fallback when no location string is recorded.
# ---------------------------------------------------------------------------
_REMOTE_WORKPLACE_TOKENS = (
    "remote", "work from home", "wfh", "work remotely", "fully distributed",
    "distributed team", "remote-first", "remote first",
)


def classify_workplace(
    location: str | None,
    description: str | None = "",
    workplace_hint: str | None = "",
) -> str:
    """Return ``onsite`` | ``hybrid`` | ``remote`` | ``unknown`` for a posting.

    Delegates to the canonical full-evidence location assessment so an ATS office
    list does not hide an explicit JD alternative such as "US hubs or remotely".
    """
    assessment = assess_location(
        location,
        {
            "allow_us_remote": True,
            "us_only": False,
            "require_match": False,
        },
        description=_source_text(description),
        workplace_hint=workplace_hint,
    )
    return assessment.workplace


# ---------------------------------------------------------------------------
# Visa-sponsorship read (likely / unlikely / unknown) — a heuristic scan of the
# JD text. Negatives (explicit denials) win over positives (explicit offers).
# This is advisory only; the agent must confirm sponsorship with the employer.
# ---------------------------------------------------------------------------
_SPONSOR_NEGATIVE = (
    "no sponsorship", "no visa sponsorship", "not offer sponsorship",
    "does not offer sponsorship", "do not offer sponsorship",
    "not offering visa sponsorship", "unable to sponsor", "not able to sponsor",
    "cannot sponsor", "can not sponsor", "will not sponsor", "does not sponsor",
    "do not sponsor", "not provide sponsorship", "unable to provide sponsorship",
    "unable to provide visa sponsorship", "not able to provide visa sponsorship",
    # "<subject> sponsorship ... will NOT be available" denial constructions
    # (real JD wordings — see GH issue #15 negation-phrase residual). Covers the
    # bare and "support" subjects plus the explicit "visa sponsorship" subject.
    "sponsorship will not be available", "sponsorship support will not be available",
    "visa sponsorship will not be available", "without sponsorship",
    "without visa sponsorship", "without employer sponsorship",
    "sponsorship is not available", "sponsorship not available",
    "not eligible for sponsorship", "not eligible for visa sponsorship",
    "does not require sponsorship", "do not require sponsorship",
    "must not require sponsorship", "not require sponsorship now or in the future",
    "authorized to work in the united states without sponsorship",
    "authorized to work without sponsorship", "work authorization without sponsorship",
    "us citizens only", "u.s. citizens only", "must be a us citizen",
    "must be a u.s. citizen", "citizenship is required", "green card holders only",
    "gc only", "green card required", "permanent resident only",
)
_SPONSOR_POSITIVE = (
    "sponsor h-1b", "sponsor h1b", "h-1b sponsorship", "h1b sponsorship",
    "visa sponsorship available", "visa sponsorship is available",
    "sponsorship available", "offer visa sponsorship",
    "provide visa sponsorship", "we sponsor", "will sponsor", "happy to sponsor",
    "open to sponsoring", "able to sponsor", "sponsor work visas", "sponsor visas",
    "green card sponsorship", "green card process", "perm process",
    "immigration sponsorship", "immigration support", "relocation and immigration",
    "cap-exempt", "cap exempt",
)

_SPONSOR_CONTEXT_RE = re.compile(
    r"\b(?:visa|h-?1b|immigration|work authorization|green card|"
    r"permanent residency|perm process|employment sponsorship)\b",
    re.I,
)
_SPONSOR_SIGNAL_RE = re.compile(
    r"\b(?:sponsor(?:ship|ing)?|visa|immigration|work authorization|"
    r"h-?1b|green card|perm)\b",
    re.I,
)
_SPONSOR_STRONG_POSITIVE = {
    "sponsor h-1b", "sponsor h1b", "h-1b sponsorship", "h1b sponsorship",
    "visa sponsorship available", "visa sponsorship is available",
    "offer visa sponsorship",
    "provide visa sponsorship", "sponsor work visas", "sponsor visas",
    "green card sponsorship", "green card process", "perm process",
    "immigration sponsorship", "cap-exempt", "cap exempt",
}


def _bounded_phrase_matches(text: str, phrases):
    hits = []
    for phrase in phrases:
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(phrase).replace(r"\ ", r"\s+")
            + r"(?![a-z0-9])",
            re.I,
        )
        hits.extend((phrase, match) for match in pattern.finditer(text))
    return hits


def _bounded_phrase_hits(text: str, phrases) -> list[str]:
    return list(dict.fromkeys(
        phrase for phrase, _match in _bounded_phrase_matches(text, phrases)))


def assess_sponsorship(text: str | None) -> dict:
    """Return an explainable tri-state sponsorship assessment.

    Generic words such as "we sponsor" are positive only when their surrounding
    sentence also contains immigration/work-authorization context. This prevents
    employee-program or event sponsorship copy from passing a hard visa gate.
    """
    source = _clean(_source_text(text))
    negative_matches = _bounded_phrase_matches(source, _SPONSOR_NEGATIVE)
    negative = list(dict.fromkeys(phrase for phrase, _ in negative_matches))
    positive: list[str] = []
    for phrase, positive_match in _bounded_phrase_matches(source, _SPONSOR_POSITIVE):
        if any(
            positive_match.start() < negative_match.end()
            and negative_match.start() < positive_match.end()
            for _negative_phrase, negative_match in negative_matches
        ):
            continue
        if phrase in _SPONSOR_STRONG_POSITIVE:
            if phrase not in positive:
                positive.append(phrase)
            continue
        window = source[
            max(0, positive_match.start() - 120):positive_match.end() + 120
        ]
        if _SPONSOR_CONTEXT_RE.search(window):
            if phrase not in positive:
                positive.append(phrase)

    if negative and positive:
        decision, verdict, confidence = "review", "unknown", "low"
        reason = "Conflicting sponsorship offer and denial language."
    elif negative:
        decision, verdict, confidence = "no_match", "unlikely", "high"
        reason = "The posting explicitly denies sponsorship."
    elif positive:
        decision, verdict, confidence = "match", "likely", "high"
        reason = "The posting explicitly offers immigration sponsorship."
    else:
        decision, verdict, confidence = "review", "unknown", "unknown"
        reason = "The posting does not provide decisive sponsorship evidence."
    rule_ids = [
        *(f"sponsorship.negative.{phrase}" for phrase in negative),
        *(f"sponsorship.positive.{phrase}" for phrase in positive),
    ]
    # The structural signature groups by rule FAMILY (polarity/conflict), not the
    # exact matched phrase, so cosmetic wording variants of a denial or an offer
    # collapse to one signature and no literal excerpt enters the signature.
    families = sorted({
        ".".join(rule_id.split(".", 2)[:2]) for rule_id in rule_ids
    })
    material = "|".join([
        "sponsorship", decision, verdict, confidence, ",".join(families),
    ])
    return {
        "decision": decision,
        "result": decision,
        "verdict": verdict,
        "confidence": confidence,
        "rule_ids": rule_ids,
        "evidence": [*negative, *positive],
        "signal_present": bool(_SPONSOR_SIGNAL_RE.search(source)),
        "reason": reason,
        "structural_signature": hashlib.sha256(
            material.encode("utf-8")).hexdigest()[:16],
    }


def classify_sponsorship_evidence(text: str | None) -> tuple[str, list[str]]:
    """Compatibility tuple of sponsorship verdict plus exact rule hits."""
    assessment = assess_sponsorship(text)
    return assessment["verdict"], list(assessment["evidence"])


def classify_sponsorship(text: str | None) -> str:
    """Return ``likely`` | ``unlikely`` | ``unknown`` for visa sponsorship.

    Heuristic on free JD text: an explicit denial -> ``unlikely`` (it wins over any
    offer), an explicit offer -> ``likely``, otherwise ``unknown``. Advisory only —
    always confirm with the employer before relying on it.
    """
    return assess_sponsorship(text)["verdict"]


# ---------------------------------------------------------------------------
# Application meta.yaml layer (the flat, human-facing schema v4).
# ---------------------------------------------------------------------------
def _google_range(normalized: str, level_entry: dict | None) -> tuple[float | None, float | None]:
    if isinstance(level_entry, dict):
        google = level_entry.get("google_equivalent")
        if isinstance(google, dict) and (
            google.get("min") is not None or google.get("max") is not None
        ):
            return (
                float(google["min"]) if google.get("min") is not None else None,
                float(google["max"]) if google.get("max") is not None else None,
            )
    generic = GENERIC_GOOGLE_EQUIVALENTS.get(
        normalized, GENERIC_GOOGLE_EQUIVALENTS["unknown"])
    return generic["min"], generic["max"]


def _salary_envelope(fact: dict) -> tuple[int | float | None, int | float | None]:
    """Collapse a rich salary fact (possibly multi-band) to one min/max."""
    bands = fact.get("bands")
    if isinstance(bands, list) and bands:
        # Prefer annual bands so a stray hourly band cannot shrink the envelope.
        annual = [b for b in bands if isinstance(b, dict) and b.get("period") == "year"]
        chosen = annual or [b for b in bands if isinstance(b, dict)]
        mins = [b["min"] for b in chosen if b.get("min") is not None]
        maxs = [b["max"] for b in chosen if b.get("max") is not None]
        return (min(mins) if mins else None, max(maxs) if maxs else None)
    return fact.get("min"), fact.get("max")


def _bare_salary(description: str, supplied: dict | None) -> dict | None:
    """A flat ``{min, max, confidence, source}`` salary, or ``None``."""
    fact = extract_salary_range(description)
    if fact:
        low, high = _salary_envelope(fact)
        if low is not None or high is not None:
            return {
                "min": _num_or_none(low),
                "max": _num_or_none(high),
                "confidence": "high",
                "source": "job_description",
            }
    if isinstance(supplied, dict):
        low, high = supplied.get("min"), supplied.get("max")
        if low is not None or high is not None:
            return {
                "min": _num_or_none(low),
                "max": _num_or_none(high),
                "confidence": "medium",
                "source": str(supplied.get("source") or "aggregator"),
            }
    return None


def analyze_job_metadata(
    *,
    company: str,
    title: str,
    description: str,
    location: str = "",
    company_levels: dict | None = None,
    supplied_salary_range: dict | None = None,
) -> dict:
    """Build the flat, human-facing metadata for one posting.

    Precedence is simple and JD-first: a value parsed from the live posting wins;
    otherwise the company-levels cache fills level/YOE; salary falls back to an
    aggregator-supplied range only for discovery. ``workplace`` is read primarily
    from ``location`` (with the JD body as a fallback) and ``sponsorship`` is a
    heuristic scan of the JD text.
    """
    reference = company_levels or {}
    matched = lookup_company_level(company, title, reference)
    _company_entry, level_entry = matched if matched else ({}, {})

    yoe_details = extract_required_yoe_details(f"{title}\n{description}")

    # --- job level -------------------------------------------------------
    if level_entry:
        normalized = str(level_entry.get("normalized") or "unknown").strip().lower()
        level_source, level_confidence = "company_reference", "medium"
    else:
        normalized, _signal = classify_level(title)
        if normalized != "unknown":
            level_source, level_confidence = "title", "medium"
        elif yoe_details.get("min") is not None:
            normalized = infer_level_from_yoe(yoe_details["min"])
            level_source, level_confidence = "required_yoe", "low"
        else:
            level_source, level_confidence = "generic", "low"
    if normalized not in NORMALIZED_LEVELS:
        normalized = "unknown"
    low, high = _google_range(normalized, level_entry)
    job_level = {
        "normalized": normalized,
        "min": low,
        "max": high,
        "confidence": level_confidence,
        "source": level_source,
    }

    # --- required years of experience -----------------------------------
    cached_yoe = level_entry.get("required_yoe") if isinstance(level_entry, dict) else None
    if yoe_details.get("min") is not None:
        required_yoe = {
            "min": yoe_details["min"],
            "max": yoe_details["max"],
            "confidence": yoe_details["confidence"],
            "source": "job_description",
        }
    elif isinstance(cached_yoe, dict) and (
        cached_yoe.get("min") is not None or cached_yoe.get("max") is not None
    ):
        required_yoe = {
            "min": _num_or_none(cached_yoe.get("min")),
            "max": _num_or_none(cached_yoe.get("max")),
            "confidence": "medium",
            "source": "company_reference",
        }
    else:
        required_yoe = {
            "min": None,
            "max": None,
            "confidence": "unknown",
            "source": "not_stated",
        }

    # --- salary ----------------------------------------------------------
    salary_range = _bare_salary(description, supplied_salary_range)

    # --- scalar reads (workplace, sponsorship) ---------------------------
    workplace = classify_workplace(location, description)
    sponsorship = classify_sponsorship(f"{title}\n{description}")

    return {
        "workplace": workplace,
        "sponsorship": sponsorship,
        "job_level": job_level,
        "required_yoe": required_yoe,
        "salary_range": salary_range,
    }


def _deep_gaps(current: dict, generated: dict) -> dict:
    gaps = {}
    for key, value in generated.items():
        if key not in current:
            gaps[key] = value
        elif isinstance(current[key], dict) and isinstance(value, dict):
            nested = _deep_gaps(current[key], value)
            if nested:
                gaps[key] = nested
    return gaps


def metadata_field_gaps(record: dict, metadata: dict) -> dict:
    """Return only missing metadata keys, recursively, without replacements."""
    gaps: dict = {}
    for field in METADATA_FIELDS:
        if field not in record or record.get(field) in ({}, ""):
            gaps[field] = metadata.get(field)
            continue
        current, generated = record.get(field), metadata.get(field)
        if isinstance(current, dict) and isinstance(generated, dict):
            nested = _deep_gaps(current, generated)
            if nested:
                gaps[field] = nested
    return gaps


# ---------------------------------------------------------------------------
# Validation (schema v4 is strict; there is no legacy/compat path).
# ---------------------------------------------------------------------------
_STATUS_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
def _validate_numeric_range(
    value: Any,
    *,
    allow_none: bool,
    path: str,
    max_value: float | None = None,
    require_bound: bool = False,
) -> list[str]:
    if value is None:
        return [] if allow_none else [f"{path} is required"]
    if not isinstance(value, dict):
        return [f"{path} must be a mapping or null"]
    errors = []
    for name in ("min", "max"):
        if name not in value:
            errors.append(f"{path}.{name} is missing")
    low, high = value.get("min"), value.get("max")
    for name, number in (("min", low), ("max", high)):
        if number is None:
            continue
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            errors.append(f"{path}.{name} must be numeric or null")
            continue
        if not math.isfinite(float(number)):
            errors.append(f"{path}.{name} must be finite")
        elif number < 0:
            errors.append(f"{path}.{name} must be non-negative")
        elif max_value is not None and number > max_value:
            errors.append(f"{path}.{name} must not exceed {max_value:g}")
    if require_bound and low is None and high is None:
        errors.append(f"{path} must contain at least one numeric bound")
    if (
        isinstance(low, (int, float))
        and not isinstance(low, bool)
        and math.isfinite(float(low))
        and isinstance(high, (int, float))
        and not isinstance(high, bool)
        and math.isfinite(float(high))
        and low > high
    ):
        errors.append(f"{path}.min must not exceed {path}.max")
    return errors


def _validate_confidence(value: Any, path: str) -> list[str]:
    if not value:
        return [f"{path}.confidence is required"]
    if value not in CONFIDENCE_VALUES:
        return [
            f"{path}.confidence must be one of "
            f"{', '.join(sorted(CONFIDENCE_VALUES))}"
        ]
    return []


def _validate_source(value: Any, path: str) -> list[str]:
    return [] if str(value or "").strip() else [f"{path}.source is required"]


def _validate_enum(value: Any, allowed: set[str], path: str) -> list[str]:
    if not str(value or "").strip():
        return [f"{path} is required"]
    if value not in allowed:
        return [f"{path} must be one of {', '.join(sorted(allowed))}"]
    return []


def _validate_status(value: Any, path: str) -> list[str]:
    """Require a per-job ``status`` in ``STATUS_VALUES`` (listed in precedence order)."""
    if not str(value or "").strip():
        return [f"{path} is required"]
    if value not in STATUS_VALUES:
        return [f"{path} must be one of {', '.join(STATUS_VALUES)}"]
    return []


def _validate_stage(value: Any, path: str) -> list[str]:
    """Optional per-job ``stage``: free text. Absent/null is fine; must be a string."""
    if value is None:
        return []
    if not isinstance(value, str):
        return [f"{path} must be a string"]
    return []


def _validate_status_date(value: Any, path: str) -> list[str]:
    """Optional per-job ``status_date``: a ``YYYY-MM-DD`` string. Absent/null/"" is fine."""
    if value is None or value == "":
        return []
    if not isinstance(value, str) or not _STATUS_DATE_RE.fullmatch(value):
        return [f"{path} must be a YYYY-MM-DD date string"]
    try:
        date.fromisoformat(value)
    except ValueError:
        return [f"{path} must be a valid YYYY-MM-DD date"]
    return []


def _validate_job_level(level: Any, lead: str) -> list[str]:
    path = f"{lead}job_level"
    if not isinstance(level, dict):
        return [f"{path} must be a mapping"]
    errors = []
    normalized = str(level.get("normalized") or "")
    if normalized not in NORMALIZED_LEVELS:
        errors.append(
            f"{path}.normalized must be one of "
            f"{', '.join(sorted(NORMALIZED_LEVELS))}")
    errors.extend(_validate_numeric_range(
        level, allow_none=False, path=path, max_value=20))
    errors.extend(_validate_confidence(level.get("confidence"), path))
    errors.extend(_validate_source(level.get("source"), path))
    return errors


def _validate_required_yoe(value: Any, lead: str) -> list[str]:
    path = f"{lead}required_yoe"
    errors = _validate_numeric_range(
        value, allow_none=False, path=path, max_value=50)
    if isinstance(value, dict):
        errors.extend(_validate_confidence(value.get("confidence"), path))
        errors.extend(_validate_source(value.get("source"), path))
    return errors


def _validate_salary_range(value: Any, lead: str) -> list[str]:
    path = f"{lead}salary_range"
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{path} must be a mapping or null"]
    errors = _validate_numeric_range(
        value, allow_none=False, path=path, max_value=100_000_000,
        require_bound=True)
    errors.extend(_validate_confidence(value.get("confidence"), path))
    errors.extend(_validate_source(value.get("source"), path))
    return errors


def validate_job_metadata(record: dict, *, prefix: str = "") -> list[str]:
    """Validate the per-posting metadata of one ``jobs`` entry."""
    lead = f"{prefix}." if prefix else ""
    errors: list[str] = []
    for field in METADATA_FIELDS:
        if field not in record:
            errors.append(f"{lead}{field} is missing")
    errors.extend(_validate_job_level(record.get("job_level"), lead))
    errors.extend(_validate_required_yoe(record.get("required_yoe"), lead))
    errors.extend(_validate_salary_range(record.get("salary_range"), lead))
    errors.extend(_validate_enum(
        record.get("workplace"), WORKPLACE_VALUES, f"{lead}workplace"))
    errors.extend(_validate_enum(
        record.get("sponsorship"), SPONSORSHIP_VALUES, f"{lead}sponsorship"))
    errors.extend(_validate_status(record.get("status"), f"{lead}status"))
    errors.extend(_validate_stage(record.get("stage"), f"{lead}stage"))
    errors.extend(_validate_status_date(record.get("status_date"), f"{lead}status_date"))
    return errors


def validate_jd_file_associations(meta: dict, app_dir: str | Path) -> list[str]:
    """Validate exact one-to-one JD filenames for the jobs list."""
    jobs = meta.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return []

    root = Path(app_dir)
    source_root = root / "source"
    search_roots = [source_root, root] if source_root.is_dir() else [root]
    actual_files = {
        path.name
        for directory in search_roots
        for path in directory.glob("JD-*.md")
        if path.is_file()
    }
    referenced: set[str] = set()
    errors: list[str] = []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        name = str(job.get("jd_file") or "").strip()
        if not name:
            continue
        if Path(name).name != name:
            errors.append(f"jobs[{index}].jd_file must be a filename, not a path")
            continue
        if not name.startswith("JD-") or not name.endswith(".md"):
            errors.append(f"jobs[{index}].jd_file must match JD-<job-title>.md")
        if name in referenced:
            errors.append(f"jobs[{index}].jd_file duplicates another role: {name}")
        referenced.add(name)
        if not any((directory / name).is_file() for directory in search_roots):
            errors.append(f"jobs[{index}].jd_file does not exist: {name}")

    for name in sorted(actual_files - referenced):
        errors.append(f"unreferenced JD file: {name}")
    return errors


def validate_meta(meta: dict, *, app_dir: str | Path | None = None) -> list[str]:
    """Validate schema-v4 application metadata (a uniform ``jobs`` list).

    Each ``jobs`` entry carries a required per-job ``status`` (one of
    ``STATUS_VALUES``) plus optional ``stage``/``status_date``; the top-level
    ``stage`` field of v3 is gone and is now rejected. When ``app_dir`` sits inside
    a known status folder, the folder label must equal ``derive_status(jobs)`` — a
    manual folder move that skipped the CLI is flagged so it can be re-synced.
    """
    version = meta.get("job_metadata_schema_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != APPLICATION_SCHEMA_VERSION
    ):
        return [
            f"job_metadata_schema_version must be {APPLICATION_SCHEMA_VERSION}"
        ]

    errors: list[str] = []
    if not str(meta.get("company") or "").strip():
        errors.append("company is required")
    if "stage" in meta:
        errors.append(
            "top-level stage is not allowed in schema v4 (move it to per-job stage)")
    if "status" in meta:
        errors.append(
            "top-level status is not allowed in schema v4 (status is per-job, "
            "under jobs:)")

    jobs = meta.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        errors.append("jobs must be a non-empty list (one entry per posting)")
        return errors

    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            errors.append(f"jobs[{index}] must be a mapping")
            continue
        if not str(job.get("role") or "").strip():
            errors.append(f"jobs[{index}].role is required")
        if not str(job.get("jd_file") or "").strip():
            errors.append(f"jobs[{index}].jd_file is required")
        errors.extend(validate_job_metadata(job, prefix=f"jobs[{index}]"))

    if app_dir is not None:
        errors.extend(validate_jd_file_associations(meta, app_dir))
        # Folder-consistency: the overall status is DERIVED from the per-job
        # statuses. When the app lives in a known status folder, that folder's
        # label must equal the rollup, else a manual move drifted out of sync.
        folder_label = status_label_for_dir(Path(app_dir).parent.name)
        if folder_label is not None:
            try:
                derived = derive_status(jobs)
            except ValueError:
                derived = None  # invalid per-job statuses already reported above
            if derived is not None and derived != folder_label:
                errors.append(
                    f"folder status '{folder_label}' does not match derived status "
                    f"'{derived}' from the per-job statuses; re-sync with "
                    f"`status.py --update <slug> {derived}` or `status.py --update-job`"
                )
    return errors
