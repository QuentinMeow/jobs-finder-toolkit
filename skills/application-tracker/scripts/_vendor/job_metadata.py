"""Pure helpers for structured, human-readable job metadata (schema v6).

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
    ``{min, max, period, currency, confidence, source}`` or ``None`` — posted
    pay. ``period``/``currency`` are stated, never assumed: a band parsed from
    the JD is always ``year`` (nothing else reaches this field), but a band
    supplied by an aggregator's structured pay field may be hourly or monthly,
    and the unit is the difference between "$30/hour" and "$30k/year".
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
APPLICATION_SCHEMA_VERSION = 6
LEGACY_APPLICATION_SCHEMA_VERSION = 5

# Canonical schema-v6 keys for one ``jobs:`` record. Unknown scalar keys remain
# tolerated for older local annotations, but unknown mappings/lists are rejected:
# structured extensions are otherwise easy to mistake for supported schema.
JOB_SCHEMA_FIELDS = frozenset({
    "role",
    "jd_file",
    "status",
    "status_date",
    "progress",
    "location",
    "workplace",
    "url",
    "store_key",
    "posted_date",
    "sponsorship",
    "fit",
    "job_level",
    "required_yoe",
    "salary_range",
})
UNSUPPORTED_COMPENSATION_FIELD = "total_compensation_range"

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


# ---------------------------------------------------------------------------
# Structured per-job progress (schema v6). ``jobs[].progress`` replaces the
# retired free-text ``stage`` with a normalized {phase, state} summary; ``label``
# preserves employer-specific wording without expanding the enums.
# ---------------------------------------------------------------------------
# Hiring phases: "which hiring step is this role in?" — independent from
# whether a time has been arranged. ``other`` requires a non-empty ``label``.
PROGRESS_PHASES = (
    "application_prep",
    "application_review",
    "recruiter_screen",
    "assessment",
    "hiring_manager",
    "technical_interview",
    "interview_loop",
    "team_match",
    "reference_check",
    "offer",
    "background_check",
    "work_authorization",
    "onboarding",
    "other",
)
# Workflow states: "what is happening now, and who needs to act?"
PROGRESS_STATES = (
    "unknown",
    "action_required",
    "booking_required",
    "awaiting_schedule",
    "scheduled",
    "reschedule_required",
    "reschedule_pending",
    "in_progress",
    "decision_required",
    "follow_up_required",
    "waiting_employer",
    "awaiting_result",
    "paused",
    "closed",
)
# States projected onto the calendar file. Keep the reporting states broad and
# describe employer-specific work in ``label`` / the calendar action text: an
# assessment, portfolio request, reference request, offer decision, or follow-
# up should not require a new phase enum merely to become a clear todo.
PROGRESS_ACTION_STATES = (
    "action_required",
    "booking_required",
    "reschedule_required",
    "in_progress",
    "decision_required",
    "follow_up_required",
)
PROGRESS_WAITING_STATES = (
    "awaiting_schedule",
    "reschedule_pending",
    "waiting_employer",
    "awaiting_result",
    "paused",
)
# Scheduling-flow states: entering one of these creates/updates a calendar entry.
PROGRESS_SCHEDULING_STATES = (
    "booking_required",
    "awaiting_schedule",
    "scheduled",
    "reschedule_required",
    "reschedule_pending",
)
PROGRESS_CALENDAR_STATES = (
    *PROGRESS_ACTION_STATES,
    *PROGRESS_WAITING_STATES,
    "scheduled",
)
PROGRESS_SOURCE_KINDS = ("manual", "email")
# Coarse statuses whose progress state must be (exactly) ``closed``.
CLOSED_STATUSES = ("rejected", "ignored")

CALENDAR_ITEM_RE = re.compile(r"^cal-[a-z0-9][a-z0-9-]*$")

# Recognized legacy ``stage`` wordings -> hiring phase, used ONLY by the
# deterministic v4 -> v5 migration. A stage text maps to a phase when exactly
# one family below matches; anything else migrates as phase ``other`` with the
# exact old text preserved in ``label``. Never guesses a workflow state.
_LEGACY_STAGE_PHASES = (
    ("recruiter_screen", ("recruiter", "phone screen", "screening call")),
    ("assessment", ("assessment", "take-home", "take home", "online test", "coding challenge")),
    ("hiring_manager", ("hiring manager",)),
    ("technical_interview", ("technical screen", "technical interview", "tech screen",
                             "coding interview", "system design")),
    ("interview_loop", ("onsite", "on-site", "interview loop", "final round",
                        "final loop", "virtual onsite", "panel")),
    ("team_match", ("team match", "team matching")),
    ("reference_check", ("reference check", "references")),
    ("offer", ("offer",)),
    ("background_check", ("background check", "background")),
    ("work_authorization", ("work authorization", "immigration", "visa paperwork")),
    ("onboarding", ("onboarding", "onboard")),
)


def legacy_stage_phase(stage: str | None) -> str | None:
    """Map a legacy free-text stage to a phase when EXACTLY one family matches."""
    text = _clean(stage)
    if not text:
        return None
    matched = [
        phase for phase, needles in _LEGACY_STAGE_PHASES
        if any(needle in text for needle in needles)
    ]
    return matched[0] if len(matched) == 1 else None


def default_progress_for_status(status: str, *, current: dict | None = None) -> dict:
    """The deterministic progress summary for a coarse per-job status transition.

    Mirrors the migration mapping (docs/designs/application-progress-calendar §6):
    ``drafted`` -> application_prep + action_required; ``applied`` ->
    application_review + waiting_employer; ``rejected``/``ignored`` keep the
    last known phase with state ``closed``; ``in_progress`` keeps the current
    phase (and any still-valid active state) but NEVER guesses — an unknown or
    closed prior state becomes ``unknown``. ``label``/``calendar_items`` from the
    current progress are preserved except on the drafted/applied resets.
    """
    current = current if isinstance(current, dict) else {}
    keep_calendar: dict[str, list] = {}
    calendar_items = current.get("calendar_items")
    if isinstance(calendar_items, list):
        keep_calendar["calendar_items"] = list(calendar_items)
    if status == "drafted":
        return {"phase": "application_prep", "state": "action_required", **keep_calendar}
    if status == "applied":
        return {"phase": "application_review", "state": "waiting_employer", **keep_calendar}
    phase = str(current.get("phase") or "").strip()
    label = str(current.get("label") or "").strip()
    if phase not in PROGRESS_PHASES:
        phase, label = "other", (label or status)
    out: dict = {"phase": phase}
    if status in CLOSED_STATUSES:
        out["state"] = "closed"
    else:  # in_progress: keep a deliberately-set active state, never guess one.
        state = str(current.get("state") or "").strip()
        keepable = set(PROGRESS_CALENDAR_STATES)
        out["state"] = state if state in keepable else "unknown"
    if label:
        out["label"] = label
    out.update(keep_calendar)
    return out


def migrate_job_progress(status: str | None, stage: str | None) -> dict:
    """Deterministic v4 -> v5 progress for one job (design §6). Never guesses.

    - ``drafted`` -> application_prep + action_required
    - ``applied`` -> application_review + waiting_employer
    - ``in_progress`` -> recognized legacy stage phase (else ``other``), state
      ``unknown``; the exact old stage text (or the status literal when the
      stage was empty) is preserved as ``label``.
    - ``rejected``/``ignored`` -> state ``closed``; phase from the recognized
      stage, else ``application_review`` for rejected (it was at least
      submitted) / ``application_prep`` for ignored (never submitted), with any
      unrecognized non-empty stage preserved via phase ``other`` + ``label``.

    No migration invents a calendar item, timestamp, email source, or
    completion event, so none of those keys ever appear in the result.
    """
    status_text = str(status or "").strip()
    stage_text = str(stage or "").strip()
    if status_text == "drafted":
        out = {"phase": "application_prep", "state": "action_required"}
    elif status_text == "applied":
        out = {"phase": "application_review", "state": "waiting_employer"}
    elif status_text == "in_progress":
        phase = legacy_stage_phase(stage_text)
        out = {"phase": phase or "other", "state": "unknown",
               "label": stage_text or status_text}
    elif status_text in CLOSED_STATUSES:
        phase = legacy_stage_phase(stage_text)
        if phase:
            out = {"phase": phase, "state": "closed"}
        elif stage_text:
            out = {"phase": "other", "state": "closed", "label": stage_text}
        else:
            out = {
                "phase": ("application_review" if status_text == "rejected"
                          else "application_prep"),
                "state": "closed",
            }
    else:
        raise ValueError(f"cannot migrate unknown status {status!r}")
    if stage_text and "label" not in out:
        out["label"] = stage_text
    return out


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
# A YOE number is a REQUIREMENT only when the years are attributed to the
# applicant. "<N> years of engineering experience" reads identically whether the
# sentence is a qualifications bullet or the About-us blurb above it, so the
# subject is what separates them: a possessor phrase naming the employer, its
# team, or its customers means the years belong to somebody else and constrain
# nobody. Same posture as the sponsorship negation scope in this file — when the
# sentence does not clearly attribute the years to the applicant, the honest
# answer is that no requirement was found, not a number.
_THIRD_PARTY_YOE_RE = re.compile(
    r"\b(?:"
    r"(?:our|the|a|an|its|their)\s+"
    r"(?:teams?|founders?|co-?founders?|leadership|engineers|staff|employees|"
    r"people|company|companies|group|advisors?|investors?|board|executives?|"
    r"management|clients?|customers?|partners?|users?)"
    r"|we\s+(?:have|had|bring|brings|combine|combines|share|shares|boast|boasts|"
    r"carry|carries|average|averages|count|serve|serves)"
    r"|(?:clients?|customers?|partners?|users?|founders?|advisors?|investors?|"
    r"executives?)\s+(?:who|that|with)"
    r"|founded"
    r")\b",
    re.I,
)
# Applicant-facing vocabulary. Anything on this list between a third-party
# possessor and the number means the sentence turned back to the candidate
# ("our team is hiring an engineer with 6+ years ..."), so the guard stands down
# and the match is classified exactly as before.
_CANDIDATE_YOE_RE = re.compile(
    r"\b(?:you|your|candidates?|applicants?|ideal|successful|seeking|seeks?|"
    r"looking\s+for|hiring|hire|join|opening|opportunit(?:y|ies)|roles?|"
    r"positions?|vacancy|require[sd]?|requirements?|must|minimum|at\s+least|"
    r"qualifications?|should\s+have|we\s+want|we\s+need|someone|somebody)\b",
    re.I,
)
# "<N> years of combined experience" is a team total by construction.
_COMBINED_YOE_RE = re.compile(r"\bcombined\b", re.I)
# The start of the NEXT independent YOE clause (e.g. the "5+ years" in
# "... experience with at least 5+ years in leadership"). Used to bound one
# match's forward look-ahead so an adjacent, separately-classified clause cannot
# contaminate this match's confidence/kind — the later clause is scored on its
# own pass. Kept deliberately loose (any "<n> years" mention) so any conjunction
# or punctuation between the two clauses still ends the window.
_NEXT_YOE_CLAUSE_RE = re.compile(
    r"\b\d{1,2}(?:\.\d+)?\s*\+?\s*(?:years?|yrs?\.?)",
    re.I,
)

# Function words that can sit between "years" and "experience" WITHOUT naming a
# tool or a domain. They exist as a block-list because the second branch of
# ``_CONTEXTUAL_YOE_RE`` had an optional ``(?:of\s+)?`` in front of its domain
# token, and an optional group is a BACKTRACK: when the literal "of " could not
# be followed by a domain token, the engine dropped the optional group and let
# "of" itself BE the domain token. So "10+ years of experience" matched as
# "years <of> experience" — the single most common phrasing in English job
# posts, graded tool-specific/medium. Only HIGH confidence is decisive
# (``assess_required_yoe``), so the documented ``max_years_experience`` cap
# silently did nothing on those postings: with a cap of 6, "Minimum 7 years of
# experience" was KEPT while "Minimum 7 years of professional experience" — the
# same requirement, one adjective apart — was correctly dropped.
_YOE_NON_DOMAIN_TOKENS = r"of|in|with|as|at|on|for|to|and|or|the|an?"
_CONTEXTUAL_YOE_RE = re.compile(
    # Branch 1 — "<N> years [of experience] <preposition> <tool/domain>".
    # Bare "with" belongs here for the same reason the block-list exists: the
    # genuinely tool-specific readings that USED to be caught by the "of"
    # backtrack ("8+ years of experience with Kubernetes") must keep their
    # contextual grade, and "with" is the preposition that carries them. Without
    # it, "Required: 8+ years of experience with Kubernetes" would become a
    # high-confidence GENERAL requirement and hard-drop a specialty posting.
    r"\byears?(?:\s+of\s+experience)?\s+"
    r"(?:working\s+with|using|with|in)\s+"
    r"(?!software engineering\b|engineering\b|industry\b|professional\b)|"
    # Branch 2 — "<N> years [of] <tool/domain> experience".
    rf"\byears?\s+(?:of\s+)?(?!professional\b|industry\b|work\b|relevant\b|"
    rf"software engineering\b|engineering\b|(?:{_YOE_NON_DOMAIN_TOKENS})\b)"
    r"[a-z0-9+#.-]+\s+experience\b",
    re.I,
)

# The NUMBER is digit-anchored at both ends. Unanchored, the bare 2-3 digit
# alternative reads a FRAGMENT of a longer figure: in "$3240 - $175,000" the scan
# slid past "3" and matched "240", then paired that fragment with a real salary,
# so the shortlist printed a band no employer states. This is the same class of
# miss as the unanchored "ote" substring documented in ``_compensation_range``,
# one level down — there the boundary that was missing was a word, here it is a
# digit. ``(?![.,]\d)`` covers the same slide across a thousands/decimal
# separator ("$1.240" -> "240").
#
# CENTS are part of the figure, not a fragment after it. The trailing guard was
# strict enough to reject every well-formed decimal it was meant to protect:
# "$60,000.00 - $90,000.00 per year" parsed as NOTHING, because "60,000" hit
# ``(?![.,]\d)`` on the ".0" that follows it and the 2-3 digit alternative then
# hit the same guard on the comma. Dropping the cents by hand made the same line
# parse, which is the tell. The grouped form ``(?:\.\d{2})?`` is therefore part
# of the comma-separated alternative — the only shape a cents figure takes — and
# the guard still runs AFTER it, so the fragment routes stay closed: "$3240"
# still matches nothing (no comma for the first alternative; "324"/"32" still
# rejected by ``(?!\d)``), and ``\.\d{2}`` is exact, so a three-decimal figure
# ("60,000.000") is refused rather than truncated. Pinned by
# ``test_a_digit_fragment_of_a_longer_figure_is_not_a_salary_bound`` and
# ``test_cents_do_not_void_a_salary_band``.
_AMOUNT = (
    r"(?:(USD|CAD|EUR|GBP)\s*)?([$€£])?\s*"
    r"((?<![\d.,])(?:\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d{2,3}(?:\.\d+)?)"
    r"(?!\d|[.,]\d))\s*([kK])?"
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
# The keyword that says "the numbers nearby are PAY". An hourly posting states
# it in its own vocabulary — "the target hourly range is $21-$25", "the hourly
# rate for this role" — and neither spelling was on this list, so an
# hourly-stated band parsed as ``None`` while the same band under the words "pay
# range" parsed fine. The two hourly spellings are pay keywords exactly like
# "pay range"; they say nothing about the PERIOD, which ``_compensation_period``
# reads separately, and nothing about whether the band is annualisable, which
# ``_salary_envelope`` decides separately (an hourly band still never reaches the
# annual ``salary_range`` field).
_SALARY_TERMS = (
    "base salary",
    "base pay",
    "salary range",
    "pay range",
    "hourly range",
    "hourly rate",
    "annual salary",
    "annual base",
    "base compensation",
)

# A pay band's two ends describe ONE figure, so they sit within an order of
# magnitude of each other AND each end is a credible rate for its own period.
# Both bounds exist because this extractor can pair numbers that were never a
# pair: a live sweep of 11,638 postings printed "$240 - $175,000" for one role.
# Two independent routes produce that shape, and each needs its own guard —
#
#   * one match, one bad end: an unanchored fragment read out of a longer figure
#     (fixed at the match site by ``_AMOUNT``'s digit guards, but the spread
#     limit is the cheap backstop if another fragment route is ever found);
#   * two GOOD matches stitched together: a real "$140,000 - $175,000" salary
#     line and a "$240 - $300" annual stipend a few words later, both kept
#     because the nearest preceding keyword to each was "base salary", then
#     collapsed by ``_salary_envelope`` to (min of mins, max of maxs). Neither
#     band is malformed; the PAIR is.
#
# The thresholds are deliberately generous, because the two errors are not
# symmetric: a dropped band is recoverable (the JD is on disk and the row reads
# "none parsed"), a wrong band is shown to the user as fact and written into
# meta.yaml. A band that is merely UNUSUAL must survive — every floor sits below
# any real posted rate, so hourly contract bands, part-time monthly bands and
# annualised intern bands all clear them, and the 10x spread is far wider than
# the widest real all-levels annual band (~6x).
_PERIOD_PAY_FLOOR = {"year": 10_000, "month": 500, "week": 100, "day": 50, "hour": 5}
# Kept as a map for symmetry with the floor; an hourly rate above this is an
# annual figure that was mislabeled by nearby "per hour" boilerplate.
_PERIOD_PAY_CEILING = {"hour": 100_000}
_BAND_SPREAD_LIMIT = 10

# "Member of <X> Staff" is a role-family name, not a Staff-level (L6) signal — the
# trailing "Staff" must not trip the bare ``\bstaff\b`` rule below. Neutralized
# before the level rules run, so "Member of Technical Staff" reads as unknown while
# "Senior Member of Technical Staff" still resolves via "senior".
#
# The qualifier is a WILDCARD, not a literal. "Technical" is the best-known
# spelling but it is one of many the same family uses on real boards — Data,
# Research, Engineering, Product, Deployment, Go-To-Market — and a live scan hit
# "Member of Data Staff", which the single-spelling pattern graded Staff-level and
# a `staff` exclude then deleted. Bounded at two qualifier words and blocked on
# connectives so the span cannot run past the head noun it belongs to.
MEMBER_OF_STAFF_TITLE_RE = re.compile(
    r"\bmembers?\s+of\s+(?:the\s+)?"
    r"(?:(?!of\b|and\b|for\b|to\b|at\b|in\b)[a-z][a-z0-9&/'-]*\s+){0,2}"
    r"staff\b",
    re.I,
)
_MTS_NEUTRALIZE_RE = MEMBER_OF_STAFF_TITLE_RE

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


# NOT the owner's ``company_key``. This is a throwaway MATCH key: it exists only
# so ``lookup_company_level`` can decide whether a free-text company string names
# the same employer as a row in the company-levels cache. It is never persisted,
# never compared against ``meta.yaml``'s ``company_key``, and never resolved
# against the company index. The persisted field's validator is
# ``_validate_company_key`` further down this same file, and the two must not be
# read as versions of each other — which is why this one carries ``match`` in its
# name (the mail reconciler's identically-shaped helper was renamed for the same
# reason, and is guarded by name in
# ``automation/shared/tests/test_company_key_additive.py``).
#
# THREE NORMALIZERS, THREE DIFFERENT SUFFIX RULES, ON PURPOSE — do not unify them
# without measuring, because each disagreement changes what matches what:
#
#   * this one — strips 7 legal suffixes (incorporated|inc|llc|ltd|corp|
#     corporation|company) ANYWHERE in the string via ``\b``, then folds every
#     non-alphanumeric run to a space. Deliberately loose: it is matching a
#     hand-written cache of employer names, where "Acme Labs" and "Acme Labs,
#     Inc." are the same row;
#   * ``skills/job-search/scripts/registry.py::comparable_base`` — strips the
#     whole of that module's ``_LEGAL_SUFFIXES`` (15 entries today), TRAILING
#     only, and never the last remaining token. A trailing-only rule keeps an
#     employer whose real name merely CONTAINS one of those words ("Inc
#     Magazine") distinct, which matters where the registry decides identity;
#   * ``automation/shared/mail/reconciliation.py::_company_match_key`` — strips
#     NOTHING. It binds email threads to applications, where a wrong merge routes
#     a recruiter's mail to the wrong employer.
#
# Making them agree would change which companies match which level rows, which
# rows dedup, and which threads bind — a behaviour change that needs its own task
# and its own before/after corpus, not a tidy-up.
def _company_match_key(value: Any) -> str:
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
    """Undo common Markdown escapes before running JD regexes.

    The HYPHEN belongs on this list for the same reason ``+`` and ``$`` do, and
    its absence was not cosmetic: markdownify (the HTML->Markdown step every
    JobSpy-sourced JD goes through) escapes a hyphen that could start a list
    item, so a real posting arrives as ``3\\-5 years of experience``. With the
    backslash still in the text ``_YOE_RANGE_RE`` cannot see a range separator
    at all, the range is missed, and one of the ``_YOE_MIN_PATTERNS`` then reads
    the range's UPPER bound as a standalone minimum — ``3\\-5 years`` was
    extracted as ``min: 5``, so the band's CEILING became its FLOOR and a
    posting the candidate qualifies for was hard-dropped by the
    ``max_years_experience`` gate. Escaped and unescaped text must parse
    identically; ``test_escaped_range_dash_still_parses_as_a_range`` pins that.
    """
    return re.sub(r"\\([-+$])", r"\1", value or "")


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
    company_match_key = _company_match_key(company)
    title_key = _clean(title)
    best: tuple[int, dict, dict] | None = None
    for company_entry in _companies(reference):
        names = [company_entry.get("name"), *(company_entry.get("aliases") or [])]
        if company_match_key not in {_company_match_key(name) for name in names if name}:
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

    Preferred/nice-to-have statements are excluded from ``required_yoe``, as is
    experience the sentence attributes to somebody other than the applicant. Tool-
    or domain-specific experience is retained as medium-confidence context only, so
    it can be displayed but cannot hard-filter a job-search result.
    """
    local, before, after = _yoe_match_context(blob, match.start(), match.end())
    # Scope the forward look-ahead to THIS clause only. A later independent YOE
    # clause ("... with at least 5+ years in leadership") is classified on its own
    # match, so its tool/domain/leadership wording must not leak into this match's
    # window and (mis)mark it contextual — the defect this guard fixes.
    next_clause = _NEXT_YOE_CLAUSE_RE.search(after)
    if next_clause:
        after = after[:next_clause.start()]
    preference_window = f"{before[-60:]} {match.group(0)} {after[:30]}"
    if _PREFERRED_YOE_RE.search(preference_window):
        return None
    matched = match.group(0)
    # Attribution guard. ``before`` never crosses a sentence/line boundary (see
    # ``_yoe_match_context``), so this only ever reads the years' own sentence.
    attribution = before[-80:]
    possessor = None
    for possessor in _THIRD_PARTY_YOE_RE.finditer(attribution):
        pass
    if possessor is not None and not _CANDIDATE_YOE_RE.search(
            attribution[possessor.end():]):
        return None
    if _COMBINED_YOE_RE.search(f"{attribution[-40:]} {matched} {after[:40]}"):
        return None
    match_context = f"{matched} {after[:80]}"
    contextual = bool(_CONTEXTUAL_YOE_RE.search(match_context))
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


def _is_pay_band(low: float, high: float, period: str | None) -> bool:
    """Whether ``low``-``high`` is credible as ONE pay band stated for ``period``.

    See ``_PERIOD_PAY_FLOOR`` for why both a per-period floor and a spread limit
    are needed and why they are set where they are.
    """
    if low <= 0 or high < low:
        return False
    ceiling = _PERIOD_PAY_CEILING.get(period or "")
    if ceiling is not None and high > ceiling:
        return False
    floor = _PERIOD_PAY_FLOOR.get(period or "")
    if floor is not None and high < floor:
        return False
    return high <= low * _BAND_SPREAD_LIMIT


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
        # BOUNDED, not `rfind`/`in`. `_TOTAL_TERMS` carries the bare token "ote"
        # (on-target earnings), and an unanchored scan finds it inside "rem-OTE-".
        # Because the nearest keyword to the number wins, a compensation paragraph
        # that says "this is a fully remote position" beat "base salary": the range
        # was then dropped entirely (`extract_salary_range` returns None) or filed
        # as total comp. `_bounded_phrase_matches` is this module's one spelling of
        # a bounded phrase — "ote" as a standalone word still matches.
        nearest_total = _last_bounded_start(before, _TOTAL_TERMS)
        nearest_salary = _last_bounded_start(before, _SALARY_TERMS)
        if nearest_total >= 0 or nearest_salary >= 0:
            has_total = nearest_total > nearest_salary
            has_salary = nearest_salary > nearest_total
        else:
            has_total = bool(_bounded_phrase_matches(after, _TOTAL_TERMS))
            has_salary = bool(_bounded_phrase_matches(after, _SALARY_TERMS))
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
        # Drop the BAND, not the whole fact: a compensation paragraph that also
        # states a small non-salary range (a stipend, an allowance) still has a
        # real salary band in it, and dropping only the implausible one keeps it.
        if not _is_pay_band(low, high, period):
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


# ---------------------------------------------------------------------------
# JD-body level evidence (Decision 3c) — a conservative, EXPLICIT-phrase-only
# fallback, never a guess. Unlike ``_LEVEL_RULES`` (which reads a bare seniority
# word from a short TITLE, where "senior"/"staff" alone is unambiguous), a full
# JD body is long free prose where a bare seniority word is far too noisy (e.g.
# "our senior leadership team", "you will mentor staff"). Each rule below
# therefore requires the word to be role-noun-qualified ("Staff Software
# Engineer") or in an explicit "<level>-level role/position" phrase, or a
# Google-style level code ("L6") — never a bare seniority word alone.
# ---------------------------------------------------------------------------
_JD_LEVEL_ROLE_RE = r"(?:software\s+)?(?:engineer|developer|programmer)\b"
_JD_BODY_LEVEL_RULES = [
    ("distinguished", re.compile(
        rf"\b(?:distinguished|fellow)\s+{_JD_LEVEL_ROLE_RE}|"
        r"\bthis (?:role|position) is (?:a\s+)?distinguished[- ]level\b|"
        r"\bdistinguished[- ]level (?:role|position)\b",
        re.I,
    )),
    ("senior_staff", re.compile(
        rf"\bsenior\s+staff\s+{_JD_LEVEL_ROLE_RE}|"
        r"\bthis (?:role|position) is (?:a\s+)?senior[- ]staff[- ]level\b|"
        r"\bsenior[- ]staff[- ]level (?:role|position)\b",
        re.I,
    )),
    ("principal", re.compile(
        rf"\bprincipal\s+{_JD_LEVEL_ROLE_RE}|"
        r"\bthis (?:role|position) is (?:a\s+)?principal[- ]level\b|"
        r"\bprincipal[- ]level (?:role|position)\b",
        re.I,
    )),
    ("staff", re.compile(
        rf"\bstaff\s+{_JD_LEVEL_ROLE_RE}|"
        r"\bthis (?:role|position) is (?:a\s+)?staff[- ]level\b|"
        r"\bstaff[- ]level (?:role|position)\b",
        re.I,
    )),
    ("senior", re.compile(
        r"\bthis (?:role|position) is (?:a\s+)?senior[- ]level\b|"
        r"\bsenior[- ]level (?:role|position)\b",
        re.I,
    )),
    ("mid", re.compile(
        r"\bthis (?:role|position) is (?:a\s+)?mid[- ]level\b|"
        r"\bmid[- ]level (?:role|position)\b",
        re.I,
    )),
    ("entry", re.compile(
        r"\bthis (?:role|position) is (?:an?\s+)?entry[- ]level\b|"
        r"\bentry[- ]level (?:role|position)\b",
        re.I,
    )),
]
# Google-style ladder codes ("L6"); bounded to a plausible IC range to avoid
# stray alphanumeric noise ("L1 support tier") reading as a level.
_JD_BODY_LEVEL_CODE_RE = re.compile(r"\bL([3-9]|10)\b")
_LEVEL_CODE_MAP = {
    3: "entry", 4: "mid", 5: "senior", 6: "staff", 7: "senior_staff",
    8: "principal", 9: "distinguished", 10: "distinguished",
}


def classify_level_from_jd_body(text: str | None) -> tuple[str, str | None]:
    """Conservative EXPLICIT JD-body level phrase -> ``(normalized, signal)``.

    Returns ``("unknown", None)`` when no explicit phrase is present — the same
    no-guessing rule used elsewhere (required YOE, salary). Never reads a bare
    seniority word alone (too noisy in free JD prose); only a role-noun-
    qualified phrase, an explicit "<level>-level role/position" phrase, or a
    Google-style level code counts as evidence.
    """
    blob = _source_text(text)
    for normalized, pattern in _JD_BODY_LEVEL_RULES:
        match = pattern.search(blob)
        if match:
            return normalized, match.group(0)
    code_match = _JD_BODY_LEVEL_CODE_RE.search(blob)
    if code_match:
        return _LEVEL_CODE_MAP[int(code_match.group(1))], code_match.group(0)
    return "unknown", None


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
# JD text. Negatives (explicit denials) win over positives (explicit offers), and
# an offer phrase inside a negation scope counts as a denial, not an offer.
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

# The denial phrases whose "sponsor" is a bare transitive VERB with no object of
# its own.  Those are the only ones that can attach to something that is not
# immigration at all — "we do not sponsor community events" matched `do not
# sponsor` and graded a confident denial, and the default policy DROPS denials,
# so a posting was deleted for a sentence about a street fair.
#
# Every OTHER phrase in ``_SPONSOR_NEGATIVE`` names "sponsorship" as the head
# noun (or names citizenship/green-card status outright), and there the object IS
# sponsorship, so no gate applies.  That asymmetry is measured, not stylistic:
# "This role does not offer sponsorship." carries no immigration word ANYWHERE in
# it, so gating every denial on context — the symmetric-looking rule — turns a
# real refusal into ``unknown``.  The dividing line is the bare verb, not the
# strength of the wording.
_SPONSOR_GENERIC_NEGATIVE = frozenset({
    "unable to sponsor", "not able to sponsor", "cannot sponsor",
    "can not sponsor", "will not sponsor", "does not sponsor", "do not sponsor",
})
# Immigration context for that gate.  Separate from ``_SPONSOR_CONTEXT_RE``
# because that one is anchored on "visa" SINGULAR, and the denials being gated
# here are routinely written with the plural ("we cannot sponsor visas at all").
# Widening the shared pattern instead would loosen the OFFER side's gate too,
# which is the direction this module does not move.
#
# It is deliberately the WIDER of the two patterns.  The two errors this gate can
# make are not equal: dropping a real denial hides it from the candidate at high
# confidence, while keeping a non-immigration one costs a ``review`` flag, so the
# gate is written to err toward keeping.  US work-authorization boilerplate is
# included for exactly that reason ("we do not sponsor. applicants must be
# authorized to work in the United States") — on its own that boilerplate is
# still never a denial, which ``_SPONSOR_NEGATIVE`` decides, not this pattern.
_SPONSOR_IMMIGRATION_RE = re.compile(
    r"\b(?:visas?|h-?1bs?|immigration|work\s+authoriz\w+|"
    r"authoriz\w+\s+to\s+work|green\s+cards?|permanent\s+residen(?:t|ts|cy)|"
    r"perm\s+process|employment\s+sponsorship|citizens?(?:hip)?|"
    r"sponsorship\s+transfers?)\b",
    re.I,
)
# How far either context gate reads around a phrase.
_SPONSOR_CONTEXT_WINDOW_CHARS = 120

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

# --- negation scope --------------------------------------------------------
# A phrase list can never enumerate every way an employer writes "no": the list
# above will always be one wording short, and a denial it does not literally
# contain used to fall through to the OFFER scan and be reported as an explicit
# offer (``does not currently offer visa sponsorship`` -> ``offer visa
# sponsorship``). Polarity is therefore decided STRUCTURALLY instead: an offer
# phrase found inside the scope of a negation cue is read as a denial OF THAT
# OFFER, whatever route the sentence took to get there.
#
# The scope is deliberately small — a NegEx-style bounded look-back, cut short at
# the nearest clause boundary — because the two errors are not symmetric. A false
# offer sends a candidate who needs sponsorship to an employer that said no in
# writing; a false denial hides a real job. ``unknown`` costs neither (it is kept
# and flagged for a human read), so every ambiguous read resolves there.
_SPONSOR_NEGATION_CUE_RE = re.compile(
    r"\b(?:not|no|never|none|cannot|unable|ineligible|without|nor|neither|"
    r"lacks?|lacking|"
    r"(?:do|does|did|is|are|was|were|has|have|had|ca|wo|would|could|should|must)"
    r"n[’']t)\b",
    re.I,
)
# Where a negation stops carrying. Sentence punctuation and contrastive
# conjunctions always end it; a comma/and/or ends it only when what follows
# starts a NEW clause (a subject, an auxiliary, or a sponsorship subject with its
# own verb) — so "we are not, at this time, able to offer visa sponsorship" stays
# one negated clause while "no relocation budget, and visa sponsorship is
# available" does not.
_SPONSOR_CLAUSE_BREAK_RE = re.compile(
    r"[.;:!?•|]|--|—|–"
    r"|\b(?:but|however|although|though|yet|whereas|while|nevertheless|"
    r"nonetheless|unless|otherwise|instead)\b"
    r"|(?:,|\band\b|\bor\b|\bplus\b)\s+(?:"
    r"(?:we|they|it|you|he|she|i|this|these|those|that|our|your|their|the|a|an|"
    r"candidates?|applicants?|employees?|employers?|positions?|roles?|"
    r"is|are|was|were|will|can|may|might|would|should|must|do|does|did|"
    r"has|have|had)\b"
    r"|(?:visas?|sponsorship|immigration|h-?1b|green\s+card|perm)\b"
    r"[^.;:!?]{0,40}?\b(?:is|are|will|can|may|would)\b)",
    re.I,
)
# "Sponsorship" has a second, unrelated legal sense: US export-control licensing
# (ITAR/EAR). "eligible to obtain the required authorizations without sponsorship
# for an export license" says nothing about immigration, but it used to score as
# an explicit denial — and because the default policy DROPS denials, a whole
# board of export-controlled roles could disappear silently. A sponsorship phrase
# whose sentence is export-control language AND carries no immigration word at
# all is not evidence either way.
_SPONSOR_EXPORT_CONTROL_RE = re.compile(
    r"\b(?:export[\s-]+(?:licen[cs]e[sd]?|control(?:led|s)?|"
    r"administration\s+regulations|compliance|classification|"
    r"authoriz\w+|restrictions?)"
    r"|itar|ear99|deemed\s+export|licen[cs]e\s+exception|"
    r"international\s+traffic\s+in\s+arms|export[- ]controlled)\b",
    re.I,
)
_SPONSOR_SENTENCE_BREAK_RE = re.compile(r"[.;:!?•|]")
# The subset of clause breaks that end a negation UNAMBIGUOUSLY: terminal
# punctuation, a dash, or a contrastive conjunction. Used only to decide whether
# a cue the bounded scope failed to reach was genuinely spent (see
# ``_sponsor_cue_out_of_reach``) — the comma/coordinator alternatives of
# ``_SPONSOR_CLAUSE_BREAK_RE`` are deliberately excluded, because those are the
# ones that fire inside an aside and strand a cue mid-sentence.
_SPONSOR_HARD_BREAK_RE = re.compile(
    r"[.;:!?•|]|--|—|–"
    r"|\b(?:but|however|although|though|yet|whereas|while|nevertheless|"
    r"nonetheless|unless|otherwise|instead)\b",
    re.I,
)
_SPONSOR_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'’./-]*", re.I)
_SPONSOR_TOPIC_RE = re.compile(
    r"\b(?:sponsor(?:s|ed|ing|ship)?|visas?|immigration|h-?1b|green\s+card|perm|"
    r"work\s+authorization|citizens?(?:hip)?|relocation)\b",
    re.I,
)
_SPONSOR_COORDINATOR_RE = re.compile(r"[,;]|\b(?:and|or|nor|plus)\b", re.I)
# Raw slice taken before the token budget does the real bounding.
_SPONSOR_LOOKBACK_CHARS = 160
# How far past the phrase the clause-break scan may read to recognize a restart.
_SPONSOR_LOOKAHEAD_CHARS = 60
# Words allowed between a cue and the phrase it negates ("not currently in a
# position to be able to offer visa sponsorship" is 8).
_SPONSOR_NEGATION_MAX_GAP_TOKENS = 8
# A negation of a negation is only read as such when the two cues are adjacent
# and nothing of substance sits between them ("it is not true that we cannot
# sponsor"). Two coordinated denials ("unable to sponsor ... and cannot sponsor")
# are two denials, not a double negative.
_SPONSOR_DOUBLE_NEGATION_MAX_GAP_TOKENS = 4

# --- scope limits: negating a UNIVERSAL is not a denial ----------------------
# Reading negation structurally fixed a real false-offer rate, but it over-reached
# on the single clearest offer shape a board writes: an offer, then a limit ON that
# offer. "we do sponsor visas … however we aren't able to sponsor visas for every
# role and every candidate" is a SPONSOR. The hedge sentence carries its own
# negated offer phrase, the negation scope read it as a denial, denial beat offer,
# and the whole employer graded `unknown` — invisible under `require_positive`,
# which is the one policy used by a candidate who NEEDS sponsorship. Returning zero
# where a real sponsor exists is the worst answer that filter can give.
#
# The distinction is logical, not lexical. ``not (for every X)`` denies the
# UNIVERSAL and therefore entails that SOME X are sponsored; ``does not sponsor``
# is the universal negation. Only the second is a denial. So a negation whose own
# clause quantifies over "every / each" — or hedges on a guarantee — limits the
# SCOPE of sponsorship and is not evidence of refusal.
#
# WHICH quantifier does that work is load-bearing, and the first cut of this rule
# got it wrong by accepting the bare word "all" alongside "every".
#
#   * "every" / "each" are DISTRIBUTIVE — they range over individuals one at a
#     time, so a negation has to outscope them (``¬∀x. sponsor(x)``) and the
#     sentence necessarily leaves individuals on BOTH sides. That is exactly what
#     licenses the inference that some roles ARE sponsored, and it is a limit on
#     an OFFER.
#   * "all" is number-neutral and also admits a COLLECTIVE/definite reading, under
#     which "for all new hires" means "for the new hires, as a class" and the
#     sentence is ``∀x. ¬sponsor(x)``. There the quantifier bounds the DENIAL's
#     own domain rather than an offer — a flat denial that happens to name the
#     population it covers — and nothing about sponsorship existing is entailed.
#     "We are unable to sponsor visas for all new hires" is that shape, and it is
#     addressed to precisely the reader who needs sponsorship.
#
# A quantifier that admits both readings is ambiguous, and this module resolves
# every ambiguity toward the cheaper error (see the negation-scope note above), so
# bare "all" must not DELETE a denial. It never needed to: every wording the
# scope-limit rule was written for says "every".
#
# The asymmetry of the original design — a scope limit can only REMOVE a denial,
# never create an offer — holds of the EVIDENCE lists by construction: a
# scope-limited phrase goes to its own list and is never counted as positive. It
# does NOT hold of the VERDICT, and nothing enforces it there. Deleting a denial
# dissolves the ``denial and positive -> review`` conflict branch in
# ``assess_sponsorship``, so the posting moves from ``review``/``unknown``/low to
# ``match``/``likely``/high and ``classify_visa`` returns "yes". One misread
# quantifier is a two-step promotion in the unsafe direction with no backstop
# under it, which is why this test is deliberately conservative and why
# ``QuantifiedDenialTests`` pins the verdict-level property directly.
_SPONSOR_SCOPE_LIMIT_RE = re.compile(
    r"\b(?:every(?:one|body)?|each|guarantee(?:s|d|ing)?)\b",
    re.I,
)
# Only a denial ABOUT SPONSORING can be scope-limited. A categorical eligibility
# statement ("us citizens only", "green card required") states who may hold the
# job at all; a nearby "all" does not soften it into a partial offer.
_SPONSOR_ACT_RE = re.compile(r"\bsponsor", re.I)
# How far the quantifier may sit from the phrase it bounds ("sponsor visas for
# every role" is 1; "cannot guarantee that we will sponsor visas" is 4).
_SPONSOR_SCOPE_LIMIT_MAX_GAP_TOKENS = 6

# --- the same ambiguity, out the other side: RECORD it, do not resolve it ------
# "Not a scope limit" is not the same claim as "a settled refusal", and collapsing
# the two put the ambiguity above straight back out the other side of the module.
# With `all` simply absent from the pattern, an `all`-bounded denial fell through
# to the ordinary denial path and graded ``no_match``/``unlikely``/HIGH with no
# review flag — silently dropped under BOTH visa policies, on a sentence the
# comment above calls ambiguous in so many words. "Our immigration team supports
# H-1B and green card cases, but we do not sponsor all roles" was deleted; the same
# sentence written with "every" was kept and flagged, and the quantifier was the
# whole difference. It only drops when no ``_SPONSOR_POSITIVE`` phrase survives the
# context gate, so the class is exactly "postings whose offer is phrased in words
# the list does not contain" — which a phrase list can never enumerate.
#
# So the ambiguity is now RECORDED, in the two layers where it actually lives:
#
#   * EVIDENCE — an `all`-bounded denial stays a DENIAL. It is never moved to
#     ``scope_limited``, never counted as positive, and never leaves the ``denial``
#     list, so every branch that could reach ``match``/``likely`` is preempted
#     exactly as before. No promotion is reachable through this pattern; that is
#     the property the narrowing above exists to protect, and it is untouched.
#   * VERDICT — the ``elif denial`` branch asserted ``high`` confidence from the
#     mere presence of a denial, without asking whether that denial's reading was
#     settled. That was the one place in this module where an ambiguity produced a
#     confident answer. A denial whose ONLY reading rests on an ambiguous
#     quantifier now lands ``review``/``unknown``/low — kept and flagged, where
#     every other ambiguity here already lands.
#
# One settled denial anywhere in the posting still wins outright: "…for all new
# hires. This role does not offer sponsorship." stays ``no_match``. And "at all"
# is excluded explicitly, because there "all" INTENSIFIES the denial rather than
# bounding it — "we cannot sponsor visas at all" is a flat refusal.
_SPONSOR_AMBIGUOUS_SCOPE_RE = re.compile(r"(?<!\bat\s)\ball\b", re.I)

# --- detection: a denial phrased in words neither list contains --------------
# Polarity is decided structurally, but DETECTION was still purely lexical: if no
# phrase from either tuple matched, the negation scope had nothing to act on and
# the posting classified ``unknown``.  "We do not offer relocation or visa
# sponsorship." is that hole — the denial phrases need "offer sponsorship"
# contiguous and the offer phrases need "offer visa sponsorship" contiguous, and
# a single coordinated object defeats both.
#
# The denial side gets the structural treatment the offer side already has: a
# bare sponsorship HEAD whose governing negation reaches it THROUGH AN OFFER VERB
# is a denial of that offer, whatever words sit between them.  Three bounds keep
# it from becoming a generic "cue … sponsorship" rule, which misfires badly:
#
#   * the OFFER VERB is required.  EEO copy — "we do not discriminate against
#     candidates who need visa sponsorship" — puts a cue five tokens from the
#     head and is NOT a denial; it has no offer verb between the two, and that is
#     the only thing that separates the two shapes;
#   * the window between the verb and the head is TIGHT (5 tokens), so the verb
#     has to plausibly govern the head;
#   * the scope is the module's existing ``_sponsor_negation`` — same clause
#     break, same budget — so a clause restart ends this rule exactly as it ends
#     every other one, and no third notion of "reach" enters the module.
#
# It is a FALLBACK only: a head already covered by a phrase from either tuple is
# left to the existing paths, byte for byte, so no wording that already had an
# answer gets a new one.
_SPONSOR_HEAD_RE = re.compile(
    r"\b(?:(?:visa|immigration|employment|employer|h-?1b|green\s+card)\s+)?"
    r"sponsorship\b",
    re.I,
)
_SPONSOR_OFFER_VERB_RE = re.compile(
    r"\b(?:offer(?:s|ed|ing)?|provid(?:e|es|ed|ing)|extend(?:s|ed|ing)?|"
    r"grant(?:s|ed|ing)?|support(?:s|ed|ing)?)\b",
    re.I,
)
# How far the offer verb may sit from the head it offers ("offer relocation or
# visa sponsorship" is 2).  Deliberately tighter than the negation budget.
_SPONSOR_OFFER_VERB_MAX_GAP_TOKENS = 5
_SPONSOR_OFFER_VERB_DENIAL = "negated offer verb"

# --- hedged offers: modality is not a guarantee ------------------------------
# The mirror error the same canary found: "limited immigration sponsorship may be
# available" graded `likely` while the unhedged offer above graded `unknown`, so
# the two labels were swapped relative to LESSONS.md ("a discretionary … must land
# unclear"). An offer stated only under a possibility modal, a discretion clause or
# a quantity hedge is not an unhedged offer; it is `unknown`, which keeps the
# posting and flags it. With both rules in place the grading is monotone in offer
# strength: unhedged offer > hedged offer > silence, and a scope limit moves
# nothing.
_SPONSOR_HEDGE_RE = re.compile(
    r"\b(?:may|might|could|possibl[ey]|potentially|limited|"
    r"discretion(?:ary)?|consider(?:s|ed|ation)?)\b"
    r"|\bcase[- ]by[- ]case\b",
    re.I,
)
# A hedge governs an offer only when it is adjacent to it inside the same clause;
# beyond that it is a different statement ("we sponsor H-1B visas, and relocation
# may be discussed").
_SPONSOR_HEDGE_MAX_GAP_TOKENS = 3


def _sponsor_clause_scope(source: str, start: int) -> str:
    """The negation-carrying text that runs up to ``start``.

    The break scan reads a little PAST ``start`` (a clause restart such as
    ", and visa sponsorship is available" is only recognizable once its verb is
    visible) but only breaks that begin before ``start`` can end the scope.
    """
    window_start = max(0, start - _SPONSOR_LOOKBACK_CHARS)
    offset = start - window_start
    probe = source[window_start:start + _SPONSOR_LOOKAHEAD_CHARS]
    cut = 0
    for break_match in _SPONSOR_CLAUSE_BREAK_RE.finditer(probe):
        if break_match.start() >= offset:
            break
        cut = min(break_match.end(), offset)
    return probe[cut:offset]


def _sponsor_last_cue(scope: str):
    last = None
    for last in _SPONSOR_NEGATION_CUE_RE.finditer(scope):
        pass
    return last


def _sponsor_gap_is_bare(gap: str) -> bool:
    """True when only a few function words separate two negation cues."""
    return (
        len(_SPONSOR_TOKEN_RE.findall(gap))
        <= _SPONSOR_DOUBLE_NEGATION_MAX_GAP_TOKENS
        and not _SPONSOR_TOPIC_RE.search(gap)
        and not _SPONSOR_COORDINATOR_RE.search(gap)
    )


def _sponsor_negation(source: str, start: int):
    """Return ``(scope, cue)`` for the negation governing ``start``, else None."""
    scope = _sponsor_clause_scope(source, start)
    cue = _sponsor_last_cue(scope)
    if cue is None:
        return None
    gap = scope[cue.end():]
    if len(_SPONSOR_TOKEN_RE.findall(gap)) > _SPONSOR_NEGATION_MAX_GAP_TOKENS:
        return None
    return scope, cue


def _sponsor_double_negated(scope: str, cue) -> bool:
    """True when ``cue`` is itself sitting inside another negation."""
    before = scope[:cue.start()]
    prior = _sponsor_last_cue(before)
    return prior is not None and _sponsor_gap_is_bare(before[prior.end():])


def _sponsor_sentence_head(source: str, start: int) -> str:
    """The text from the start of ``start``'s sentence up to ``start``."""
    left = 0
    for break_match in _SPONSOR_SENTENCE_BREAK_RE.finditer(source, 0, start):
        left = break_match.end()
    return source[left:start]


def _sponsor_cue_out_of_reach(source: str, start: int) -> bool:
    """True when a negation cue precedes an OFFER phrase but cannot govern it.

    Both bounds on the negation scope — the clause break and the token budget —
    can put a cue the sentence plainly contains out of the phrase's reach, and
    the failure was NOT symmetric: an unreachable cue left the offer phrase
    scored as an explicit OFFER rather than as silence, so a denial written with
    a parenthetical in the middle of it ("We are unable, given <clause>, to
    offer visa sponsorship.") graded ``likely``/``high``/``match``.

    This is the EVIDENCE half of the repair — the same separation the
    quantifier fix used: the reading is recorded as unsettled here, and only the
    VERDICT layer's confidence changes.  Neither bound is widened, so the
    clause break still does the job it was written for.

    Two shapes must NOT be demoted, and both are measured rather than assumed:

    * the offer phrase OPENS its own clause ("There is no relocation budget, and
      visa sponsorship is available"). There the break that cut the scope is the
      phrase's own subject boundary and the earlier cue belongs to the previous
      clause.  Measured, that shape leaves ``_sponsor_clause_scope`` EMPTY,
      while a phrase stranded mid-clause leaves a non-empty remnant;
    * the negation is SPENT before the phrase by an unambiguous clause break —
      terminal punctuation, a dash, or a contrastive conjunction ("we cannot
      guarantee an outcome, but we do provide visa sponsorship"). Those breaks
      end a negation on any reading, so the cue is not "out of reach", it is
      finished.  The comma/coordinator breaks are excluded from that set on
      purpose: they are exactly the ones that fire inside an aside.
    """
    if not _sponsor_clause_scope(source, start).strip():
        return False
    head = _sponsor_sentence_head(source, start)
    cue = _sponsor_last_cue(head)
    if cue is None:
        return False
    return not _SPONSOR_HARD_BREAK_RE.search(head[cue.end():])


def _sponsor_sentence(source: str, start: int, end: int) -> str:
    """The sentence a phrase match sits in."""
    left = 0
    for break_match in _SPONSOR_SENTENCE_BREAK_RE.finditer(source, 0, start):
        left = break_match.end()
    right = _SPONSOR_SENTENCE_BREAK_RE.search(source, end)
    return source[left:right.start() if right else len(source)]


def _sponsor_is_export_control(source: str, start: int, end: int) -> bool:
    """True when this "sponsorship" word means export licensing, not immigration.

    Requires BOTH an export-control cue and the complete absence of immigration
    context in the same sentence, so a JD that discusses export licences and visa
    sponsorship in one breath keeps its immigration evidence.
    """
    sentence = _sponsor_sentence(source, start, end)
    return bool(
        _SPONSOR_EXPORT_CONTROL_RE.search(sentence)
        and not _SPONSOR_CONTEXT_RE.search(sentence)
    )


def _sponsor_denial_is_negated(source: str, start: int) -> bool:
    """True when a DENIAL phrase at ``start`` is itself negated."""
    scope = _sponsor_clause_scope(source, start)
    cue = _sponsor_last_cue(scope)
    return cue is not None and _sponsor_gap_is_bare(scope[cue.end():])


def _sponsor_clause_tail(source: str, end: int) -> str:
    """The clause text that runs FORWARD from ``end`` to the next clause break.

    The mirror of ``_sponsor_clause_scope``: a qualifier usually FOLLOWS the phrase
    it bounds ("sponsor visas for every role"), so both directions are needed.
    """
    probe = source[end:end + _SPONSOR_LOOKBACK_CHARS]
    stop = _SPONSOR_CLAUSE_BREAK_RE.search(probe)
    return probe[:stop.start()] if stop else probe


def _sponsor_cue_within(text: str, pattern, budget: int, *, backward: bool) -> bool:
    """Whether ``pattern`` fires inside ``text`` close enough to govern the phrase.

    ``text`` is the clause on one side of the phrase; ``backward`` says which end
    of it abuts the phrase. A cue governs only when few tokens and no coordinator
    separate the two — the same adjacency test the double-negation check uses, so a
    coordinated second statement ("…, and relocation may be discussed") cannot
    reach back across the comma.
    """
    for cue in pattern.finditer(text):
        gap = text[cue.end():] if backward else text[:cue.start()]
        if (len(_SPONSOR_TOKEN_RE.findall(gap)) <= budget
                and not _SPONSOR_COORDINATOR_RE.search(gap)):
            return True
    return False


def _sponsor_quantifier_bounds(source: str, start: int, end: int, pattern) -> bool:
    """True when ``pattern`` quantifies the negation around a sponsorship phrase.

    The reading machinery both quantifier questions share — "is this a limit on an
    offer?" and "is this denial's own reading settled?" — differ only in WHICH
    quantifier they look for, so the adjacency rules stay in one place.

    Applies to phrases about the ACT of sponsoring: a categorical eligibility rule
    ("us citizens only", "green card required") states who may hold the job at all,
    and a nearby quantifier does not bound it.
    """
    if not _SPONSOR_ACT_RE.search(source[start:end]):
        return False
    if _sponsor_cue_within(
            _sponsor_clause_tail(source, end), pattern,
            _SPONSOR_SCOPE_LIMIT_MAX_GAP_TOKENS, backward=False):
        return True
    # Backward, the quantifier only counts INSIDE the negation it bounds — it has
    # to sit after the cue. Otherwise a plain requirement whose subject happens to
    # be "all" ("all roles require work authorization without sponsorship") would
    # read as a partial offer and a real denial would stop being one.
    scope = _sponsor_clause_scope(source, start)
    cue = _sponsor_last_cue(scope)
    if cue is None:
        return False
    return _sponsor_cue_within(
        scope[cue.end():], pattern,
        _SPONSOR_SCOPE_LIMIT_MAX_GAP_TOKENS, backward=True)


def _sponsor_scope_limited(source: str, start: int, end: int) -> bool:
    """True when the negation around a sponsorship phrase bounds it, not denies it.

    ``not … for every role`` negates a UNIVERSAL and so entails that some roles are
    sponsored; ``does not sponsor`` is the universal negation. Only the second is a
    denial.

    Only DISTRIBUTIVE quantifiers count (``every``/``each``, plus an explicit
    ``guarantee`` hedge). Bare ``all`` also has a collective reading under which
    the quantifier bounds the denial's own domain rather than an offer — see
    ``_SPONSOR_SCOPE_LIMIT_RE`` — so it is not a scope limit here.
    """
    return _sponsor_quantifier_bounds(source, start, end, _SPONSOR_SCOPE_LIMIT_RE)


def _sponsor_scope_unsettled(source: str, start: int, end: int) -> bool:
    """True when a denial's reading rests on a quantifier that means either thing.

    ``all`` is number-neutral: "we do not sponsor all roles" is a limit on an offer
    read distributively and a flat refusal read collectively, and the sentence does
    not settle which. The phrase stays a DENIAL either way — this only says the
    denial cannot support a CONFIDENT verdict on its own (see
    ``_SPONSOR_AMBIGUOUS_SCOPE_RE``).
    """
    return _sponsor_quantifier_bounds(source, start, end,
                                      _SPONSOR_AMBIGUOUS_SCOPE_RE)


def _sponsor_window(source: str, start: int, end: int) -> str:
    """The text either context gate reads around a phrase match."""
    return source[max(0, start - _SPONSOR_CONTEXT_WINDOW_CHARS):
                  end + _SPONSOR_CONTEXT_WINDOW_CHARS]


def _sponsor_denial_is_immigration(phrase: str, source: str,
                                   start: int, end: int) -> bool:
    """Whether a DENIAL phrase is about immigration rather than some other sponsee.

    Only the bare-verb phrases are gated (see ``_SPONSOR_GENERIC_NEGATIVE``);
    every other denial names sponsorship itself and passes unconditionally.
    """
    if phrase not in _SPONSOR_GENERIC_NEGATIVE:
        return True
    return bool(_SPONSOR_IMMIGRATION_RE.search(
        _sponsor_window(source, start, end)))


def _sponsor_offer_is_hedged(source: str, start: int, end: int) -> bool:
    """True when an OFFER phrase is stated only under a hedge.

    A possibility modal, a discretion clause or a quantity hedge ("limited …",
    "… may be available", "at our discretion", "case-by-case") makes the offer a
    maybe rather than a statement. LESSONS.md requires those to land ``unknown``.
    """
    return (
        _sponsor_cue_within(
            _sponsor_clause_scope(source, start), _SPONSOR_HEDGE_RE,
            _SPONSOR_HEDGE_MAX_GAP_TOKENS, backward=True)
        or _sponsor_cue_within(
            _sponsor_clause_tail(source, end), _SPONSOR_HEDGE_RE,
            _SPONSOR_HEDGE_MAX_GAP_TOKENS, backward=False)
    )


class _SponsorSpan:
    """A structurally detected denial, duck-typing the ``re.Match`` API used here.

    Only ``start()``/``end()`` are read by the sponsorship code, and the span has
    to run from the negation CUE to the head — not from the head — or
    ``_sponsor_denial_is_negated`` reads this rule's own cue as an outer negation
    and grades the denial as a double negative.
    """

    __slots__ = ("_start", "_end")

    def __init__(self, start: int, end: int) -> None:
        self._start, self._end = start, end

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end


def _sponsor_offer_verb_denials(source: str, covered: list[tuple[int, int]]):
    """Denials the phrase lists cannot see: a negated OFFER VERB plus a bare head.

    ``covered`` is the span of every ``_SPONSOR_NEGATIVE``/``_SPONSOR_POSITIVE``
    match in ``source``.  A head inside one of those spans already has an answer
    from the existing paths and is left to them, so this rule only ever ADDS
    detection for wordings that previously matched nothing at all.
    """
    for head in _SPONSOR_HEAD_RE.finditer(source):
        if any(head.start() < end and start < head.end()
               for start, end in covered):
            continue
        negation = _sponsor_negation(source, head.start())
        if negation is None:
            continue
        scope, cue = negation
        between = scope[cue.end():]
        verb = None
        for verb in _SPONSOR_OFFER_VERB_RE.finditer(between):
            pass
        if verb is None:
            continue
        if (len(_SPONSOR_TOKEN_RE.findall(between[verb.end():]))
                > _SPONSOR_OFFER_VERB_MAX_GAP_TOKENS):
            continue
        # ``scope`` ends exactly at the head, so the cue's absolute offset is
        # measured back from there.
        yield _SponsorSpan(head.start() - len(scope) + cue.start(), head.end())


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


def _last_bounded_start(text: str, phrases) -> int:
    """Offset of the LAST bounded occurrence of any phrase, or -1 (bounded ``rfind``)."""
    return max((match.start() for _phrase, match
                in _bounded_phrase_matches(text, phrases)), default=-1)


def assess_sponsorship(text: str | None) -> dict:
    """Return an explainable tri-state sponsorship assessment.

    Generic words such as "we sponsor" are positive only when their surrounding
    sentence also contains immigration/work-authorization context. This prevents
    employee-program or event sponsorship copy from passing a hard visa gate.

    An offer phrase inside a negation scope (see ``_sponsor_negation``) is counted
    as a DENIAL of that offer rather than an offer, so a denial the phrase list
    never anticipated cannot be reported as an explicit offer. Text that negates a
    negation is read neither way: it returns ``unknown``, which is kept and
    flagged rather than acted on.

    Two refinements keep that structural read from swallowing real offers, and
    grade the result on OFFER STRENGTH rather than on whichever polarity appeared
    last:

    * a negation that quantifies over a DISTRIBUTIVE "every / each" (or hedges a
      guarantee) LIMITS the scope of sponsorship instead of refusing it, so it
      neither denies nor offers — "we do sponsor visas, but not for every role" is
      a sponsor. Bare "all" does not qualify: it is number-neutral, so "unable to
      sponsor visas for all new hires" reads either as that limit or as a flat
      denial naming its population. Such a denial is KEPT as a denial (it can never
      be promoted to an offer) but cannot on its own carry a confident verdict, so
      alone it lands ``review``/``unknown``/low rather than being dropped silently;
    * an offer stated only under a possibility modal, a discretion clause or a
      quantity hedge is a HEDGED offer and lands ``unknown``, not ``likely``.

    An offer phrase whose sentence carries a negation cue the bounded scope
    cannot REACH is not an offer either: neither bound is widened, the cue is
    recorded as unreachable, and the posting lands ``unknown`` — kept and
    flagged — instead of being asserted as an explicit offer.

    So an unhedged offer outranks a hedged one, a hedged one outranks silence, and
    a scope limit moves nothing — while a SETTLED denial still wins over
    everything.
    """
    source = _clean(_source_text(text))
    export_control = False

    def _immigration_sense(match: re.Match) -> bool:
        nonlocal export_control
        if _sponsor_is_export_control(source, match.start(), match.end()):
            export_control = True
            return False
        return True

    listed = [
        *_bounded_phrase_matches(source, _SPONSOR_NEGATIVE),
        *_bounded_phrase_matches(source, _SPONSOR_POSITIVE),
    ]
    covered = [(match.start(), match.end()) for _phrase, match in listed]
    negative_matches = [
        (phrase, match)
        for phrase, match in _bounded_phrase_matches(source, _SPONSOR_NEGATIVE)
        if _immigration_sense(match)
    ] + [
        (_SPONSOR_OFFER_VERB_DENIAL, match)
        for match in _sponsor_offer_verb_denials(source, covered)
        if _immigration_sense(match)
    ]
    negative: list[str] = []
    scope_limited: list[str] = []
    unsettled: list[str] = []
    ambiguous = False
    for phrase, negative_match in negative_matches:
        if _sponsor_denial_is_negated(source, negative_match.start()):
            ambiguous = True
            continue
        if _sponsor_scope_limited(
                source, negative_match.start(), negative_match.end()):
            if phrase not in scope_limited:
                scope_limited.append(phrase)
            continue
        if _sponsor_scope_unsettled(
                source, negative_match.start(), negative_match.end()):
            if phrase not in unsettled:
                unsettled.append(phrase)
            continue
        if not _sponsor_denial_is_immigration(
                phrase, source, negative_match.start(), negative_match.end()):
            # A bare-verb "sponsor" with no immigration anywhere near it is
            # about something else entirely. Dropped from the evidence exactly
            # as a non-immigration OFFER phrase is, so the posting reads
            # `unknown` — kept and flagged — instead of being deleted.
            continue
        if phrase not in negative:
            negative.append(phrase)
    positive: list[str] = []
    hedged_offer: list[str] = []
    negated_offer: list[str] = []
    unreachable_cue: list[str] = []
    for phrase, positive_match in _bounded_phrase_matches(source, _SPONSOR_POSITIVE):
        if not _immigration_sense(positive_match):
            continue
        if any(
            positive_match.start() < negative_match.end()
            and negative_match.start() < positive_match.end()
            for _negative_phrase, negative_match in negative_matches
        ):
            continue
        if phrase not in _SPONSOR_STRONG_POSITIVE:
            if not _SPONSOR_CONTEXT_RE.search(_sponsor_window(
                    source, positive_match.start(), positive_match.end())):
                continue
        negation = _sponsor_negation(source, positive_match.start())
        if negation is not None:
            scope, cue = negation
            if _sponsor_double_negated(scope, cue):
                ambiguous = True
            elif _sponsor_scope_limited(
                    source, positive_match.start(), positive_match.end()):
                if phrase not in scope_limited:
                    scope_limited.append(phrase)
            elif _sponsor_scope_unsettled(
                    source, positive_match.start(), positive_match.end()):
                if phrase not in unsettled:
                    unsettled.append(phrase)
            elif phrase not in negated_offer:
                negated_offer.append(phrase)
            continue
        if _sponsor_cue_out_of_reach(source, positive_match.start()):
            # A cue the sentence contains but the bounded scope cannot reach.
            # Not an offer, and not asserted as a denial either: recorded as
            # unsettled so the verdict layer keeps and flags the posting.
            if phrase not in unreachable_cue:
                unreachable_cue.append(phrase)
            continue
        if _sponsor_offer_is_hedged(
                source, positive_match.start(), positive_match.end()):
            if phrase not in hedged_offer:
                hedged_offer.append(phrase)
            continue
        if phrase not in positive:
            positive.append(phrase)

    # A phrase read as settled ANYWHERE outranks the same phrase read as bounded
    # elsewhere: one flat refusal is enough, however many quantified ones surround it.
    unsettled = [phrase for phrase in unsettled
                 if phrase not in negative and phrase not in negated_offer]
    settled = [*negative, *negated_offer]
    denial = [*settled, *unsettled]
    # An offer phrase with an unreachable cue in front of it is a POSSIBLE
    # denial, so it conflicts with a real offer elsewhere the way a denial does.
    # It is deliberately NOT part of ``denial``: a settled refusal must keep
    # winning outright, and letting an unsettled reading weaken one would be the
    # promotion this module refuses to make.
    if (denial or unreachable_cue) and (positive or hedged_offer):
        decision, verdict, confidence = "review", "unknown", "low"
        reason = "Conflicting sponsorship offer and denial language."
    elif settled:
        decision, verdict, confidence = "no_match", "unlikely", "high"
        reason = (
            "The posting explicitly denies sponsorship." if negative
            else "The posting negates its own sponsorship offer language."
        )
    elif unsettled:
        decision, verdict, confidence = "review", "unknown", "low"
        reason = ("The posting's only denial is bounded by a quantifier that reads "
                  "either way, so it is not read as a settled refusal.")
    elif ambiguous:
        decision, verdict, confidence = "review", "unknown", "low"
        reason = ("Double-negated sponsorship language; the posting is not read "
                  "either way.")
    elif positive:
        decision, verdict, confidence = "match", "likely", "high"
        reason = "The posting explicitly offers immigration sponsorship."
    elif hedged_offer:
        decision, verdict, confidence = "review", "unknown", "low"
        reason = ("The posting's only sponsorship offer is hedged (discretionary "
                  "or limited), so it is not read as an offer.")
    elif unreachable_cue:
        decision, verdict, confidence = "review", "unknown", "low"
        reason = ("The posting's only sponsorship offer sits behind a negation "
                  "the clause scope cannot resolve, so it is not read as an "
                  "offer.")
    elif scope_limited:
        decision, verdict, confidence = "review", "unknown", "low"
        reason = ("The posting limits the SCOPE of sponsorship without saying "
                  "whether it sponsors at all.")
    elif export_control:
        decision, verdict, confidence = "review", "unknown", "low"
        reason = ("The posting's only sponsorship wording is export-control "
                  "licensing, not immigration.")
    else:
        decision, verdict, confidence = "review", "unknown", "unknown"
        reason = "The posting does not provide decisive sponsorship evidence."
    rule_ids = [
        *(f"sponsorship.negative.{phrase}" for phrase in negative),
        *(f"sponsorship.negated_offer.{phrase}" for phrase in negated_offer),
        *(f"sponsorship.unsettled_denial.{phrase}" for phrase in unsettled),
        *(f"sponsorship.unreachable_cue.{phrase}" for phrase in unreachable_cue),
        *(f"sponsorship.scope_limit.{phrase}" for phrase in scope_limited),
        *(["sponsorship.ambiguous.double_negation"] if ambiguous else []),
        *(["sponsorship.non_immigration.export_control"] if export_control else []),
        *(f"sponsorship.hedged_offer.{phrase}" for phrase in hedged_offer),
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
        "evidence": [
            *negative,
            *(f"negated: {phrase}" for phrase in negated_offer),
            *(f"unsettled: {phrase}" for phrase in unsettled),
            *(f"unreachable-cue: {phrase}" for phrase in unreachable_cue),
            *(f"scope-limited: {phrase}" for phrase in scope_limited),
            *(f"hedged: {phrase}" for phrase in hedged_offer),
            *positive,
        ],
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
    offer, and a negated offer counts as a denial), an explicit offer -> ``likely``,
    otherwise ``unknown``. Advisory only — always confirm with the employer before
    relying on it.
    """
    return assess_sponsorship(text)["verdict"]


# ---------------------------------------------------------------------------
# Application meta.yaml layer (the flat, human-facing schema v6).
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
    """Collapse a rich salary fact (possibly multi-band) to one ANNUAL min/max.

    The collapse stitches the LOW of one band to the HIGH of another, so the pair
    it hands back is one no posting ever stated. Per-band plausibility cannot
    see that — two individually sane bands still collapse to a nonsense pair when
    they describe different things. When the stitched ends land more than an
    order of magnitude apart there is no way to tell which end is the salary, so
    report NEITHER: the row then reads "none parsed", which the reader can
    resolve from the JD, instead of a band the posting does not contain.

    The unit is part of the value. ``salary_range`` is defined as posted pay in
    USD/**year** (``METADATA_FIELDS`` / the schema-v6 ``meta.yaml`` field), so a
    band stated for any other period is not a value this field can carry, and the
    only correct answer is REFUSAL — not the hourly number, and not an annualised
    one. Annualising would have to invent an hours-per-year figure the posting
    never stated (2080 h assumes full-time FTE, which is exactly wrong for the
    intern, contract and part-time bands this path sees), and the result would be
    stamped ``source: job_description`` / ``confidence: high`` and shown to the
    user as posted pay. Nothing is lost by refusing: ``extract_salary_range``
    still returns the band with its ``period``, so a consumer that wants hourly
    pay can read it there.

    This is why "prefer the annual band" is not enough: preference silently
    degrades to the hourly band once ``_is_pay_band`` rejects every annual
    candidate, which publishes e.g. an intern's ``$30 - $45`` as an annual salary
    — a plausible-looking number in the wrong unit, which is worse than an
    obviously garbled one because nothing about it looks wrong.
    """
    bands = fact.get("bands")
    if isinstance(bands, list) and bands:
        annual = [b for b in bands if isinstance(b, dict) and b.get("period") == "year"]
        if not annual:
            return None, None
        mins = [b["min"] for b in annual if b.get("min") is not None]
        maxs = [b["max"] for b in annual if b.get("max") is not None]
        low = min(mins) if mins else None
        high = max(maxs) if maxs else None
        if (low is not None and high is not None
                and low > 0 and high > low * _BAND_SPREAD_LIMIT):
            return None, None
        return low, high
    if fact.get("period") != "year":
        return None, None
    return fact.get("min"), fact.get("max")


def _fact_currency(fact: dict) -> str | None:
    """The one currency a salary fact states, or ``None`` when its bands disagree."""
    bands = fact.get("bands")
    if isinstance(bands, list) and bands:
        codes = {
            band.get("currency") for band in bands
            if isinstance(band, dict) and band.get("period") == "year"
            and band.get("currency")
        }
        return next(iter(codes)) if len(codes) == 1 else None
    currency = fact.get("currency")
    return str(currency) if currency else None


def _bare_salary(description: str, supplied: dict | None) -> dict | None:
    """A flat ``{min, max, currency, period, confidence, source}`` salary, or ``None``.

    THE UNIT TRAVELS WITH THE NUMBER. It used to be dropped here, and the two
    routes into this field do not agree on what the number means, so dropping it
    silently mixed two scales in one column:

    * the JD route is annual by construction — ``_salary_envelope`` refuses any
      band the posting did not state per year (see its docstring for why it
      refuses rather than annualising);
    * the AGGREGATOR route is whatever the board's structured pay field said.
      ``common.provided_salary_range`` accepts hour/day/week/month/year and
      only ever emits a range that carries BOTH an explicit currency and an
      explicit period — so a contract role's ``{30, 35, hour, USD}`` arrived
      here fully labelled and left as a bare ``{30, 35}``, which the discovery
      table printed as ``30-35``, pixel-identical to a $30k-$35k annual band.
      Nothing downstream could tell a $30/hour role from a $30k one.

    Carrying ``currency`` and ``period`` through costs two keys and makes the
    unit readable at every consumer (``search_jobs._format_comp`` renders it).
    A JD band with no single agreed currency reports none rather than guessing.
    """
    fact = extract_salary_range(description)
    if fact:
        low, high = _salary_envelope(fact)
        if low is not None or high is not None:
            currency = _fact_currency(fact)
            return {
                "min": _num_or_none(low),
                "max": _num_or_none(high),
                # ``_salary_envelope`` returns a value only for an ANNUAL band.
                "period": "year",
                **({"currency": currency} if currency else {}),
                "confidence": "high",
                "source": "job_description",
            }
    if isinstance(supplied, dict):
        low, high = supplied.get("min"), supplied.get("max")
        if low is not None or high is not None:
            period = supplied.get("period")
            currency = supplied.get("currency")
            return {
                "min": _num_or_none(low),
                "max": _num_or_none(high),
                **({"period": str(period)} if period else {}),
                **({"currency": str(currency)} if currency else {}),
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
            # Decision 3c: title and YOE are BOTH silent — a conservative,
            # explicit JD-body level phrase (never a bare seniority word alone)
            # is a low-confidence fill of last resort, ahead of the "generic"
            # unknown fallback. Never changes occupation; a phrase-conflict-
            # with-title review flag is handled by scoring.py (has the profile's
            # target band, which this config-free module intentionally lacks).
            jd_level, _jd_signal = classify_level_from_jd_body(description)
            if jd_level != "unknown":
                normalized = jd_level
                level_source, level_confidence = "job_description", "low"
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
# Validation (schema v6 is strict; legacy v5 validation exists only for the
# checksum-guarded v5 -> v6 migration planner).
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


_ISO_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)?$")


def _validate_progress(
    value: Any,
    status: Any,
    path: str,
    *,
    schema_version: int = APPLICATION_SCHEMA_VERSION,
) -> list[str]:
    """Validate the required per-job ``progress`` summary.

    ``phase``/``state`` are enum-gated; phase ``other`` requires a non-empty
    ``calendar_items`` is an ordered list of unique calendar entry ids in v6;
    legacy v5 accepts the retired scalar ``calendar_item`` only for migration;
    ``updated_at`` (tool-stamped, never invented) must be ISO-8601;
    ``source.kind`` is manual|email and an email source requires a ``ref``
    (the neutral stored message key). The workflow state must agree with the
    coarse status: rejected/ignored jobs are exactly ``closed``, active jobs
    are never ``closed``.
    """
    if not isinstance(value, dict):
        return [
            f"{path} is required and must be a mapping "
            f"(schema v{schema_version})"
        ]
    errors: list[str] = []
    phase = value.get("phase")
    if phase not in PROGRESS_PHASES:
        errors.append(f"{path}.phase must be one of {', '.join(PROGRESS_PHASES)}")
    state = value.get("state")
    if state not in PROGRESS_STATES:
        errors.append(f"{path}.state must be one of {', '.join(PROGRESS_STATES)}")
    label = value.get("label")
    if label is not None and not isinstance(label, str):
        errors.append(f"{path}.label must be a string")
    if phase == "other" and not str(label or "").strip():
        errors.append(f"{path}.label is required when phase is 'other'")
    calendar_keys: tuple[str, ...]
    if schema_version == LEGACY_APPLICATION_SCHEMA_VERSION:
        calendar_keys = ("calendar_item",)
        calendar_item = value.get("calendar_item")
        if calendar_item not in (None, ""):
            if (
                not isinstance(calendar_item, str)
                or not CALENDAR_ITEM_RE.match(calendar_item)
            ):
                errors.append(
                    f"{path}.calendar_item must be a calendar entry id "
                    "(cal-<lowercase-slug>)")
    else:
        calendar_keys = ("calendar_items",)
        if "calendar_item" in value:
            errors.append(
                f"{path}.calendar_item is not allowed in schema v6; use the "
                "ordered calendar_items list (migrate_to_v6.py)")
        calendar_items = value.get("calendar_items")
        if calendar_items is not None:
            if not isinstance(calendar_items, list):
                errors.append(f"{path}.calendar_items must be a list")
            else:
                seen_calendar_items: set[str] = set()
                for index, calendar_id in enumerate(calendar_items):
                    item_path = f"{path}.calendar_items[{index}]"
                    if (
                        not isinstance(calendar_id, str)
                        or not CALENDAR_ITEM_RE.match(calendar_id)
                    ):
                        errors.append(
                            f"{item_path} must be a calendar entry id "
                            "(cal-<lowercase-slug>)")
                        continue
                    if calendar_id in seen_calendar_items:
                        errors.append(
                            f"{item_path} duplicates calendar entry id "
                            f"{calendar_id!r}")
                    seen_calendar_items.add(calendar_id)
    updated_at = value.get("updated_at")
    if updated_at not in (None, ""):
        if not isinstance(updated_at, str) or not _ISO_TIMESTAMP_RE.match(updated_at):
            errors.append(f"{path}.updated_at must be an ISO-8601 timestamp")
    source = value.get("source")
    if source is not None:
        if not isinstance(source, dict):
            errors.append(f"{path}.source must be a mapping")
        else:
            kind = source.get("kind")
            if kind not in PROGRESS_SOURCE_KINDS:
                errors.append(
                    f"{path}.source.kind must be one of "
                    f"{', '.join(PROGRESS_SOURCE_KINDS)}")
            ref = source.get("ref")
            if ref is not None and not isinstance(ref, str):
                errors.append(f"{path}.source.ref must be a string")
            if kind == "email" and not str(ref or "").strip():
                errors.append(
                    f"{path}.source.ref is required for an email source "
                    "(the neutral stored message key)")
    unknown = [
        key for key in value
        if key not in ("phase", "state", "label", *calendar_keys,
                       "updated_at", "source")
        and not (schema_version == APPLICATION_SCHEMA_VERSION
                 and key == "calendar_item")
    ]
    if unknown:
        errors.append(f"{path} has unknown key(s): {', '.join(sorted(unknown))}")
    # Coarse-status coupling: closed <=> rejected/ignored.
    if state in PROGRESS_STATES:
        if status in CLOSED_STATUSES and state != "closed":
            errors.append(
                f"{path}.state must be 'closed' when status is {status!r}")
        if state == "closed" and status not in CLOSED_STATUSES:
            errors.append(
                f"{path}.state 'closed' requires status rejected or ignored")
    return errors


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


def validate_job_metadata(
    record: dict,
    *,
    prefix: str = "",
    schema_version: int = APPLICATION_SCHEMA_VERSION,
) -> list[str]:
    """Validate the per-posting metadata of one ``jobs`` entry."""
    lead = f"{prefix}." if prefix else ""
    errors: list[str] = []
    if UNSUPPORTED_COMPENSATION_FIELD in record:
        errors.append(
            f"{lead}{UNSUPPORTED_COMPENSATION_FIELD} is not supported in "
            f"schema v{schema_version}; use salary_range for posted base salary and "
            "company-scope comp_notes for other compensation details"
        )
    unknown_structured = sorted(
        key for key, value in record.items()
        if key not in JOB_SCHEMA_FIELDS
        and key != UNSUPPORTED_COMPENSATION_FIELD
        and isinstance(value, (dict, list))
    )
    if unknown_structured:
        errors.append(
            f"{lead}has unsupported structured field(s): "
            f"{', '.join(unknown_structured)}"
        )
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
    if "stage" in record:
        errors.append(
            f"{lead}stage was removed in schema v{schema_version} — migrate it to the "
            f"structured {lead}progress summary (migrate_to_v5.py)")
    errors.extend(_validate_progress(
        record.get("progress"), record.get("status"), f"{lead}progress",
        schema_version=schema_version))
    errors.extend(_validate_status_date(record.get("status_date"), f"{lead}status_date"))
    errors.extend(_validate_store_key(record.get("store_key"), f"{lead}store_key"))
    if "company_key" in record:
        # A jobs[] entry is HALF-CLOSED: unknown structured fields are rejected
        # above, unknown SCALARS are tolerated. So a per-job company_key would be
        # silently accepted and silently ignored — the worst outcome, because the
        # writer would believe it took effect. One folder is one employer (every
        # meta.yaml carries exactly one top-level ``company``), so the key belongs
        # beside it and nowhere else.
        errors.append(
            f"{lead}company_key is not a per-job field — one application folder is "
            "one employer, so company_key belongs at the top level beside company")
    return errors


_STORE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# The owner's company key. Same PATTERN as ``company_index.KEY_RE``, deliberately
# RESTATED rather than imported: this module is vendored byte-identically into
# three skills and is stdlib+PyYAML only (module docstring), and no other module in
# that vendored set imports a sibling — so an import here would mean vendoring the
# whole index loader into three skills that use nothing but this one regex, with a
# sys.path dance to keep the copies byte-identical. The two are pinned together by
# ``test_job_metadata.py::test_company_key_pattern_matches_the_index_module``, so a
# change to either that is not made to both turns the suite red.
#
# It is a SEPARATE constant from ``_STORE_KEY_RE`` despite the identical pattern:
# store entity keys and company keys answer different questions and either may
# change shape without the other.
#
# ``\A``/``\Z`` rather than ``^``/``$``: ``$`` matches BEFORE a trailing newline, so
# ``"acme-labs\n"`` used to validate here while the reconciler called the same value
# a finding. A key is spent as a folder name, and a folder name cannot hold one.
_COMPANY_KEY_RE = re.compile(r"\A[a-z0-9][a-z0-9-]*\Z")


def _validate_company_key(value: Any) -> list[str]:
    """Optional top-level link to an entry in the owner's private company index.

    A FILING key, never a match key: nothing in this repository may put it into a
    comparison that decides whether a posting is skipped, deduplicated, filtered
    or counted as covered (guarded at source level by
    ``automation/shared/tests/test_company_key_additive.py``).

    Absent is fine and is the normal state — a new application is scaffolded
    without one and the key is assigned later, deliberately. Present must be a
    non-empty string of the documented shape.

    Deliberately does NOT check that the key RESOLVES. The index is private, and
    this module is vendored into three skills that must run correctly with no
    overlay mounted at all; resolution is checked by the reconciler on the
    maintainer's machine, where the index exists.
    """
    if value is None:
        return []
    if not isinstance(value, str) or not _COMPANY_KEY_RE.match(value):
        return ["company_key must be a lowercase company-index key "
                "([a-z0-9-], starting with a letter or digit), or absent"]
    return []


def _validate_store_key(value: Any, path: str) -> list[str]:
    """Optional durable link to a raw-data-layer store entity (e.g. ``gh-1234567``).

    Absent OR empty string (``""``, the documented unset default, matching every
    sibling optional v4 field) is fine; a NON-empty value must be a lowercase store
    entity key. Handoff copies it verbatim from the search JSON — never re-derived.
    """
    if value is None or value == "":
        return []
    if not isinstance(value, str) or not _STORE_KEY_RE.match(value):
        return [f"{path} must be a store entity key ([a-z0-9-], e.g. gh-1234567)"]
    return []


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


def _role_label_key(role: str) -> str:
    """The collision domain of a ``jobs[].role`` label: its output-filename slug.

    ``layout.slugify_label`` is what turns a role into the ``<COVER_STEM>_<role>``
    and ``<APPLICATION_STEM>_<role>`` suffixes, so two roles collide exactly when
    their slugs do. Reproduced here rather than imported because this module is
    vendored into three skills and must stay dependency-free; casefolded on top of
    it, because the filesystems this ships on are case-insensitive and
    ``check.check_role_filename_collisions`` (which compares case-sensitively)
    would otherwise miss ``Software Engineer`` vs ``software engineer``.
    """
    return "_".join(re.sub(r"[^0-9A-Za-z]+", " ", str(role)).split()).casefold()


def _validate_meta_for_schema(
    meta: dict,
    *,
    schema_version: int,
    app_dir: str | Path | None = None,
) -> list[str]:
    """Validate one explicitly selected application metadata schema.

    Each ``jobs`` entry carries a required per-job ``status`` (one of
    ``STATUS_VALUES``) and a required structured ``progress`` summary
    ({phase, state, label?, calendar_items?, updated_at?, source?} in v6); the retired
    free-text ``stage`` key (per-job or top-level) is rejected. When ``app_dir``
    sits inside a known status folder, the folder label must equal
    ``derive_status(jobs)`` — a manual folder move that skipped the CLI is
    flagged so it can be re-synced.
    """
    version = meta.get("job_metadata_schema_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != schema_version
    ):
        return [
            f"job_metadata_schema_version must be {schema_version}"
        ]

    errors: list[str] = []
    if not str(meta.get("company") or "").strip():
        errors.append("company is required")
    # The top level is a DENYLIST (``stage``/``status``/``total_compensation_range``
    # below), so ``company_key`` was already tolerated. This is the positive shape
    # check, so a malformed key is caught here rather than carried to the reconciler.
    errors.extend(_validate_company_key(meta.get("company_key")))
    if "stage" in meta:
        errors.append(
            f"top-level stage is not allowed in schema v{schema_version} "
            "(stage was replaced by "
            "per-job progress)")
    if "status" in meta:
        errors.append(
            f"top-level status is not allowed in schema v{schema_version} "
            "(status is per-job, "
            "under jobs:)")
    if UNSUPPORTED_COMPENSATION_FIELD in meta:
        errors.append(
            f"top-level {UNSUPPORTED_COMPENSATION_FIELD} is not supported in "
            f"schema v{schema_version}; use jobs[].salary_range for posted base salary and "
            "comp_notes for other compensation details"
        )

    jobs = meta.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        errors.append("jobs must be a non-empty list (one entry per posting)")
        return errors

    seen_role_labels: dict[str, str] = {}
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            errors.append(f"jobs[{index}] must be a mapping")
            continue
        role = str(job.get("role") or "").strip()
        if not role:
            errors.append(f"jobs[{index}].role is required")
        else:
            label = _role_label_key(role)
            if label in seen_role_labels:
                errors.append(
                    f"jobs[{index}].role duplicates another posting's role: "
                    f"{role!r} and {seen_role_labels[label]!r} produce the same "
                    "cover-letter and bundle filename, so two JDs would share one "
                    "cover letter; give each posting a distinguishing label "
                    "(e.g. 'Software Engineer (Austin, TX)')"
                )
            else:
                seen_role_labels[label] = role
        if not str(job.get("jd_file") or "").strip():
            errors.append(f"jobs[{index}].jd_file is required")
        errors.extend(validate_job_metadata(
            job, prefix=f"jobs[{index}]", schema_version=schema_version))

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


def validate_meta(meta: dict, *, app_dir: str | Path | None = None) -> list[str]:
    """Validate the current schema-v6 application metadata contract."""
    return _validate_meta_for_schema(
        meta, schema_version=APPLICATION_SCHEMA_VERSION, app_dir=app_dir)


def validate_legacy_v5_meta(meta: dict) -> list[str]:
    """Validate v5 input immediately before a checksum-guarded v6 migration.

    This intentionally has no application-directory mode and is not a runtime
    compatibility path: normal readers and writers call :func:`validate_meta`,
    which accepts only the current schema.
    """
    return _validate_meta_for_schema(
        meta, schema_version=LEGACY_APPLICATION_SCHEMA_VERSION)
