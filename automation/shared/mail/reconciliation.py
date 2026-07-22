"""Pure email-store categorization, application linking, and reconciliation.

This module deliberately has no filesystem, provider, or application-tracker
imports.  The email builder feeds it normalized *stored* message mappings and
persists its content-free result; a later consumer may re-open exactly one
stored message through :func:`reverify_transition` before presenting a tracker
transaction.  Nothing here sends mail or writes an application.

The safety properties are intentionally visible in the public result shape:

* categories are deterministic, versioned, and non-exclusive;
* shared ATS mail domains are vendors, never companies;
* a role becomes ``exact`` only from a company-agreeing structured token or a
  human confirmation; thread and temporal links cannot become exact;
* every proposal is preview-only and names its message key, derivation and
  confidence; and
* scheduling needs an explicit body date, time, and timezone.  Attachment
  metadata can request triage but can never create a scheduled interview.

The module uses only the standard library so it is safe to vendor into the
standalone email-assistant skill.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
from typing import Any, Callable, Iterable, Mapping, Sequence


CATEGORY_VOCABULARY_VERSION = "email-categories.v1"
LINKING_RULES_VERSION = "email-linking.v1"
PROJECTION_SCHEMA_VERSION = "email-projections.v1"

CATEGORIES = (
    "receipt",
    "assessment",
    "interview_invite",
    "scheduling",
    "neutral_status_update",
    "rejection",
    "offer",
    "inbound_recruiter_outreach",
    "outbound_cold_outreach",
    "follow_up_needed",
    "job_alert_digest",
    "background_check_onboarding",
    "unrelated",
    "unknown",
)

SCHEDULING_SUBTYPES = (
    "booking_requested",
    "availability_submitted",
    "schedule_confirmed",
    "reschedule_requested",
    "replacement_confirmed",
    "cancellation",
    "awaiting_result",
)

# ``needs_reply`` is deliberately narrower than the general triage/category
# surface.  These categories are terminal, informational, or bulk mail even
# when wording elsewhere happens to look like a response request; never turn
# them into a personal TODO.  A confirmed time is also informational, while a
# booking/reschedule request is actionable.
NEEDS_REPLY_HARD_EXCLUSIONS = frozenset({
    "receipt",
    "rejection",
    "job_alert_digest",
    "unrelated",
})
NEEDS_REPLY_ACTIONABLE_CATEGORIES = frozenset({
    "follow_up_needed",
    "inbound_recruiter_outreach",
})
NEEDS_REPLY_ACTIONABLE_SCHEDULING_SUBTYPES = frozenset({
    "booking_requested",
    "reschedule_requested",
})

# These vendors host mail for thousands of companies.  A match here is useful
# only as vendor metadata; treating it as a company would be a mislink factory.
SHARED_ATS_DOMAINS = frozenset({
    "greenhouse.io", "greenhouse-mail.io", "greenhousemail.io",
    "lever.co", "levermail.com", "ashbyhq.com", "workday.com",
    "myworkday.com", "icims.com", "smartrecruiters.com",
    "jobvite.com", "taleo.net", "successfactors.com",
})

_EMAIL_RE = re.compile(r"(?<![\w.+-])([a-z0-9][a-z0-9._%+-]*@([a-z0-9-]+(?:\.[a-z0-9-]+)+))", re.I)
_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.I)
_REQ_RE = re.compile(
    r"\b(?:req(?:uisition)?(?:\s*(?:id|number|#|no\.?)\s*)?"
    r"|(?:job|posting)\s*(?:id|number|#|no\.?)\s*)[:#-]?\s*([a-z][a-z0-9._-]{2,}|\d{3,})\b",
    re.I,
)
_BARE_NUMBER_RE = re.compile(r"\b\d{3,}\b")
_ISO_SCHEDULE_RE = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2})[ T,]+(\d{1,2}:\d{2})(?:\s*([ap]m))?\s+(UTC|GMT|[A-Z]{2,4}|America/[A-Za-z_]+(?:/[A-Za-z_]+)?)\b",
    re.I,
)
_MONTH_SCHEDULE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s*(20\d{2})\s+(?:at\s+)?(\d{1,2}:\d{2})(?:\s*([ap]m))?\s+"
    r"(UTC|GMT|[A-Z]{2,4}|America/[A-Za-z_]+(?:/[A-Za-z_]+)?)\b",
    re.I,
)
_DATE_DEADLINE_RE = re.compile(r"\b(?:by|before|deadline\s*(?:is|:)?|due)\s+(20\d{2}-\d{2}-\d{2})\b", re.I)
_HOURS_DEADLINE_RE = re.compile(r"\bwithin\s+(\d{1,3})\s+hours?\b", re.I)
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", re.I)

_TZ_CANONICAL = {
    "utc": "UTC", "gmt": "UTC",
    "pt": "America/Los_Angeles", "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "mt": "America/Denver", "mst": "America/Denver", "mdt": "America/Denver",
    "ct": "America/Chicago", "cst": "America/Chicago", "cdt": "America/Chicago",
    "et": "America/New_York", "est": "America/New_York", "edt": "America/New_York",
}
_MONTHS = {name.casefold(): number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1
)}
_ACTIVE_STATUSES = frozenset({"drafted", "applied", "in_progress"})


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).casefold()).strip()


def _company_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm(value))


def _domain(value: Any) -> str:
    raw = _text(value).casefold().lstrip("@")
    if "@" in raw:
        raw = raw.rsplit("@", 1)[1]
    return raw.rstrip(".") if _DOMAIN_RE.fullmatch(raw) else ""


def _domain_is_shared_ats(domain: str) -> bool:
    return any(domain == item or domain.endswith("." + item) for item in SHARED_ATS_DOMAINS)


def _parse_time(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _time_text(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else ""


def _first_mapping_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _address(value: Any) -> str:
    if isinstance(value, str):
        match = _EMAIL_RE.search(value)
        return (match.group(1) if match else value).casefold().strip()
    if isinstance(value, Mapping):
        direct = _first_mapping_value(value, "address", "email", "emailAddress")
        if isinstance(direct, Mapping):
            direct = _first_mapping_value(direct, "address", "email")
        return _address(direct)
    return ""


def _addresses(value: Any) -> tuple[str, ...]:
    """Extract recipient addresses from Graph-style or generic recipient fields."""
    if isinstance(value, Mapping):
        address = _address(value)
        return (address,) if address else ()
    if isinstance(value, str):
        address = _address(value)
        return (address,) if address else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(sorted({address for item in value for address in _addresses(item) if address}))
    return ()


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ()


def _body_from_stored(mapping: Mapping[str, Any]) -> str:
    """Accept common normalized envelopes without binding to a disk schema."""
    for key in ("body_text", "body", "content", "text"):
        value = mapping.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            nested = _first_mapping_value(value, "content", "text", "value")
            if isinstance(nested, str):
                return nested
    envelope = mapping.get("envelope")
    if isinstance(envelope, Mapping):
        return _body_from_stored(envelope)
    return ""


def hydrate_stored_message(envelope: Mapping[str, Any], content: Mapping[str, Any] | str) -> dict[str, Any]:
    """Merge an email-store envelope with one deliberately resolved raw body.

    The store's normal entity contains only envelope fields (``message_key``,
    provider IDs, folder/scope/timestamps, attachment metadata, and raw fetch
    references).  It intentionally has no subject or body.  The builder or a
    transition verifier resolves the referenced raw blob explicitly, passes the
    resulting subject/body here, and must persist only :func:`_public_record`'s
    content-free result.  This function never opens a blob or accepts a path.
    """
    if not isinstance(envelope, Mapping):
        raise ValueError("stored message envelope must be a mapping")
    merged = dict(envelope)
    if isinstance(content, str):
        merged["body_text"] = content
    elif isinstance(content, Mapping):
        subject = _first_mapping_value(content, "subject")
        body = _body_from_stored(content)
        if subject is not None:
            merged["subject"] = subject
        if body:
            merged["body_text"] = body
    else:
        raise ValueError("hydrated stored message content must be a mapping or string")
    return normalize_stored_message(merged)


def normalize_stored_message(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one deliberate local message read into a provider-neutral view.

    The adapter accepts Graph-style fields and the narrow generic field names the
    email-store builder is expected to emit.  It never reads a path itself.  The
    The input may be an envelope-only entity, in which case ``body_present`` is
    false and every transition is fail-closed.  For categorization/reverification
    pass an explicit hydration via :func:`hydrate_stored_message` (or the same
    envelope mapping merged with raw ``subject``/``body_text`` in memory).  The
    returned object retains ``body_text`` only in memory; callers must not
    serialize it into a tracked index or application file.
    """
    if not isinstance(mapping, Mapping):
        raise ValueError("stored message must be a mapping")
    envelope = mapping.get("envelope") if isinstance(mapping.get("envelope"), Mapping) else {}
    message_key = _text(_first_mapping_value(mapping, "message_key", "key", "entity_key"))
    if not message_key:
        message_key = _text(_first_mapping_value(envelope, "message_key", "key", "entity_key", "id"))
    if not message_key:
        # Provider IDs are accepted only at this boundary.  A builder should turn
        # them into neutral keys before persistence, but a missing key is worse
        # than refusing a potentially unsafe proposal.
        message_key = _text(_first_mapping_value(mapping, "id", "provider_id"))
    if not message_key:
        raise ValueError("stored message requires message_key or provider id")

    folder = _norm(_first_mapping_value(mapping, "folder", "folder_name") or _first_mapping_value(envelope, "folder", "folder_name"))
    direction = _norm(_first_mapping_value(mapping, "direction") or _first_mapping_value(envelope, "direction"))
    if direction not in {"inbound", "outbound", "draft"}:
        direction = "outbound" if folder in {"sent", "sentitems", "sent items"} else "draft" if (folder == "drafts" or mapping.get("is_draft")) else "inbound"
    sender = _address(_first_mapping_value(mapping, "sender", "from", "from_address") or _first_mapping_value(envelope, "sender", "from", "from_address"))
    recipients = _addresses(
        _first_mapping_value(mapping, "to", "to_recipients", "toRecipients", "recipients")
        or _first_mapping_value(envelope, "to", "to_recipients", "toRecipients", "recipients")
    )
    timestamp_raw = _first_mapping_value(
        mapping, "timestamp", "received_at", "receivedDateTime", "sent_at", "sentDateTime", "lastModifiedDateTime"
    ) or _first_mapping_value(envelope, "timestamp", "received_at", "receivedDateTime", "sent_at", "sentDateTime")
    timestamp = _parse_time(timestamp_raw)
    thread_values = list(_strings(_first_mapping_value(mapping, "thread_keys", "correlation_keys", "thread_key")))
    for key in ("thread_key", "provider_thread_id", "conversation_id", "conversationId", "rfc_message_id", "internet_message_id", "internetMessageId", "in_reply_to", "inReplyTo", "references"):
        value = _first_mapping_value(mapping, key) or _first_mapping_value(envelope, key)
        thread_values.extend(_strings(value))
    thread_keys = tuple(sorted({_norm(value) for value in thread_values if _norm(value)}))
    attachments = mapping.get("attachments") or envelope.get("attachments") or []
    attachment_names = []
    if isinstance(attachments, Sequence) and not isinstance(attachments, (str, bytes, bytearray)):
        for item in attachments:
            if isinstance(item, Mapping):
                attachment_names.append(_text(_first_mapping_value(item, "name", "filename")))
            elif isinstance(item, str):
                attachment_names.append(item.strip())
    body_text = _body_from_stored(mapping)
    subject = _text(_first_mapping_value(mapping, "subject") or _first_mapping_value(envelope, "subject"))
    return {
        "message_key": message_key,
        "account": _text(_first_mapping_value(mapping, "account", "account_key") or _first_mapping_value(envelope, "account", "account_key")),
        "provider": _text(_first_mapping_value(mapping, "provider") or _first_mapping_value(envelope, "provider")),
        "folder": folder,
        "direction": direction,
        "timestamp": _time_text(timestamp),
        "subject": subject,
        "sender": sender,
        "sender_domain": _domain(sender),
        "recipient_domains": tuple(sorted({_domain(address) for address in recipients if _domain(address)})),
        "thread_keys": thread_keys,
        "body_text": body_text,
        "body_present": bool(body_text.strip()),
        "attachment_names": tuple(name for name in attachment_names if name),
        "tombstoned": bool(mapping.get("tombstoned") or mapping.get("deleted")),
        "out_of_scope": bool(mapping.get("out_of_scope") or mapping.get("in_scope") is False),
    }


def _contains(text: str, *phrases: str) -> bool:
    return any(phrase in text for phrase in phrases)


def _explicit_schedule(text: str) -> dict[str, str] | None:
    """Return a wall-clock datetime only if date, time, and timezone are explicit."""
    match = _ISO_SCHEDULE_RE.search(text)
    if match:
        date_part, clock, ampm, raw_tz = match.groups()
        return _schedule_parts(date_part, clock, ampm, raw_tz)
    match = _MONTH_SCHEDULE_RE.search(text)
    if match:
        month, day, year, clock, ampm, raw_tz = match.groups()
        date_part = f"{year}-{_MONTHS[month.casefold()]:02d}-{int(day):02d}"
        return _schedule_parts(date_part, clock, ampm, raw_tz)
    return None


def _schedule_parts(date_part: str, clock: str, ampm: str | None, raw_tz: str) -> dict[str, str] | None:
    hour, minute = (int(part) for part in clock.split(":"))
    if ampm:
        if hour < 1 or hour > 12:
            return None
        hour = (hour % 12) + (12 if ampm.casefold() == "pm" else 0)
    elif hour > 23:
        return None
    tz = _TZ_CANONICAL.get(raw_tz.casefold(), raw_tz)
    try:
        datetime.fromisoformat(f"{date_part}T{hour:02d}:{minute:02d}:00")
    except ValueError:
        return None
    return {"starts_at": f"{date_part}T{hour:02d}:{minute:02d}:00", "timezone": tz}


def extract_deadline(message: Mapping[str, Any]) -> dict[str, str] | None:
    """Extract a deterministic explicit/relative deadline; never use wall clock."""
    normalized = normalize_stored_message(message) if "body_text" not in message else dict(message)
    text = f"{normalized.get('subject', '')}\n{normalized.get('body_text', '')}".casefold()
    match = _DATE_DEADLINE_RE.search(text)
    if match:
        try:
            datetime.fromisoformat(match.group(1))
        except ValueError:
            return None
        return {"due_at": match.group(1), "kind": "explicit_date"}
    match = _HOURS_DEADLINE_RE.search(text)
    timestamp = _parse_time(normalized.get("timestamp"))
    if match and timestamp:
        due = timestamp + timedelta(hours=int(match.group(1)))
        return {"due_at": _time_text(due), "kind": "relative_hours"}
    return None


def categorize_message(message: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a normalized message with deterministic, non-exclusive flags."""
    normalized = normalize_stored_message(message) if "body_text" not in message else dict(message)
    subject = _text(normalized.get("subject"))
    body = _text(normalized.get("body_text"))
    text = f"{subject}\n{body}".casefold()
    direction = _norm(normalized.get("direction"))
    categories: set[str] = set()
    subtypes: set[str] = set()

    if _contains(text, "application received", "application has been received", "thanks for applying", "thank you for applying"):
        categories.add("receipt")
    if _contains(text, "assessment", "coding challenge", "online assessment", "take-home", "take home"):
        categories.add("assessment")
    if _contains(text, "interview", "phone screen", "virtual screen", "onsite", "on-site", "interview loop"):
        categories.add("interview_invite")
    if _contains(text, "application update", "still under consideration", "status update", "next steps"):
        categories.add("neutral_status_update")
    if _contains(text, "unfortunately", "not moving forward", "not move forward", "decided not to proceed", "no longer under consideration", "will not be moving forward"):
        categories.add("rejection")
    if _contains(text, "job offer", "offer letter", "pleased to offer", "offer package"):
        categories.add("offer")
    if _contains(text, "background check", "onboarding", "start date", "i-9"):
        categories.add("background_check_onboarding")
    if _contains(text, "job alert", "new jobs matching", "recommended jobs"):
        categories.add("job_alert_digest")
    if _contains(text, "unsubscribe", "shipping update", "your order", "invoice", "receipt for your purchase"):
        categories.add("unrelated")

    schedule_words = _contains(text, "schedule", "scheduling", "availability", "available times", "calendar", "book a time", "reschedule", "rescheduled", "cancelled", "canceled")
    if schedule_words:
        categories.add("scheduling")
    if direction == "inbound" and _contains(text, "choose a time", "select a time", "book a time", "send your availability", "share your availability", "available times", "scheduling link"):
        subtypes.add("booking_requested")
    if direction == "outbound" and _contains(text, "my availability", "i am available", "i'm available", "available on", "available at", "booked"):
        subtypes.add("availability_submitted")
    explicit_time = _explicit_schedule(text)
    replacement_language = _contains(text, "replacement", "rescheduled to", "new interview time", "new time is")
    confirmation_language = _contains(text, "confirmed", "confirmation", "is scheduled", "has been scheduled", "you're scheduled", "you are scheduled")
    if replacement_language and confirmation_language and explicit_time:
        subtypes.add("replacement_confirmed")
    elif confirmation_language and explicit_time:
        subtypes.add("schedule_confirmed")
    if _contains(text, "need to reschedule", "please reschedule", "must reschedule", "change the interview time", "change your interview"):
        subtypes.add("reschedule_requested")
    if _contains(text, "interview has been cancelled", "interview has been canceled", "interview is cancelled", "interview is canceled", "cancelling the interview", "canceling the interview"):
        subtypes.add("cancellation")
    if _contains(text, "interview is complete", "interview has concluded", "thank you for interviewing", "completed the assessment"):
        subtypes.add("awaiting_result")
    # A confirmation can be phrased as "your interview is confirmed" without
    # saying the word "schedule".  The structured subtype still belongs under
    # the broad scheduling category for deterministic downstream filters.
    if subtypes - {"awaiting_result"}:
        categories.add("scheduling")

    if direction == "inbound" and _contains(text, "recruiter", "talent acquisition", "opportunity", "open role", "are you interested"):
        categories.add("inbound_recruiter_outreach")
    if direction == "outbound" and _contains(text, "reaching out", "interested in the", "my application", "would love to connect"):
        categories.add("outbound_cold_outreach")
    if _contains(text, "please reply", "please respond", "please let us know", "action required", "response requested") or "booking_requested" in subtypes:
        categories.add("follow_up_needed")

    attachment_hint = bool(normalized.get("attachment_names")) and _contains(
        " ".join(str(name).casefold() for name in normalized.get("attachment_names", ())),
        ".ics", "calendar", "invite",
    )
    # A bare attachment tells the reviewer where to look; it is never evidence
    # of an appointment time because attachment content is intentionally absent.
    if not categories:
        categories.add("unknown")
    return {
        "vocabulary_version": CATEGORY_VOCABULARY_VERSION,
        "categories": tuple(sorted(categories)),
        "scheduling_subtypes": tuple(sorted(subtypes)),
        "explicit_schedule": explicit_time,
        "attachment_schedule_hint": attachment_hint,
        "deadline": extract_deadline(normalized),
    }


def validate_company_email_domains(company_domains: Mapping[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    """Validate/write-gate per-company domains, rejecting shared ATS domains."""
    result: dict[str, tuple[str, ...]] = {}
    for company, values in sorted(company_domains.items(), key=lambda item: _company_key(item[0])):
        key = _company_key(company)
        if not key:
            raise ValueError("company email-domain mapping has an empty company")
        domains = []
        if isinstance(values, str):
            values = (values,)
        for value in values:
            domain = _domain(value)
            if not domain:
                raise ValueError(f"{company}: invalid email domain {value!r}")
            if _domain_is_shared_ats(domain):
                raise ValueError(f"{company}: shared ATS domain {domain!r} cannot identify a company")
            domains.append(domain)
        result[key] = tuple(sorted(set(domains)))
    return result


def _normalize_applications(applications: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for raw in applications:
        if not isinstance(raw, Mapping):
            continue
        slug = _text(raw.get("slug"))
        company = _text(raw.get("company"))
        if not slug or not company:
            continue
        jobs_out = []
        jobs = raw.get("jobs") if isinstance(raw.get("jobs"), Sequence) else []
        for index, job in enumerate(jobs):
            if not isinstance(job, Mapping):
                continue
            jobs_out.append({
                "index": index,
                "role": _text(job.get("role")),
                "status": _norm(job.get("status")),
                "url": _text(job.get("url")),
                "store_key": _text(job.get("store_key")),
                "requisition_id": _text(job.get("requisition_id") or job.get("req_id")),
                "progress": dict(job.get("progress") or {}) if isinstance(job.get("progress"), Mapping) else {},
            })
        normalized.append({"slug": slug, "company": company, "company_key": _company_key(company), "jobs": jobs_out})
    return sorted(normalized, key=lambda app: app["slug"])


def _company_for_domain(sender_domain: str, company_domains: Mapping[str, tuple[str, ...]]) -> str | None:
    matches = [company for company, domains in company_domains.items() if any(sender_domain == domain or sender_domain.endswith("." + domain) for domain in domains)]
    return matches[0] if len(matches) == 1 else None


def _token_job_matches(text: str, app: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Match full URLs or prefixed req IDs.  Bare numbers intentionally vanish."""
    urls = {_norm(url.rstrip(".,;)")) for url in _URL_RE.findall(text)}
    req_ids = {_norm(match.group(1)) for match in _REQ_RE.finditer(text)}

    def req_variants(value: Any) -> set[str]:
        token = _norm(value)
        if not token:
            return set()
        # Providers disagree on whether the ``REQ-`` marker belongs in the
        # requisition value.  It is still a structured token because the body
        # had the marker; normalize only this known presentation difference.
        stripped = re.sub(r"^req(?:uisition)?\s*[-#:]*\s*", "", token)
        return {token, stripped} - {""}
    matches = []
    for job in app["jobs"]:
        job_url = _norm(job.get("url")).rstrip(".,;)")
        store_key = _norm(job.get("store_key"))
        requisition = _norm(job.get("requisition_id"))
        url_match = bool(job_url and any(url == job_url or url.startswith(job_url + "?") for url in urls))
        # Store keys are accepted only when they are carried by a full URL. A
        # standalone numeric key could be a ticket, zip, or another employer's req.
        store_match = bool(store_key and any(store_key in url for url in urls))
        req_match = bool(req_variants(requisition) & req_ids)
        if url_match or store_match or req_match:
            matches.append(job)
    return matches


def _link(company: str | None, slug: str | None, job: Mapping[str, Any] | None, *, derivation: str, confidence: str, candidates: Sequence[str] = (), note: str | None = None) -> dict[str, Any]:
    return {
        "company": company,
        "application_slug": slug,
        "job_index": job.get("index") if job else None,
        "role": job.get("role") if job else None,
        "derivation": derivation,
        "confidence": confidence,
        "candidates": tuple(sorted(set(candidates))),
        "note": note,
    }


def _human_link(message_key: str, confirmations: Mapping[str, Any], apps: list[dict[str, Any]]) -> dict[str, Any] | None:
    raw = confirmations.get(message_key)
    if not isinstance(raw, Mapping):
        return None
    slug = _text(raw.get("application_slug") or raw.get("slug"))
    app = next((item for item in apps if item["slug"] == slug), None)
    if app is None:
        return None
    job_index = raw.get("job_index")
    role = _norm(raw.get("role"))
    job = None
    if isinstance(job_index, int) and 0 <= job_index < len(app["jobs"]):
        job = app["jobs"][job_index]
    elif role:
        possible = [item for item in app["jobs"] if _norm(item["role"]) == role]
        job = possible[0] if len(possible) == 1 else None
    return _link(app["company"], app["slug"], job, derivation="human_confirmed", confidence="exact")


def _thread_candidates(thread_keys: Sequence[str], thread_links: Mapping[str, Any], company_key: str | None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for key in thread_keys:
        raw = thread_links.get(key)
        records = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) else [raw]
        for record in records:
            if not isinstance(record, Mapping):
                continue
            if company_key and _company_key(record.get("company")) not in {"", company_key}:
                continue  # never carry Company A's thread link into Company B mail
            found.append(dict(record))
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in found:
        marker = (record.get("application_slug"), record.get("job_index"), record.get("role"), _company_key(record.get("company")))
        unique[marker] = record
    return [unique[key] for key in sorted(unique, key=lambda value: tuple(str(item) for item in value))]


def link_message(
    message: Mapping[str, Any],
    applications: Iterable[Mapping[str, Any]],
    company_domains: Mapping[str, Iterable[str]],
    *,
    thread_links: Mapping[str, Any] | None = None,
    human_confirmations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the association ladder without guessing a company or a role."""
    normalized = normalize_stored_message(message) if "body_text" not in message else dict(message)
    apps = _normalize_applications(applications)
    domains = validate_company_email_domains(company_domains)
    confirmations = human_confirmations or {}
    confirmed = _human_link(str(normalized["message_key"]), confirmations, apps)
    if confirmed is not None:
        return confirmed

    sender_domain = _domain(normalized.get("sender_domain"))
    candidate_domains = (sender_domain,) if normalized.get("direction") != "outbound" else tuple(normalized.get("recipient_domains", ()))
    shared_vendor = next((domain for domain in candidate_domains if _domain_is_shared_ats(domain)), "")
    if shared_vendor:
        return _link(None, None, None, derivation="shared_ats_vendor", confidence="none", note="sender domain is a shared ATS vendor")
    recognized_companies = {_company_for_domain(domain, domains) for domain in candidate_domains if domain}
    recognized_companies.discard(None)
    company_key = next(iter(recognized_companies)) if len(recognized_companies) == 1 else None
    company_apps = [app for app in apps if app["company_key"] == company_key] if company_key else []
    company = company_apps[0]["company"] if company_apps else None
    text = f"{normalized.get('subject', '')}\n{normalized.get('body_text', '')}"
    if company_apps:
        matched = [(app, job) for app in company_apps for job in _token_job_matches(text, app)]
        if len(matched) == 1:
            app, job = matched[0]
            return _link(app["company"], app["slug"], job, derivation="direct_rule", confidence="exact")
        if len(matched) > 1:
            return _link(company, None, None, derivation="structured_token_ambiguous", confidence="weak", candidates=[app["slug"] for app, _ in matched], note="structured token matched more than one job")

    inherited = _thread_candidates(normalized.get("thread_keys", ()), thread_links or {}, company_key)
    if len(inherited) == 1:
        prior = inherited[0]
        return _link(
            company or _text(prior.get("company")) or None,
            _text(prior.get("application_slug")) or None,
            {"index": prior.get("job_index"), "role": prior.get("role")} if prior.get("role") is not None else None,
            derivation="thread_inheritance", confidence="strong",
        )
    if len(inherited) > 1:
        return _link(company, None, None, derivation="thread_ambiguous", confidence="weak", candidates=[_text(item.get("application_slug")) for item in inherited], note="thread has conflicting links")

    active = [app for app in company_apps if any(job.get("status") in _ACTIVE_STATUSES for job in app["jobs"])]
    if len(active) == 1:
        return _link(active[0]["company"], active[0]["slug"], None, derivation="temporal_correlation", confidence="strong")
    if len(active) > 1:
        return _link(company, None, None, derivation="temporal_correlation", confidence="weak", candidates=[app["slug"] for app in active], note="multiple active applications; role intentionally unresolved")
    return _link(company, None, None, derivation="unresolved", confidence="none")


def _phase_for(categories: set[str], text: str, job: Mapping[str, Any] | None) -> tuple[str, str | None]:
    existing = (job or {}).get("progress", {}).get("phase") if isinstance((job or {}).get("progress"), Mapping) else None
    if existing and existing not in {"application_prep", "application_review", "unknown"}:
        return str(existing), None
    if "assessment" in categories:
        return "assessment", None
    if _contains(text, "recruiter", "talent", "phone screen"):
        return "recruiter_screen", None
    if _contains(text, "hiring manager"):
        return "hiring_manager", None
    if _contains(text, "technical", "coding", "system design"):
        return "technical_interview", None
    if _contains(text, "onsite", "on-site", "interview loop"):
        return "interview_loop", None
    if "offer" in categories:
        return "offer", None
    return "other", "Interview"


def _safe_exact_role(link: Mapping[str, Any]) -> bool:
    return link.get("derivation") in {"direct_rule", "human_confirmed"} and link.get("confidence") == "exact" and link.get("job_index") is not None


def _proposal_base(message: Mapping[str, Any], link: Mapping[str, Any], *, kind: str, target: Mapping[str, Any], guards: Sequence[str], ready: bool) -> dict[str, Any]:
    return {
        "kind": kind,
        "auto_apply": False,
        "requires_exact_message_verification": True,
        "ready_for_tracker_transaction": ready,
        "message_key": message["message_key"],
        "application_slug": link.get("application_slug"),
        "job_index": link.get("job_index"),
        "role": link.get("role"),
        "target": dict(target),
        "evidence": {
            "source": {"kind": "email", "ref": message["message_key"]},
            "derivation": link.get("derivation"),
            "confidence": link.get("confidence"),
            "body_sha256": sha256(_text(message.get("body_text")).encode("utf-8")).hexdigest() if message.get("body_present") else None,
        },
        "guards": tuple(guards),
    }


def propose_reconciliation(
    message: Mapping[str, Any], link: Mapping[str, Any], applications: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Return guarded status/progress/calendar proposals; never execute them."""
    normalized = normalize_stored_message(message) if "body_text" not in message else dict(message)
    categories = set(categorize_message(normalized)["categories"])
    classification = categorize_message(normalized)
    subtypes = set(classification["scheduling_subtypes"])
    app = next((item for item in _normalize_applications(applications) if item["slug"] == link.get("application_slug")), None)
    job = None
    if app is not None and isinstance(link.get("job_index"), int):
        candidates = [item for item in app["jobs"] if item["index"] == link["job_index"]]
        job = candidates[0] if candidates else None
    exact_role = _safe_exact_role(link)
    direct_or_human = link.get("derivation") in {"direct_rule", "human_confirmed"}
    text = f"{normalized.get('subject', '')}\n{normalized.get('body_text', '')}".casefold()
    proposal: list[dict[str, Any]] = []

    def status(target_status: str, *, per_role: bool, evidence_name: str) -> None:
        ready = bool(normalized.get("body_present")) and direct_or_human and (exact_role if per_role else bool(link.get("application_slug")))
        guards = ["re-open exact stored message body", "require unambiguous application link", f"explicit {evidence_name} language"]
        if per_role:
            guards.append("require exact role link; do not roll other postings")
        else:
            guards.append("require explicit whole-application scope")
            if not _contains(text, "all roles", "all applications", "entire application"):
                ready = False
        if link.get("derivation") not in {"direct_rule", "human_confirmed"}:
            guards.append("thread/temporal/AI links are triage only")
        proposal.append(_proposal_base(normalized, link, kind="status_transition", target={"status": target_status, "scope": "per_role" if per_role else "whole_application"}, guards=guards, ready=ready))

    if "receipt" in categories:
        # A direct role receipt is safe to propose per-role.  A generic receipt
        # still needs human whole-application scope confirmation.
        status("applied", per_role=exact_role, evidence_name="receipt")
    if "rejection" in categories:
        status("rejected", per_role=exact_role, evidence_name="rejection")
    if "interview_invite" in categories:
        status("in_progress", per_role=True, evidence_name="interview/screen")

    phase, label = _phase_for(categories, text, job)
    state_by_subtype = {
        "booking_requested": ("booking_required", "create_action_needed"),
        "availability_submitted": ("awaiting_schedule", "move_to_waiting"),
        "schedule_confirmed": ("scheduled", "confirm_occurrence"),
        "reschedule_requested": ("reschedule_required", "request_reschedule"),
        "replacement_confirmed": ("scheduled", "append_replacement"),
        "cancellation": ("action_required", "cancel_occurrence"),
        "awaiting_result": ("awaiting_result", "mark_complete"),
    }
    for subtype in sorted(subtypes):
        state, calendar_action = state_by_subtype[subtype]
        schedule = classification.get("explicit_schedule")
        ready = bool(normalized.get("body_present")) and exact_role
        guards = ["re-open exact stored message body", "require exact role link", "apply meta.yaml and calendar.md in one tracker transaction"]
        calendar: dict[str, Any] = {"action": calendar_action, "deadline": classification.get("deadline")}
        if subtype in {"schedule_confirmed", "replacement_confirmed"}:
            if not schedule:
                ready = False
                guards.append("require explicit body date, time, and timezone; attachment metadata is insufficient")
            else:
                calendar.update(schedule)
            if subtype == "replacement_confirmed":
                calendar["preserve_existing_occurrence"] = True
                guards.append("require existing calendar item; mark old occurrence superseded")
        if subtype == "cancellation":
            guards.append("cancellation never rejects the role without separate explicit closure evidence")
        if subtype == "awaiting_result":
            guards.append("never infer completion from wall clock")
        if link.get("derivation") not in {"direct_rule", "human_confirmed"}:
            guards.append("thread/temporal/AI links are triage only")
        target = {"progress": {"phase": phase, "state": state, **({"label": label} if label else {})}, "calendar": calendar, "scheduling_subtype": subtype}
        proposal.append(_proposal_base(normalized, link, kind="progress_calendar", target=target, guards=guards, ready=ready))

    if "offer" in categories:
        ready = bool(normalized.get("body_present")) and exact_role and direct_or_human
        proposal.append(_proposal_base(
            normalized, link, kind="progress", target={"progress": {"phase": "offer", "state": "waiting_employer"}},
            guards=("re-open exact stored message body", "require exact role link", "thread/temporal/AI links are triage only"), ready=ready,
        ))
    return proposal


def reverify_transition(
    proposal: Mapping[str, Any],
    load_stored_message: Callable[[str], Mapping[str, Any] | None],
    applications: Iterable[Mapping[str, Any]],
    company_domains: Mapping[str, Iterable[str]],
    *,
    human_confirmations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-open the exact stored body and prove a proposal still matches.

    ``load_stored_message`` is the only seam that knows the raw-store layout.
    A caller may execute a tracker transaction only after ``verified`` is true;
    this function itself remains entirely non-mutating.
    """
    key = _text(proposal.get("message_key"))
    if not key:
        return {"verified": False, "reason": "proposal has no message_key"}
    raw = load_stored_message(key)
    if not isinstance(raw, Mapping):
        return {"verified": False, "reason": "stored message was not found", "message_key": key}
    try:
        message = normalize_stored_message(raw)
    except ValueError as exc:
        return {"verified": False, "reason": str(exc), "message_key": key}
    if message["message_key"] != key:
        return {"verified": False, "reason": "stored message key mismatch", "message_key": key}
    if not message["body_present"]:
        return {"verified": False, "reason": "stored message body is unavailable", "message_key": key}
    link = link_message(message, applications, company_domains, human_confirmations=human_confirmations)
    candidates = propose_reconciliation(message, link, applications)
    wanted = (proposal.get("kind"), proposal.get("application_slug"), proposal.get("job_index"), proposal.get("target"))
    match = next((item for item in candidates if (item.get("kind"), item.get("application_slug"), item.get("job_index"), item.get("target")) == wanted), None)
    if match is None:
        return {"verified": False, "reason": "message no longer supports the proposed target", "message_key": key}
    if not match["ready_for_tracker_transaction"]:
        return {"verified": False, "reason": "proposal remains triage-only after exact-message verification", "message_key": key, "proposal": match}
    return {"verified": True, "message_key": key, "proposal": match}


def _public_record(message: Mapping[str, Any], classification: Mapping[str, Any], link: Mapping[str, Any]) -> dict[str, Any]:
    """Content-free derived record.  Do not put subjects, senders, or bodies here."""
    # Provider conversation IDs and RFC Message-IDs are useful only as internal
    # correlation material.  Some include a mail domain, so expose stable,
    # one-way neutral tokens rather than the provider values themselves.  The
    # same raw thread still maps to the same token across folders/accounts,
    # preserving sent-vs-inbound reply suppression in ``build_projections``.
    thread_keys = tuple(
        "thread-" + sha256(str(value).encode("utf-8")).hexdigest()[:24]
        for value in message.get("thread_keys", ())
        if _text(value)
    )
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "message_key": message["message_key"],
        "account": message.get("account"),
        "folder": message.get("folder"),
        "direction": message.get("direction"),
        "timestamp": message.get("timestamp"),
        "thread_keys": thread_keys,
        "tombstoned": bool(message.get("tombstoned")),
        "out_of_scope": bool(message.get("out_of_scope")),
        "categories": tuple(classification["categories"]),
        "scheduling_subtypes": tuple(classification["scheduling_subtypes"]),
        "deadline": classification.get("deadline"),
        "attachment_schedule_hint": bool(classification.get("attachment_schedule_hint")),
        "link": dict(link),
    }


def _needs_reply(item: Mapping[str, Any]) -> bool:
    """Whether a content-free inbound record represents a real response TODO.

    This predicate intentionally treats category as a safety gate, rather than
    a loose relevance hint.  Terminal/bulk categories win over any accidental
    keyword match, and a plain status update or schedule confirmation is not a
    response request.  New category values default to false until explicitly
    designated actionable here.
    """
    if item.get("direction") != "inbound":
        return False
    categories = {str(value) for value in item.get("categories", ())}
    if categories & NEEDS_REPLY_HARD_EXCLUSIONS:
        return False
    subtypes = {str(value) for value in item.get("scheduling_subtypes", ())}
    actionable_scheduling = subtypes & NEEDS_REPLY_ACTIONABLE_SCHEDULING_SUBTYPES
    # A confirmed/replacement time is an informational calendar event, not a
    # reply request.  This must win even when generic wording also set
    # ``follow_up_needed``; only a simultaneous booking/reschedule subtype can
    # make that unusual combination actionable.
    if {"schedule_confirmed", "replacement_confirmed"} & subtypes and not actionable_scheduling:
        return False
    # Be explicit for auditability even though it also falls through to the
    # false default below.  A neutral status update with no action cue must not
    # become a reply task merely because it is job-related.
    if categories == {"neutral_status_update"}:
        return False
    if categories & NEEDS_REPLY_ACTIONABLE_CATEGORIES:
        return True
    return bool(actionable_scheduling)


def build_projections(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build content-free reverse and triage queues from derived message records."""
    usable = [dict(item) for item in records if not item.get("tombstoned") and not item.get("out_of_scope")]
    usable.sort(key=lambda item: (str(item.get("timestamp") or ""), str(item.get("message_key") or "")))
    by_application: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []
    deadlines: list[dict[str, Any]] = []
    sent_by_thread: dict[str, list[str]] = defaultdict(list)
    for item in usable:
        if item.get("direction") == "outbound":
            for thread in item.get("thread_keys", ()):
                sent_by_thread[str(thread)].append(str(item.get("timestamp") or ""))
        link = item.get("link") or {}
        slug = _text(link.get("application_slug"))
        if slug:
            by_application[slug].append(item)
        if link.get("confidence") in {"none", "weak"} or not slug:
            unresolved.append(item)
        if item.get("deadline"):
            deadlines.append(item)
    needs_reply = []
    for item in usable:
        if not _needs_reply(item):
            continue
        timestamp = str(item.get("timestamp") or "")
        related_sent = [value for thread in item.get("thread_keys", ()) for value in sent_by_thread.get(str(thread), ())]
        if any(value > timestamp for value in related_sent):
            continue
        needs_reply.append(item)
    for values in by_application.values():
        values.sort(key=lambda item: (str(item.get("timestamp") or ""), str(item.get("message_key") or "")))
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "by_application": {slug: by_application[slug] for slug in sorted(by_application)},
        "unresolved": unresolved,
        "needs_reply": needs_reply,
        "deadlines": sorted(deadlines, key=lambda item: (str((item.get("deadline") or {}).get("due_at") or ""), str(item.get("message_key") or ""))),
    }


def reconcile_messages(
    messages: Iterable[Mapping[str, Any]],
    applications: Iterable[Mapping[str, Any]],
    company_domains: Mapping[str, Iterable[str]],
    *,
    human_confirmations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic derived records plus reverse/triage projections.

    Earlier messages in a correlated thread are supplied as inheritance evidence
    for later messages, but inheritance stays ``strong`` and therefore cannot
    make a status or offer proposal tracker-ready.
    """
    normalized = [normalize_stored_message(item) for item in messages]
    normalized.sort(key=lambda item: (str(item.get("timestamp") or ""), item["message_key"]))
    thread_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records = []
    for message in normalized:
        classification = categorize_message(message)
        link = link_message(message, applications, company_domains, thread_links=thread_links, human_confirmations=human_confirmations)
        record = _public_record(message, classification, link)
        records.append(record)
        if link.get("application_slug"):
            for thread in message.get("thread_keys", ()):
                thread_links[str(thread)].append(link)
    return {"records": records, "projections": build_projections(records)}
