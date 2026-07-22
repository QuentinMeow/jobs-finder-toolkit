"""Deterministic corpus and live-snapshot audit for high-stakes job filters."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
for _path in (HERE, HERE / "_vendor"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from job_metadata import (  # noqa: E402
    assess_required_yoe,
    assess_sponsorship,
)
from common import days_since, parse_dt  # noqa: E402
from location import assess_location  # noqa: E402
from scoring import assess_posting_quality, assess_title  # noqa: E402

CORPUS_PATH = HERE.parent / "filter_variants" / "corpus.yaml"
DOMAINS = {"location", "sponsorship", "title", "yoe", "quality"}

_LOCATION_MARKER_RE = re.compile(
    r"\b(?:remote|remotely|hybrid|distributed|anywhere|worldwide|"
    r"on[- ]site|onsite|in[- ]office)\b",
    re.I,
)
_SPONSOR_MARKER_RE = re.compile(
    r"\b(?:sponsor(?:ship|ing)?|visa|immigration|work authorization|"
    r"h-?1b|green card|perm)\b",
    re.I,
)
_TITLE_LEVEL_MARKER_RE = re.compile(
    r"\b(?:senior|sr|staff|principal|distinguished|fellow|lead|"
    r"member of technical staff|level [ivx]+)\b",
    re.I,
)
_YOE_MARKER_RE = re.compile(
    r"\b\d+(?:\.\d+)?\+?\s*(?:-|to)?\s*\d*(?:\.\d+)?\s*"
    r"(?:years?|yrs?)\b",
    re.I,
)


def load_corpus(path: Path = CORPUS_PATH) -> dict:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return data if isinstance(data, dict) else {}


def lint_corpus(corpus: dict) -> list[str]:
    errors: list[str] = []
    if corpus.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    variants = corpus.get("variants")
    if not isinstance(variants, list):
        return [*errors, "variants must be a list"]
    seen: set[str] = set()
    for index, case in enumerate(variants):
        prefix = f"variants[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            errors.append(f"{prefix}.id is required")
        elif case_id in seen:
            errors.append(f"{prefix}.id duplicates {case_id!r}")
        seen.add(case_id)
        if case.get("domain") not in DOMAINS:
            errors.append(f"{prefix}.domain must be one of {sorted(DOMAINS)}")
        if not isinstance(case.get("input"), dict):
            errors.append(f"{prefix}.input must be a mapping")
        if not isinstance(case.get("expect"), dict):
            errors.append(f"{prefix}.expect must be a mapping")
    return errors


def run_case(case: dict) -> dict:
    """Dispatch one corpus case to its canonical production assessor."""
    domain = case["domain"]
    inputs = case.get("input") or {}
    if domain == "location":
        return assess_location(
            inputs.get("location"),
            case.get("policy") or {},
            title=inputs.get("title"),
            description=inputs.get("description"),
            workplace_hint=inputs.get("workplace_hint"),
            hint_trusted=inputs.get("hint_trusted", True),
        ).to_dict()
    if domain == "sponsorship":
        return assess_sponsorship(inputs.get("text"))
    if domain == "title":
        return assess_title(
            inputs.get("title"), (inputs.get("profile") or {}).get("titles"))
    if domain == "yoe":
        return assess_required_yoe(inputs.get("text"))
    if domain == "quality":
        return assess_posting_quality(inputs.get("title"), inputs.get("description"))
    raise ValueError(f"unsupported variant domain: {domain}")


def _mismatches(expect: dict, actual: dict) -> list[str]:
    errors: list[str] = []
    for key, wanted in expect.items():
        if key == "evidence_contains":
            missing = [x for x in wanted if x not in actual.get("evidence", [])]
            if missing:
                errors.append(f"evidence missing {missing!r}")
        elif key == "review_contains":
            missing = [x for x in wanted if x not in actual.get("review_reasons", [])]
            if missing:
                errors.append(f"review_reasons missing {missing!r}")
        elif actual.get(key) != wanted:
            errors.append(f"{key}: expected {wanted!r}, got {actual.get(key)!r}")
    return errors


def check_corpus(corpus: dict) -> list[str]:
    errors = [f"LINT {message}" for message in lint_corpus(corpus)]
    if errors:
        return errors
    for case in corpus["variants"]:
        try:
            actual = run_case(case)
        except Exception as exc:  # noqa: BLE001 - report every corpus case
            errors.append(f"CHECK {case['id']}: raised {exc}")
            continue
        for message in _mismatches(case["expect"], actual):
            errors.append(f"CHECK {case['id']}: {message}")
    return errors


def _rule_family(rule_id: str) -> str:
    """Drop a rule ID's specific literal token, keeping only ``domain.class``.

    e.g. ``sponsorship.negative.no sponsorship`` -> ``sponsorship.negative`` and
    ``title.included.software engineer`` -> ``title.included``. This is what keeps
    a signature grouping cosmetic variants without embedding any literal excerpt.
    """
    parts = str(rule_id).split(".", 2)
    return ".".join(parts[:2]) if len(parts) >= 2 else str(rule_id)


def structural_signature(domain: str, inputs: dict, actual: dict) -> str:
    """A privacy-safe structural signature built ONLY from the assessment shape.

    It is the accepted SEMANTIC structure — domain, decision/confidence, evidence
    SOURCE CHANNEL classes, polarity/conflict state, and rule FAMILY — never an
    exact rule-ID combination or a literal excerpt. It carries no company name,
    job title, URL, date, salary, or raw description/location prose, so
    punctuation/capitalization changes and different company/title/location text
    collapse to one signature; a genuinely new conflict, polarity, evidence
    channel, or rule family does not.
    """
    parts = [
        domain,
        str(actual.get("decision") or actual.get("result") or ""),
        str(actual.get("confidence") or ""),
    ]
    if domain == "location":
        # The review-reason set is the conflict/polarity family AND already names
        # the evidence CHANNELS in tension (e.g. ``remote_onsite_conflict`` =
        # remote-channel vs onsite-channel; ``mixed_us_foreign_scope`` = two geo
        # channels; ``uncorroborated_ats_workplace_hint`` = ATS channel alone).
        # Keying on it — not the exact category/workplace or the incidental
        # evidence rule IDs — means different company/title/location TEXT with the
        # same conflict groups, while a genuinely new conflict or polarity shape
        # (a new review-reason string, which only new code can introduce) does not.
        parts.append(",".join(sorted(set(actual.get("review_reasons", [])))))
    elif domain == "title":
        parts += [
            ",".join(sorted({_rule_family(r) for r in actual.get("rule_ids", [])})),
            ",".join(sorted(set(actual.get("review_reasons", [])))),
        ]
    elif domain == "sponsorship":
        parts += [
            str(actual.get("verdict") or ""),
            ",".join(sorted({_rule_family(r) for r in actual.get("rule_ids", [])})),
        ]
    elif domain == "quality":
        parts.append(
            ",".join(sorted({_rule_family(r) for r in actual.get("rule_ids", [])})))
    else:  # yoe
        parts.append(str(actual.get("requirement_kind") or ""))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def known_signatures(corpus: dict) -> set[str]:
    return {
        structural_signature(case["domain"], case["input"], run_case(case))
        for case in corpus.get("variants", [])
    }


def _excerpt(text: str, marker: re.Pattern, width: int = 280) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    match = marker.search(text)
    if not match:
        return text[:width]
    start = max(0, match.start() - width // 3)
    return text[start:start + width]


def audit_postings(
    postings: list[dict],
    profile: dict,
    corpus: dict,
    *,
    max_age: float | None = None,
    now=None,
) -> list[dict]:
    """Return grouped, unlabeled signal-bearing variants from a private snapshot.

    The audit replays the SAME gate order as production
    (``search_jobs.filter_score_rank``): quality -> title -> date -> location ->
    sponsorship -> YOE.
    A posting the production title gate would reject never generates a downstream
    location/sponsorship/YOE variant; a definite location ``no_match`` short-
    circuits the sponsorship/YOE gates exactly as production drops the row before
    reaching them. Only PROFILE-RELEVANT, signal-bearing ``review`` shapes are
    emitted, and each is grouped by its coarse semantic signature so a whole
    family of postings collapses to one label stub rather than one per wording.
    """
    known = known_signatures(corpus)
    pending: dict[tuple[str, str], dict] = {}
    titles_cfg = profile.get("titles") or {}
    loc_cfg = profile.get("location", {}) or {}
    location_policy = {
        "metro": loc_cfg.get("preferred") or [],
        "allow_us_remote": loc_cfg.get("allow_remote", True),
        "us_only": loc_cfg.get("us_only", False),
        "require_match": loc_cfg.get("require_match", False),
    }
    visa_cfg = profile.get("visa", {}) or {}
    needs_sponsorship = bool(visa_cfg.get("needs_sponsorship"))
    visa_policy = visa_cfg.get("policy", "exclude_negative")
    cap = profile.get("max_years_experience")

    for posting in postings:
        title = str(posting.get("title") or "")
        description = str(posting.get("description") or "")
        location = str(posting.get("location") or "")

        # --- Gate 0: posting quality (mirrors scoring.posting_quality_ok) -
        quality_case = {"domain": "quality",
                        "input": {"title": title, "description": description}}
        quality_actual = run_case(quality_case)
        if quality_actual["decision"] == "no_match":
            continue  # an unfilled ATS template is dropped before any other gate
        if quality_actual["decision"] == "review":
            _add_pending(
                pending, "quality", quality_case["input"], quality_actual, known,
                posting, _excerpt(description, _LOCATION_MARKER_RE))

        # --- Gate 1: title (mirrors scoring.title_ok) ---------------------
        title_case = {"domain": "title", "input": {"title": title, "profile": profile}}
        title_actual = run_case(title_case)
        if title_actual["decision"] == "no_match":
            continue  # production drops the posting; no downstream variants
        if title_actual["decision"] == "review":
            _add_pending(
                pending, "title", title_case["input"], title_actual, known,
                posting, title)

        # --- Gate 1b: posting age (mirrors scoring.date_ok) ---------------
        posted_at = parse_dt(posting.get("posted_at"))
        age_days = days_since(posted_at, now) if posted_at and now else None
        if max_age is not None and age_days is not None and age_days > max_age:
            continue

        # --- Gate 2: location (mirrors scoring.location_ok) ---------------
        hint_trusted = not str(posting.get("source") or "").startswith("jobspy:")
        location_inputs = {
            "title": title,
            "location": location,
            "description": description,
            "workplace_hint": posting.get("remote"),
            "hint_trusted": hint_trusted,
        }
        location_actual = assess_location(
            location, location_policy, title=title, description=description,
            workplace_hint=posting.get("remote"), hint_trusted=hint_trusted,
        ).to_dict()
        if location_actual["decision"] == "no_match":
            continue  # definite non-match: production drops before visa/YOE
        if location_actual["decision"] == "review":
            _add_pending(
                pending, "location", location_inputs, location_actual, known,
                posting, _excerpt(description, _LOCATION_MARKER_RE))

        # --- Gate 3: sponsorship (mirrors scoring.visa_ok) ----------------
        if needs_sponsorship:
            sponsorship = assess_sponsorship(description)
            if sponsorship["decision"] == "no_match":
                continue  # explicit denial: production drops before YOE
            if sponsorship["decision"] == "review" and (
                    sponsorship["signal_present"] or visa_policy == "require_positive"):
                inputs = {"text": _excerpt(description, _SPONSOR_MARKER_RE)}
                _add_pending(
                    pending, "sponsorship", inputs, sponsorship, known, posting,
                    inputs["text"])

        # --- Gate 4: required YOE (mirrors scoring.experience_ok) ---------
        blob = "\n".join(x for x in (title, description) if x)
        yoe = assess_required_yoe(
            blob, cap=int(cap) if cap is not None else None)
        # Only a STATED-but-non-decisive requirement is signal-bearing; a
        # "not_stated" YOE (no requirement extracted) is benign and skipped.
        if yoe["decision"] == "review" and yoe.get("min") is not None:
            inputs = {"text": _excerpt(blob, _YOE_MARKER_RE)}
            _add_pending(
                pending, "yoe", inputs, yoe, known, posting, inputs["text"])

    return list(pending.values())


def _add_pending(
    pending: dict,
    domain: str,
    inputs: dict,
    actual: dict,
    known: set[str],
    posting: dict,
    excerpt: str,
) -> None:
    signature = structural_signature(domain, inputs, actual)
    if signature in known:
        return
    key = (domain, signature)
    if key not in pending:
        pending[key] = {
            "id": f"pending-{domain}-{signature[:8]}",
            "domain": domain,
            "signature": signature,
            "count": 0,
            "example": {
                "source": posting.get("source"),
                "company": posting.get("company"),
                "title": posting.get("title"),
                "url": posting.get("url"),
                "location": posting.get("location"),
                "remote": posting.get("remote"),
                "excerpt": excerpt,
            },
            "actual": actual,
            "label_required": {
                "decision": "match | no_match | review",
                "notes": "Verify privately, then add a fictional minimal corpus case.",
            },
        }
    pending[key]["count"] += 1


def _reject_family(domain: str, actual: dict) -> str:
    """Coarse ``domain:rule-family`` key for a first-reject hard `no_match`.

    Deliberately coarser than `structural_signature` (no confidence/evidence
    split needed here) — this groups every hard-reject variant of the SAME rule
    family (e.g. every ``title.excluded.*`` literal) under one census row.
    """
    # Location ``rule_ids`` begin with evidence channels (for example an ATS
    # workplace hint), not the reason the row failed. The decisive no-match
    # classification is its category (foreign/other_us); using the first rule ID
    # produced misleading census families such as ``location:ats_hint_hybrid``.
    if domain == "location":
        return f"location:{actual.get('category') or 'unknown'}"
    if domain == "yoe":
        return "yoe:exceeds_cap"
    rule_ids = actual.get("rule_ids") or []
    if rule_ids:
        return f"{domain}:{_rule_family(rule_ids[0])}"
    verdict = actual.get("verdict")
    return f"{domain}:{verdict}" if verdict else domain


def first_reject_census(
    postings: list[dict],
    profile: dict,
    *,
    sample_size: int = 5,
    max_age: float | None = None,
    now=None,
) -> dict:
    """Replay the production gate order and report every hard `no_match`.

    Decision 3b: unlike `audit_postings` (signal-bearing `review` rows only,
    which SKIPS a title/location/sponsorship/YOE `no_match` outright), this
    walks the SAME gate order (quality -> title -> date -> location -> sponsorship ->
    YOE, mirroring `search_jobs.filter_score_rank`) and records, per FIRST-
    reject rule family, the total count and a small, DETERMINISTIC sample (with
    a JD excerpt) — the artifact needed to check false-negative recall, since
    "snapshot audit clean" from `audit_postings` alone cannot speak to what the
    hard gates silently dropped. Production gate order is untouched; a posting
    that never reaches a later gate is never counted under that gate.
    """
    titles_cfg = profile.get("titles") or {}
    loc_cfg = profile.get("location", {}) or {}
    location_policy = {
        "metro": loc_cfg.get("preferred") or [],
        "allow_us_remote": loc_cfg.get("allow_remote", True),
        "us_only": loc_cfg.get("us_only", False),
        "require_match": loc_cfg.get("require_match", False),
    }
    visa_cfg = profile.get("visa", {}) or {}
    needs_sponsorship = bool(visa_cfg.get("needs_sponsorship"))
    cap = profile.get("max_years_experience")

    families: dict[str, dict] = {}

    def _record(family: str, posting: dict, excerpt: str) -> None:
        entry = families.setdefault(family, {"count": 0, "candidates": []})
        entry["count"] += 1
        signature = hashlib.sha256(
            f"{posting.get('source')}|{posting.get('url')}|{posting.get('title')}"
            .encode("utf-8")
        ).hexdigest()
        entry["candidates"].append((signature, {
            "source": posting.get("source"),
            "company": posting.get("company"),
            "title": posting.get("title"),
            "url": posting.get("url"),
            "location": posting.get("location"),
            "excerpt": excerpt,
        }))

    for posting in postings:
        title = str(posting.get("title") or "")
        description = str(posting.get("description") or "")
        location = str(posting.get("location") or "")

        quality_actual = assess_posting_quality(title, description)
        if quality_actual["decision"] == "no_match":
            _record(_reject_family("quality", quality_actual), posting,
                    _excerpt(description, _LOCATION_MARKER_RE))
            continue

        title_actual = run_case(
            {"domain": "title", "input": {"title": title, "profile": profile}})
        if title_actual["decision"] == "no_match":
            _record(_reject_family("title", title_actual), posting, title)
            continue

        posted_at = parse_dt(posting.get("posted_at"))
        age_days = days_since(posted_at, now) if posted_at and now else None
        if max_age is not None and age_days is not None and age_days > max_age:
            _record("date:older_than_window", posting, title)
            continue

        hint_trusted = not str(posting.get("source") or "").startswith("jobspy:")
        location_actual = assess_location(
            location, location_policy, title=title, description=description,
            workplace_hint=posting.get("remote"), hint_trusted=hint_trusted,
        ).to_dict()
        if location_actual["decision"] == "no_match":
            _record(_reject_family("location", location_actual), posting,
                    _excerpt(description, _LOCATION_MARKER_RE))
            continue

        if needs_sponsorship:
            sponsorship = assess_sponsorship(description)
            if sponsorship["decision"] == "no_match":
                _record(_reject_family("sponsorship", sponsorship), posting,
                        _excerpt(description, _SPONSOR_MARKER_RE))
                continue

        blob = "\n".join(x for x in (title, description) if x)
        yoe = assess_required_yoe(blob, cap=int(cap) if cap is not None else None)
        if yoe["decision"] == "no_match":
            _record(_reject_family("yoe", yoe), posting,
                    _excerpt(blob, _YOE_MARKER_RE))

    report = []
    for family in sorted(families):
        entry = families[family]
        sample = [example for _sig, example in
                  sorted(entry["candidates"], key=lambda item: item[0])[:sample_size]]
        report.append({"family": family, "count": entry["count"], "sample": sample})
    return {
        "total_rejected": sum(entry["count"] for entry in families.values()),
        "families": report,
    }
