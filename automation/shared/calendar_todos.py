"""The single private calendar/todo file (``calendar.md``) — parse, verify, plan.

``config.calendar_path()`` resolves ONE human-first Markdown file that holds
every interview schedule, scheduling todo, follow-up deadline, and reschedule
history for the whole application fleet (design family:
``design/application-progress-calendar/``). The owner scans it, checks boxes,
and adds personal notes; tools own ONLY the marked job-hunt entries.

File contract:

- Four exact section headings, each appearing once::

      ## Action needed              owner action / booking / decision / follow-up
      ## Waiting and follow-up      scheduling / employer / result / paused waits
      ## Interview schedule         confirmed times, chronological
      ## My notes and personal todos   owner-only; tooling never writes here

- A tool-owned entry is a top-level checkbox bullet immediately followed by a
  compact, hidden machine marker. The visible row is the product; the marker
  stays on one line so opening the Markdown source does not bury the agenda in
  implementation detail::

      - [ ] **Choose an interview time** — [ExampleCorp · Senior Software Engineer](../4_in_progress/examplecorp/meta.yaml)
        <!-- jobhunt-calendar {"id":"cal-examplecorp-01",...} -->

- ``starts_at``/``timezone`` describe the CURRENT confirmed occurrence; the
  append-only ``history:`` list preserves superseded and cancelled occurrences
  (a confirmed reschedule never overwrites the old time). A time merely
  passing never completes an interview — only the owner or explicit evidence
  does.
- The owner-editable proposal fields are the checkbox, ``reschedule_to`` +
  ``reschedule_timezone`` (a confirmed replacement time), and ``cancel: true``;
  ``status.py --sync-calendar`` maps them back to progress, preview-first.

Safety: parsing fails closed on malformed markers, duplicate ids, unknown
keys/states, and scheduled entries without an exact time + IANA timezone.
Plans splice only whole entry line-ranges, so every unmarked line survives
byte-for-byte; writes go through the checksum-guarded atomic replacement in
``metadata_editor.atomic_write_bytes``. This module is pure (stdlib + PyYAML)
and config-free; the application tracker is the only transactional writer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

try:  # Sibling shared module (vendored together into the tracker skill).
    from .job_metadata import (
        CALENDAR_ITEM_RE,
        PROGRESS_ACTION_STATES,
        PROGRESS_PHASES,
        PROGRESS_STATES,
        PROGRESS_WAITING_STATES,
    )
except ImportError:  # Direct top-level import (tests + vendored skills).
    from job_metadata import (
        CALENDAR_ITEM_RE,
        PROGRESS_ACTION_STATES,
        PROGRESS_PHASES,
        PROGRESS_STATES,
        PROGRESS_WAITING_STATES,
    )

SECTION_ACTION = "## Action needed"
SECTION_WAITING = "## Waiting and follow-up"
SECTION_SCHEDULED = "## Interview schedule"
SECTION_NOTES = "## My notes and personal todos"
SECTIONS = (SECTION_ACTION, SECTION_WAITING, SECTION_SCHEDULED, SECTION_NOTES)
LEGACY_SECTION_ALIASES = {
    "## Waiting for confirmation": SECTION_WAITING,
    "## Scheduled": SECTION_SCHEDULED,
}
ALL_SECTION_HEADINGS = (*SECTIONS, *LEGACY_SECTION_ALIASES)
# Sections whose marked entries tools may create, edit, and move.
MANAGED_SECTIONS = (SECTION_ACTION, SECTION_WAITING, SECTION_SCHEDULED)

MARKER_OPEN = "<!-- jobhunt-calendar"
MARKER_CLOSE = "-->"

# State -> the section a live entry belongs in. Unknown/closed entries keep
# their last section so history stays auditable; nothing is deleted.
STATE_SECTIONS = {
    **{state: SECTION_ACTION for state in PROGRESS_ACTION_STATES},
    **{state: SECTION_WAITING for state in PROGRESS_WAITING_STATES},
    "scheduled": SECTION_SCHEDULED,
}
# Terminal roles render checked; active waits remain visibly open.
CHECKED_STATES = ("closed",)

# Owner checked the box -> the state the sync command proposes.
CHECKED_BOX_TRANSITIONS = {
    "booking_required": "awaiting_schedule",     # availability sent / slot booked
    "reschedule_required": "reschedule_pending",  # replacement request sent
    "scheduled": "awaiting_result",              # interview happened
    "action_required": "waiting_employer",       # owed action completed
    "in_progress": "awaiting_result",            # assessment/work submitted
    "decision_required": "waiting_employer",     # decision sent
    "follow_up_required": "waiting_employer",    # follow-up sent
}

# Marker payload keys. Required first; the rest default to null/false/empty.
_REQUIRED_KEYS = ("id", "application", "role", "phase", "state")
_OPTIONAL_KEYS = (
    "label", "action", "due_at", "starts_at", "ends_at", "timezone",
    "follow_up_at", "details", "source",
    "reschedule_to", "reschedule_timezone", "cancel", "history",
)
_HISTORY_STATUSES = ("superseded", "cancelled", "completed")
_HISTORY_KEYS = ("starts_at", "ends_at", "timezone", "status", "recorded_at")

_CHECKBOX_RE = re.compile(r"^- \[( |x|X)\] (.*)$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)?$")
_DATE_OR_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)?)?$")
_TIMEZONE_RE = re.compile(r"^(UTC|[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)+)$")

CALENDAR_TEMPLATE = """\
# Interview calendar

Scan the bold date or action first. Open the linked role for full context.

## Action needed

## Waiting and follow-up

## Interview schedule

## My notes and personal todos

- [ ] Add anything here; tooling never rewrites unmarked items.
"""


@dataclass(frozen=True)
class CalendarEntry:
    """One tool-owned entry: its fields plus its exact line span in the file."""

    entry_id: str
    application: str
    role: str
    phase: str
    state: str
    label: str | None
    action: str | None
    due_at: str | None
    starts_at: str | None
    ends_at: str | None
    timezone: str | None
    follow_up_at: str | None
    details: str | None
    source: str | None
    reschedule_to: str | None
    reschedule_timezone: str | None
    cancel: bool
    history: tuple[dict, ...]
    checked: bool
    text: str
    section: str | None
    start_line: int  # bullet line index (inclusive)
    end_line: int    # line index AFTER the marker close (exclusive)

    def fields(self) -> dict:
        """The marker-payload fields as a plain dict (no span/placement info)."""
        return {
            "id": self.entry_id,
            "application": self.application,
            "role": self.role,
            "phase": self.phase,
            "state": self.state,
            "label": self.label,
            "action": self.action,
            "due_at": self.due_at,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "timezone": self.timezone,
            "follow_up_at": self.follow_up_at,
            "details": self.details,
            "source": self.source,
            "reschedule_to": self.reschedule_to,
            "reschedule_timezone": self.reschedule_timezone,
            "cancel": self.cancel,
            "history": [dict(item) for item in self.history],
        }


@dataclass
class CalendarDocument:
    """A parsed calendar file: raw lines, section map, entries, and errors."""

    lines: list[str] = field(default_factory=list)  # keepends=True
    newline: str = "\n"
    sections: dict[str, int] = field(default_factory=dict)  # heading -> line idx
    entries: dict[str, CalendarEntry] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CalendarEditPlan:
    """A checksum-bound calendar edit prepared for an atomic write."""

    before_sha256: str
    output_bytes: bytes
    changed_entry_ids: tuple[str, ...]
    errors: tuple[str, ...]
    changed: bool


def _validate_timezone(value: str) -> bool:
    if not _TIMEZONE_RE.match(value):
        return False
    try:  # Best-effort IANA check; a missing tz database never fails the gate.
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            return False
        except Exception:
            return True
    except ImportError:
        return True
    return True


def validate_entry_fields(fields: dict, *, context: str) -> list[str]:
    """Validate one entry's marker payload. Fail closed on anything odd."""
    errors: list[str] = []
    for key in _REQUIRED_KEYS:
        if not str(fields.get(key) or "").strip():
            errors.append(f"{context}: marker is missing required key '{key}'")
    unknown = [k for k in fields if k not in _REQUIRED_KEYS + _OPTIONAL_KEYS]
    if unknown:
        errors.append(f"{context}: marker has unknown key(s): {', '.join(sorted(unknown))}")
    entry_id = str(fields.get("id") or "")
    if entry_id and not CALENDAR_ITEM_RE.match(entry_id):
        errors.append(f"{context}: id must match cal-<lowercase-slug>")
    phase = fields.get("phase")
    if phase is not None and phase not in PROGRESS_PHASES:
        errors.append(f"{context}: phase must be one of {', '.join(PROGRESS_PHASES)}")
    state = fields.get("state")
    if state is not None and state not in PROGRESS_STATES:
        errors.append(f"{context}: state must be one of {', '.join(PROGRESS_STATES)}")
    for key in (
        "label", "action", "details", "source", "timezone",
        "reschedule_timezone",
    ):
        value = fields.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"{context}: {key} must be a string or null")
        if isinstance(value, str) and ("\n" in value or "\r" in value or "-->" in value):
            errors.append(
                f"{context}: {key} must be one line and cannot contain '-->'")
    for key, pattern in (("starts_at", _DATETIME_RE),
                         ("ends_at", _DATETIME_RE),
                         ("reschedule_to", _DATETIME_RE),
                         ("due_at", _DATE_OR_DATETIME_RE),
                         ("follow_up_at", _DATE_OR_DATETIME_RE)):
        value = fields.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not pattern.match(value):
            errors.append(
                f"{context}: {key} must be an ISO-8601 "
                f"{'date or timestamp' if key in ('due_at', 'follow_up_at') else 'timestamp with an exact time'}")
    for key in ("timezone", "reschedule_timezone"):
        value = fields.get(key)
        if isinstance(value, str) and value and not _validate_timezone(value):
            errors.append(f"{context}: {key} must be an IANA timezone name")
    if not isinstance(fields.get("cancel", False), bool):
        errors.append(f"{context}: cancel must be true or false")
    history = fields.get("history", [])
    if not isinstance(history, list):
        errors.append(f"{context}: history must be a list")
        history = []
    for index, item in enumerate(history):
        if not isinstance(item, dict):
            errors.append(f"{context}: history[{index}] must be a mapping")
            continue
        if item.get("status") not in _HISTORY_STATUSES:
            errors.append(
                f"{context}: history[{index}].status must be one of "
                f"{', '.join(_HISTORY_STATUSES)}")
        bad = [k for k in item if k not in _HISTORY_KEYS]
        if bad:
            errors.append(
                f"{context}: history[{index}] has unknown key(s): {', '.join(sorted(bad))}")
    if state == "scheduled":
        if not str(fields.get("starts_at") or "").strip():
            errors.append(
                f"{context}: a scheduled entry requires starts_at with an exact time")
        if not str(fields.get("timezone") or "").strip():
            errors.append(f"{context}: a scheduled entry requires an explicit timezone")
    if fields.get("ends_at") and not fields.get("starts_at"):
        errors.append(f"{context}: ends_at requires starts_at")
    if fields.get("starts_at") and fields.get("ends_at"):
        try:
            starts = datetime.fromisoformat(str(fields["starts_at"]).replace("Z", "+00:00"))
            ends = datetime.fromisoformat(str(fields["ends_at"]).replace("Z", "+00:00"))
            if ends <= starts:
                errors.append(f"{context}: ends_at must be after starts_at")
        except (TypeError, ValueError):
            pass  # Shape errors above are more useful than a second parse error.
    if fields.get("reschedule_to") and not str(fields.get("reschedule_timezone") or "").strip():
        errors.append(f"{context}: reschedule_to requires reschedule_timezone")
    return errors


def _line_text(line: str) -> str:
    return line.rstrip("\r\n")


def parse_calendar(text: str) -> CalendarDocument:
    """Parse calendar.md. Any structural problem lands in ``doc.errors``."""
    doc = CalendarDocument(lines=text.splitlines(keepends=True))
    if doc.lines and doc.lines[0].endswith("\r\n"):
        doc.newline = "\r\n"

    for index, line in enumerate(doc.lines):
        stripped = _line_text(line)
        canonical = LEGACY_SECTION_ALIASES.get(stripped, stripped)
        if canonical in SECTIONS:
            if canonical in doc.sections:
                doc.errors.append(f"line {index + 1}: duplicate section heading '{canonical}'")
            else:
                doc.sections[canonical] = index
    for heading in SECTIONS:
        if heading not in doc.sections:
            doc.errors.append(f"missing required section heading '{heading}'")

    current_section: str | None = None
    index = 0
    while index < len(doc.lines):
        stripped = _line_text(doc.lines[index])
        canonical = LEGACY_SECTION_ALIASES.get(stripped, stripped)
        if canonical in SECTIONS:
            current_section = canonical
            index += 1
            continue
        marker_text = stripped.strip()
        if marker_text.startswith(MARKER_OPEN):
            context = f"line {index + 1}"
            bullet_index = index - 1
            bullet = _CHECKBOX_RE.match(_line_text(doc.lines[bullet_index])) \
                if bullet_index >= 0 else None
            if bullet is None:
                doc.errors.append(
                    f"{context}: jobhunt-calendar marker is not directly below a "
                    "'- [ ]' checkbox bullet")
                index += 1
                continue
            if marker_text == MARKER_OPEN:
                # Legacy multi-line YAML markers remain readable; every entry
                # touched by the planner is rewritten to the compact form.
                indent = doc.lines[index][
                    :len(doc.lines[index]) - len(doc.lines[index].lstrip())]
                close_index = None
                payload_lines: list[str] = []
                probe = index + 1
                while probe < len(doc.lines):
                    probe_text = _line_text(doc.lines[probe])
                    if probe_text.strip() == MARKER_CLOSE:
                        close_index = probe
                        break
                    if probe_text.strip() in (MARKER_OPEN, *ALL_SECTION_HEADINGS):
                        break
                    payload_lines.append(
                        probe_text[len(indent):] if probe_text.startswith(indent)
                        else probe_text.strip())
                    probe += 1
                if close_index is None:
                    doc.errors.append(
                        f"{context}: marker block is never closed with '-->'")
                    index += 1
                    continue
                payload_text = "\n".join(payload_lines)
            elif marker_text.endswith(MARKER_CLOSE):
                close_index = index
                payload_text = marker_text[
                    len(MARKER_OPEN):-len(MARKER_CLOSE)].strip()
            else:
                doc.errors.append(
                    f"{context}: compact marker is never closed with '-->'")
                index += 1
                continue
            try:
                payload = yaml.safe_load(payload_text) or {}
            except yaml.YAMLError as exc:
                doc.errors.append(f"{context}: marker payload is not valid YAML: {exc}")
                index = close_index + 1
                continue
            if not isinstance(payload, dict):
                doc.errors.append(f"{context}: marker payload must be a mapping")
                index = close_index + 1
                continue
            doc.errors.extend(validate_entry_fields(payload, context=context))
            entry_id = str(payload.get("id") or "")
            if entry_id in doc.entries:
                doc.errors.append(f"{context}: duplicate calendar entry id '{entry_id}'")
            if current_section == SECTION_NOTES:
                doc.errors.append(
                    f"{context}: tool-owned marker inside the personal-notes section")
            if current_section is None:
                doc.errors.append(
                    f"{context}: marker appears before the first section heading")
            history = payload.get("history") or []
            entry = CalendarEntry(
                entry_id=entry_id,
                application=str(payload.get("application") or ""),
                role=str(payload.get("role") or ""),
                phase=str(payload.get("phase") or ""),
                state=str(payload.get("state") or ""),
                label=payload.get("label"),
                action=payload.get("action"),
                due_at=payload.get("due_at"),
                starts_at=payload.get("starts_at"),
                ends_at=payload.get("ends_at"),
                timezone=payload.get("timezone"),
                follow_up_at=payload.get("follow_up_at"),
                details=payload.get("details"),
                source=payload.get("source"),
                reschedule_to=payload.get("reschedule_to"),
                reschedule_timezone=payload.get("reschedule_timezone"),
                cancel=bool(payload.get("cancel", False)),
                history=tuple(item for item in history if isinstance(item, dict)),
                checked=bullet.group(1).lower() == "x",
                text=bullet.group(2),
                section=current_section,
                start_line=bullet_index,
                end_line=close_index + 1,
            )
            if entry_id and entry_id not in doc.entries:
                doc.entries[entry_id] = entry
            index = close_index + 1
            continue
        index += 1
    return doc


def render_entry(fields: dict, *, checked: bool, text: str, newline: str = "\n") -> list[str]:
    """Render one human row plus one compact, hidden machine marker."""
    box = "x" if checked else " "
    payload: dict[str, Any] = {key: fields.get(key) for key in _REQUIRED_KEYS}
    for key in (
        "label", "action", "due_at", "starts_at", "ends_at", "timezone",
        "follow_up_at", "details", "reschedule_to", "reschedule_timezone",
    ):
        if fields.get(key) not in (None, ""):
            payload[key] = fields[key]
    if fields.get("cancel", False):
        payload["cancel"] = True
    history = fields.get("history") or []
    if history:
        payload["history"] = [dict(item) for item in history]
    dumped = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"- [{box}] {text}", f"  {MARKER_OPEN} {dumped} {MARKER_CLOSE}"]
    return [line + newline for line in lines]


_PHASE_LABELS = {
    "application_prep": "Application",
    "application_review": "Application review",
    "recruiter_screen": "Recruiter screen",
    "assessment": "Assessment",
    "hiring_manager": "Hiring manager",
    "technical_interview": "Technical interview",
    "interview_loop": "Interview loop",
    "team_match": "Team match",
    "reference_check": "Reference check",
    "offer": "Offer",
    "background_check": "Background check",
    "work_authorization": "Work authorization",
    "onboarding": "Onboarding",
    "other": "Next step",
}

_STATE_LABELS = {
    "action_required": "Complete next step",
    "booking_required": "Choose an interview time",
    "awaiting_schedule": "Waiting for confirmed time",
    "scheduled": "Interview",
    "reschedule_required": "Arrange a new interview time",
    "reschedule_pending": "Waiting for rescheduled time",
    "in_progress": "Complete current task",
    "decision_required": "Make a decision",
    "follow_up_required": "Follow up",
    "waiting_employer": "Waiting on employer",
    "awaiting_result": "Waiting for result",
    "paused": "Process paused",
    "closed": "Closed",
    "unknown": "Status needs review",
}


def _markdown_text(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _display_datetime(value: str | None, timezone_name: str | None) -> str | None:
    """Compact agenda timestamp in the entry's explicit timezone."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timezone_name:
            zone = ZoneInfo(timezone_name)
            parsed = parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return str(value)
    date_text = parsed.strftime("%a, %b %d").replace(" 0", " ")
    time_text = parsed.strftime("%I:%M %p").lstrip("0")
    zone_text = parsed.tzname() or timezone_name or ""
    return f"{date_text} · {time_text}{f' {zone_text}' if zone_text else ''}"


def _display_date_or_datetime(value: str | None, timezone_name: str | None) -> str | None:
    if not value:
        return None
    if "T" not in str(value):
        try:
            return datetime.fromisoformat(str(value)).strftime("%a, %b %d").replace(" 0", " ")
        except ValueError:
            return str(value)
    return _display_datetime(value, timezone_name)


def _subject(company: str, role: str, details: str | None) -> str:
    label = " · ".join(_markdown_text(part) for part in (company, role) if part)
    if not label:
        label = "Application"
    return f"[{label}](<{details}>)" if details else label


def _legacy_default_entry_text(company: str, role: str, state: str) -> str:
    subject = " — ".join(part for part in (company, role) if part)
    hints = {
        "booking_required": "choose an interview time",
        "awaiting_schedule": "waiting for the confirmed time",
        "scheduled": "confirmed interview",
        "reschedule_required": "arrange a new interview time",
        "reschedule_pending": "waiting for the rescheduled time",
        "action_required": "action needed",
    }
    hint = hints.get(state, state.replace("_", " "))
    return f"{subject}: {hint}" if subject else hint


def default_entry_text(
    company: str, role: str, state: str, *, fields: dict | None = None,
) -> str:
    """Scannable task or agenda row; full context lives behind one role link."""
    fields = fields or {}
    subject = _subject(company, role, fields.get("details"))
    stage = str(fields.get("label") or "").strip() or _PHASE_LABELS.get(
        str(fields.get("phase") or ""), "Next step")
    if state == "scheduled":
        when = _display_datetime(fields.get("starts_at"), fields.get("timezone")) \
            or "Time needs review"
        end = _display_datetime(fields.get("ends_at"), fields.get("timezone"))
        if end and " · " in end and " · " in when:
            end_time = end.split(" · ", 1)[1]
            when = f"{when}–{end_time}"
        return f"**{when}** — {subject} · {_markdown_text(stage)}"

    headline = str(fields.get("action") or "").strip() or _STATE_LABELS.get(
        state, state.replace("_", " ").title())
    bits = [f"**{_markdown_text(headline)}** — {subject}", _markdown_text(stage)]
    due = _display_date_or_datetime(fields.get("due_at"), fields.get("timezone"))
    follow_up = _display_date_or_datetime(
        fields.get("follow_up_at"), fields.get("timezone"))
    if due:
        bits.append(f"Due {due}")
    if follow_up:
        bits.append(f"Follow up {follow_up}")
    return " · ".join(bits)


def generate_entry_id(existing_ids, application_slug: str) -> str:
    """A stable new id: cal-<slug-minus-date>-NN (lowest unused NN)."""
    base = re.sub(r"-\d{8}$", "", str(application_slug or "").strip().lower())
    base = re.sub(r"[^a-z0-9-]+", "-", base).strip("-") or "entry"
    taken = set(existing_ids)
    for number in range(1, 100):
        candidate = f"cal-{base}-{number:02d}"
        if candidate not in taken:
            return candidate
    raise ValueError(f"no free calendar id for application {application_slug!r}")


def record_reschedule(fields: dict, new_starts_at: str, new_timezone: str) -> dict:
    """Confirm a replacement time: the old occurrence is preserved, never lost.

    Appends the current occurrence to ``history`` as ``superseded``, installs
    the replacement as the current time, clears the owner-proposal fields, and
    returns the entry to ``scheduled``.
    """
    out = dict(fields)
    history = [dict(item) for item in out.get("history") or []]
    if out.get("starts_at"):
        occurrence = {
            "starts_at": out.get("starts_at"),
            "timezone": out.get("timezone"),
            "status": "superseded",
        }
        if out.get("ends_at"):
            occurrence["ends_at"] = out["ends_at"]
        history.append(occurrence)
    out.update({
        "starts_at": new_starts_at,
        "ends_at": None,
        "timezone": new_timezone,
        "state": "scheduled",
        "reschedule_to": None,
        "reschedule_timezone": None,
        "cancel": False,
        "history": history,
    })
    return out


def record_cancellation(fields: dict, *, next_state: str = "action_required") -> dict:
    """Cancel the current occurrence (kept in history); never closes the role."""
    out = dict(fields)
    history = [dict(item) for item in out.get("history") or []]
    if out.get("starts_at"):
        occurrence = {
            "starts_at": out.get("starts_at"),
            "timezone": out.get("timezone"),
            "status": "cancelled",
        }
        if out.get("ends_at"):
            occurrence["ends_at"] = out["ends_at"]
        history.append(occurrence)
    out.update({
        "starts_at": None,
        "ends_at": None,
        "timezone": None,
        "state": next_state,
        "reschedule_to": None,
        "reschedule_timezone": None,
        "cancel": False,
        "history": history,
    })
    return out


def _section_bounds(doc: CalendarDocument, heading: str) -> tuple[int, int]:
    """(start, end) line indexes of a section's content (after its heading)."""
    start = doc.sections[heading] + 1
    following = [idx for idx in doc.sections.values() if idx > doc.sections[heading]]
    end = min(following) if following else len(doc.lines)
    return start, end


def _entry_sort_key(lines: list[str]) -> str:
    """Chronological key for a rendered scheduled entry."""
    for line in lines:
        match = re.search(r'"starts_at":"([0-9T:.+\-Z]+)"', _line_text(line))
        if not match:  # Legacy multi-line marker.
            match = re.match(
                r"\s*starts_at:\s*['\"]?([0-9T:.+\-Z]+)", _line_text(line))
        if match:
            return match.group(1)
    return "~"


def plan_calendar_update(
    raw: bytes,
    upserts: dict[str, dict],
    *,
    create_missing: bool = False,
) -> CalendarEditPlan:
    """Plan a formatting-preserving calendar edit for the given entries.

    ``upserts`` maps entry id -> desired marker fields (the ``fields()`` shape).
    Existing entries are rewritten in place and MOVED to the section their new
    state projects to; new entries (``create_missing=True``) are appended to
    their section (chronologically for Scheduled). Unmarked lines are spliced
    around, never rewritten. Fails closed — a parse error, duplicate id,
    validation error, or verification failure returns the original bytes.
    """
    before_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return CalendarEditPlan(before_sha256, raw, (), (f"calendar is not UTF-8: {exc}",), False)

    doc = parse_calendar(text)
    errors = list(doc.errors)
    for entry_id, fields in sorted(upserts.items()):
        context = f"entry {entry_id}"
        if str(fields.get("id") or "") != entry_id:
            errors.append(f"{context}: upsert fields carry a different id")
        public = {k: v for k, v in fields.items() if not k.startswith("_")}
        errors.extend(validate_entry_fields(public, context=context))
        if entry_id not in doc.entries and not create_missing:
            errors.append(f"{context}: not found in the calendar file")
    if errors:
        return CalendarEditPlan(before_sha256, raw, (), tuple(errors), False)

    lines = list(doc.lines)
    # Work on a copy with entry spans; apply removals bottom-up so earlier
    # spans stay valid, collecting the rendered replacement per target section.
    pending: list[tuple[str, list[str], str]] = []  # (target section, lines, sort key)
    replacements: list[tuple[int, int, list[str]]] = []

    for entry_id, fields in sorted(upserts.items()):
        state = str(fields.get("state") or "")
        existing = doc.entries.get(entry_id)
        checked = state in CHECKED_STATES or (
            existing.checked if existing and state == existing.state else False
        )
        company = str(fields.get("_company") or "")
        role = str(fields.get("role") or "")
        text_line = default_entry_text(company, role, state, fields=fields)
        if existing:
            existing_fields = existing.fields()
            previous_default = default_entry_text(
                company, role, existing.state, fields=existing_fields)
            legacy_default = _legacy_default_entry_text(
                company, role, existing.state)
            # Preserve owner-authored wording, but advance labels that the tool
            # itself generated for the previous scheduling state.
            text_line = (
                default_entry_text(company, role, state, fields=fields)
                if existing.text in (previous_default, legacy_default)
                else existing.text
            )
        clean_fields = {k: v for k, v in fields.items() if not k.startswith("_")}
        rendered = render_entry(
            clean_fields, checked=checked, text=text_line, newline=doc.newline)
        target = STATE_SECTIONS.get(state)
        if existing is None:
            pending.append((target or SECTION_ACTION, rendered, _entry_sort_key(rendered)))
            continue
        if target is None or target == existing.section:
            # Rewrite in place (state keeps the entry in its current section).
            replacements.append((existing.start_line, existing.end_line, rendered))
        else:
            replacements.append((existing.start_line, existing.end_line, []))
            pending.append((target, rendered, _entry_sort_key(rendered)))

    for start, end, new_lines in sorted(replacements, key=lambda item: -item[0]):
        lines[start:end] = new_lines

    if pending:
        # Re-parse the spliced document to find fresh section bounds.
        interim = CalendarDocument(lines=lines, newline=doc.newline)
        for index, line in enumerate(lines):
            stripped = _line_text(line)
            canonical = LEGACY_SECTION_ALIASES.get(stripped, stripped)
            if canonical in SECTIONS and canonical not in interim.sections:
                interim.sections[canonical] = index
        if any(heading not in interim.sections for heading in SECTIONS):
            return CalendarEditPlan(
                before_sha256, raw, (),
                ("internal error: section headings lost during splice",), False)
        # Insert in a stable order (per section, chronological for Scheduled).
        for target, rendered, sort_key in sorted(
            pending, key=lambda item: (SECTIONS.index(item[0]), item[2])
        ):
            start, end = _section_bounds(interim, target)
            insert_at = end
            if target == SECTION_SCHEDULED:
                probe = start
                while probe < end:
                    stripped = _line_text(lines[probe])
                    if _CHECKBOX_RE.match(stripped):
                        span_end = probe
                        while span_end < end and _line_text(lines[span_end]).strip() != MARKER_CLOSE:
                            span_end += 1
                        existing_key = _entry_sort_key(lines[probe:span_end + 1])
                        if sort_key < existing_key:
                            insert_at = probe
                            break
                        probe = span_end + 1
                        continue
                    probe += 1
            # Keep one blank line between the previous content and the entry.
            while insert_at > start and _line_text(lines[insert_at - 1]).strip() == "":
                insert_at -= 1
            block = list(rendered)
            if insert_at > start:
                block = [doc.newline] + block
            block = block + [doc.newline]
            if insert_at < len(lines) and _line_text(lines[insert_at]).strip() == "" \
                    and block[-1] == doc.newline:
                block = block[:-1]
            if insert_at > 0 and not lines[insert_at - 1].endswith(("\n", "\r")):
                lines[insert_at - 1] = lines[insert_at - 1] + doc.newline
            lines[insert_at:insert_at] = block
            # Refresh section indexes after the insertion.
            interim.sections = {}
            for index, line in enumerate(lines):
                stripped = _line_text(line)
                canonical = LEGACY_SECTION_ALIASES.get(stripped, stripped)
                if canonical in SECTIONS and canonical not in interim.sections:
                    interim.sections[canonical] = index

    # Section headings are part of the tool contract, not owner prose. Any
    # touch upgrades the two original labels to the clearer current wording.
    for index, line in enumerate(lines):
        stripped = _line_text(line)
        canonical = LEGACY_SECTION_ALIASES.get(stripped)
        if canonical:
            ending = line[len(stripped):]
            lines[index] = canonical + ending

    output_text = "".join(lines)
    output_doc = parse_calendar(output_text)
    if output_doc.errors:
        return CalendarEditPlan(
            before_sha256, raw, (),
            tuple(f"planned calendar failed verification: {error}"
                  for error in output_doc.errors),
            False)
    for entry_id in upserts:
        if entry_id not in output_doc.entries:
            return CalendarEditPlan(
                before_sha256, raw, (),
                (f"planned calendar lost entry {entry_id}",), False)

    output_bytes = output_text.encode("utf-8")
    return CalendarEditPlan(
        before_sha256=before_sha256,
        output_bytes=output_bytes,
        changed_entry_ids=tuple(sorted(upserts)),
        errors=(),
        changed=output_bytes != raw,
    )


def entry_with_state(entry: CalendarEntry, **updates) -> CalendarEntry:
    """A copy of *entry* with the given field updates (frozen dataclass helper)."""
    return replace(entry, **updates)
