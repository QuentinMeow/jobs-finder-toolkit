"""Filtering and scoring of postings against a job-matching profile."""
from __future__ import annotations

import re
from collections import Counter

from common import JobPosting, normalize, term_matches
from job_metadata import (
    assess_required_yoe,
    assess_sponsorship,
    classify_level,
    classify_level_from_jd_body,
    extract_required_yoe_details,
)
from location import assess_location
from visa import classify_visa, visa_tags

# Engineering role nouns that make a broad domain include ("infrastructure",
# "platform", ...) an actual engineering title rather than a business/finance use.
_ROLE_NOUN_RE = re.compile(
    r"\b(engineer|engineers|engineering|developer|developers|swe|sde|sre|"
    r"programmer|architect)\b")

# Standalone role families that are self-sufficient titles even without one of the
# nouns above (kept so a legitimate SRE / reliability title is never guarded out).
_STANDALONE_ROLE_FAMILIES = (
    "sre", "site reliability", "site reliability engineer", "reliability engineer",
)

# Broad single-word/domain include tokens that name a technical AREA, not a role.
# On their own — with no engineering role noun in the title — they admit
# non-engineering postings (e.g. a finance "Capital Markets Infrastructure
# Financing" role), so a title matched ONLY via one of these must also show an
# engineering role noun or a standalone role family.
_BROAD_DOMAIN_TOKENS = frozenset({
    "infrastructure", "platform", "compute", "cloud", "data", "systems",
    "distributed systems", "networking", "network", "storage", "security",
    "observability", "reliability", "devops", "api", "services", "backend",
    "back end", "frontend", "front end", "full stack", "fullstack", "ml",
    "ai", "machine learning",
})

# Leadership words that are ambiguous between an IC and a people-manager role and
# are NOT already captured by the profile's explicit exclude list. Genuine
# ambiguity is sent to review (conservative) rather than silently accepted; an
# explicit manager/director/VP/"head of" title is still a hard exclude above.
_AMBIGUOUS_LEADERSHIP_RE = re.compile(r"\b(lead|leader|leadership)\b")
_EARLY_CAREER_RE = re.compile(
    r"\b(?:new\s+(?:college\s+)?grad(?:uate)?|"
    r"graduate\s+(?:software\s+)?engineer)\b",
    re.I,
)

# Generic, evidence-bearing NON-TECHNICAL OCCUPATION lexicon (Decision 3a) — a
# small, whole-term set naming common non-engineering occupation FAMILIES, never
# a per-title/per-company alias. A title that hits one of these AND carries no
# engineering role noun (see `_title_has_role`) is a definite non-technical
# occupation and stays a hard `no_match`, matching the asymmetry already given
# to the profile's explicit excludes. A title that ALSO carries a role noun
# (e.g. "Customer Success Engineer", "Sales Engineer") is genuinely ambiguous,
# not definite, so the lexicon is skipped for it — it falls through to the
# normal include/broad-domain/leadership logic (and, worst case, the
# `title.occupation_ambiguous` review residual) instead of a hard reject.
_NONTECHNICAL_OCCUPATION_RULES = [
    ("sales", re.compile(
        r"\bsales\b|\baccount executive\b|\bbusiness development\b|"
        r"\bbdr\b|\bsdr\b|\bcustomer success\b",
        re.I)),
    ("marketing", re.compile(
        r"\bmarketing\b|\badvertising\b|\bbrand\s+manager\b|"
        r"\bcontent\s+strategist\b|\bpartnerships?\s+(?:lead|manager|director)\b|"
        r"\bpublic relations\b|\bcommunications\s+(?:lead|manager|specialist)\b",
        re.I)),
    ("recruiting", re.compile(
        r"\brecruit(?:er|ing|ment)\b|\btalent acquisition\b|"
        r"\bpeople operations\b|\bhuman resources\b|\bhr\b",
        re.I)),
    ("finance", re.compile(
        r"\bfinance\b|\bfinancial\b|\bcapital markets?\b|\bfinancing\b|"
        r"\baccounting\b|\baccountant\b|\bbanking\b|\bbanker\b|"
        r"\bunderwrit(?:er|ing)\b|\bportfolio manager\b|"
        r"\binvestment (?:banking|analyst)\b",
        re.I)),
    ("legal", re.compile(
        r"\blegal\b|\bparalegal\b|\battorney\b|\bcounsel\b",
        re.I)),
    ("clinical", re.compile(
        r"\bnurse\b|\bnursing\b|\bphysician\b|\bclinician\b|\btherapist\b|"
        r"\bpharmacist\b|\bveterinar(?:y|ian)\b|\bclinical\b",
        re.I)),
    ("education", re.compile(
        r"\bteacher\b|\bprofessor\b|\binstructor\b|\btutor\b|\bcurriculum\b",
        re.I)),
]


def _nontechnical_occupation_hits(ntitle: str) -> list[str]:
    return [name for name, pattern in _NONTECHNICAL_OCCUPATION_RULES
            if pattern.search(ntitle)]


def _is_role_bearing(term: str) -> bool:
    tn = normalize(term)
    return bool(_ROLE_NOUN_RE.search(tn)) or tn in _STANDALONE_ROLE_FAMILIES


def _title_has_role(ntitle: str) -> bool:
    return bool(_ROLE_NOUN_RE.search(ntitle)) or any(
        fam in ntitle for fam in _STANDALONE_ROLE_FAMILIES)


def assess_title(title: str | None, titles_cfg: dict | None) -> dict:
    """Canonical tri-state title/role assessment shared by production + corpus.

    Precedence: explicit exclude family (manager/director/…) -> generic
    non-technical-occupation lexicon -> not-included/broad-domain-without-role
    residual (-> review, `title.occupation_ambiguous`) -> leadership ambiguity
    (review) -> match. Only (i) an explicit profile exclude and (ii) a definite
    non-technical-occupation lexicon hit are hard `no_match` (Decision 3a); every
    other title that is neither a clean include match nor one of those two stays
    a `review` row so JD semantics are never lost to a silent hard drop. The
    broad-domain guard and the lexicon are GENERIC safeguards applied at
    assessment time; neither ever edits the (user-owned) profile.
    """
    titles_cfg = titles_cfg or {}
    ntitle = normalize(title)
    include = titles_cfg.get("include") or []
    exclude = titles_cfg.get("exclude") or []
    # Strip known non-level phrases before applying excludes, so their words don't
    # trip a rule — e.g. "Member of Technical Staff" must survive the "staff" exclude.
    ntitle_excl = ntitle
    for phrase in titles_cfg.get("exclude_neutralize") or []:
        ntitle_excl = ntitle_excl.replace(normalize(phrase), " ")

    level, level_signal = classify_level(title)

    excluded = [t for t in exclude if term_matches(t, ntitle_excl)]
    # Treat common wording variants as the profile's explicit "new grad"
    # exclusion rather than requiring brittle phrase duplication in every profile.
    if (any(normalize(term) == "new grad" for term in exclude)
            and _EARLY_CAREER_RE.search(ntitle_excl)
            and "new grad" not in [normalize(term) for term in excluded]):
        excluded.append("new grad")
    if excluded:
        return _title_result(
            "no_match", level, level_signal,
            rule_ids=[f"title.excluded.{normalize(t)}" for t in excluded])

    # Generic non-technical-occupation lexicon: hard no_match, but ONLY when the
    # title carries no engineering role noun — a co-occurring role noun (e.g.
    # "Customer Success Engineer", "Sales Engineer") makes the occupation
    # genuinely ambiguous rather than definite, so it falls through instead.
    if not _title_has_role(ntitle_excl):
        nontechnical = _nontechnical_occupation_hits(ntitle_excl)
        if nontechnical:
            return _title_result(
                "no_match", level, level_signal,
                rule_ids=[f"title.nontechnical_occupation.{h}" for h in nontechnical],
                evidence=[f"nontechnical_occupation:{','.join(nontechnical)}"])

    matched = [t for t in include if term_matches(t, ntitle)]
    residual_rule_id, broad = None, []
    if include and not matched:
        residual_rule_id = "title.not_included"
    elif include and matched and not any(_is_role_bearing(t) for t in matched):
        # Broad-domain guard: a title admitted ONLY by broad domain word(s) must
        # also carry an engineering role noun or a standalone role family.
        broad = sorted({
            normalize(t) for t in matched if normalize(t) in _BROAD_DOMAIN_TOKENS})
        if broad and not _title_has_role(ntitle):
            residual_rule_id = "title.broad_domain_without_role"

    if residual_rule_id:
        # Neither a clean include match nor a definite non-technical occupation:
        # a plausible/technical UNKNOWN occupation (e.g. "Member of Technical
        # Staff", "Systems Generalist"). Conservative -> review, not a silent
        # hard drop, so JD semantics still reach enrichment/adjudication.
        return _title_result(
            "review", level, level_signal,
            rule_ids=[residual_rule_id, "title.occupation_ambiguous"],
            evidence=[f"broad_domain:{','.join(broad)}"] if broad else [],
            review_reasons=["title_occupation_ambiguous"])

    # Leadership/manager-family ambiguity -> conservative review.
    if _AMBIGUOUS_LEADERSHIP_RE.search(ntitle_excl):
        return _title_result(
            "review", level, level_signal,
            rule_ids=["title.leadership_ambiguous"],
            review_reasons=["title_leadership_ambiguous"])

    rule_ids = ([f"title.included.{normalize(t)}" for t in matched]
                or ["title.included"])
    return _title_result(
        "match", level, level_signal, rule_ids=rule_ids,
        evidence=[level_signal] if level != "unknown" else [])


def _title_result(decision, level, level_signal, *, rule_ids,
                  evidence=None, review_reasons=None):
    confidence = "high" if level != "unknown" else "unknown"
    if decision == "review":
        confidence = "low"
    return {
        "domain": "title",
        "decision": decision,
        "result": decision,
        "accepted": decision != "no_match",
        "level": level,
        "level_signal": level_signal,
        "confidence": confidence,
        "rule_ids": list(rule_ids),
        "evidence": list(evidence or []),
        "review_reasons": list(review_reasons or []),
    }


def title_ok(posting: JobPosting, profile: dict) -> bool:
    """Keep a posting whose title is not a definite non-match.

    Records the canonical title assessment (and any leadership-ambiguity review
    reason) on the posting so the pipeline's review queue preserves ambiguous
    titles instead of silently dropping or accepting them.
    """
    assessment = assess_title(posting.title, profile.get("titles") or {})
    posting.filter_assessments["title"] = assessment
    if assessment["review_reasons"]:
        posting.review_reasons = list(dict.fromkeys(
            [*posting.review_reasons, *assessment["review_reasons"]]))
    return assessment["decision"] != "no_match"


def location_ok(posting: JobPosting, profile: dict) -> bool:
    loc_cfg = profile.get("location", {}) or {}
    assessment = assess_location(
        posting.location,
        {
            "metro": loc_cfg.get("preferred") or [],
            "allow_us_remote": loc_cfg.get("allow_remote", True),
            "us_only": loc_cfg.get("us_only", False),
            "require_match": loc_cfg.get("require_match", False),
        },
        title=posting.title,
        description=posting.description,
        workplace_hint=posting.remote,
        hint_trusted=not str(posting.source or "").startswith("jobspy:"),
    )
    posting.workplace = assessment.workplace
    posting.filter_assessments["location"] = assessment.to_dict()
    posting.review_reasons = list(dict.fromkeys(
        [*posting.review_reasons, *assessment.review_reasons]))
    # Reviewable ambiguity is preserved for the pipeline's review queue. Definite
    # non-matches alone are dropped here.
    return assessment.decision != "no_match"


def visa_ok(posting: JobPosting, profile: dict) -> bool:
    """Apply the profile's visa policy. Fills posting.visa_label/hits as a side effect."""
    text = posting.description or posting.title
    assessment = assess_sponsorship(text)
    label, hits = classify_visa(text)
    posting.visa_label = label
    posting.visa_hits = hits
    posting.sponsorship = assessment["verdict"]
    posting.filter_assessments["sponsorship"] = assessment
    visa = profile.get("visa", {}) or {}
    if not visa.get("needs_sponsorship"):
        return True
    policy = visa.get("policy", "exclude_negative")
    if assessment["decision"] == "review":
        if assessment["signal_present"] or policy == "require_positive":
            posting.review_reasons = list(dict.fromkeys([
                *posting.review_reasons,
                "sponsorship_requires_review",
            ]))
        return True
    if policy == "require_positive":
        return label == "yes"
    return label != "no"          # exclude_negative (default): keep yes + unclear


# --------------------------------------------------------------------------- #
# Posting-quality gate: unfilled ATS templates must never be accepted as a real
# posting. Generic, evidence-based placeholder detection — never a per-company
# alias — so a fictional template shape is exactly as detectable as a real one.
# --------------------------------------------------------------------------- #
_PLACEHOLDER_TITLE_RE = re.compile(
    r"<\s*job\s*title\s*>|\{\{\s*job\s*title\s*\}\}|\[\s*job\s*title\s*\]|"
    r"<\s*role\s*title\s*>|<\s*position\s*title\s*>",
    re.I,
)
# An unmistakable dollar-amount PLACEHOLDER token (never a real number): a
# repeated literal digit-placeholder character in a money position.
_PLACEHOLDER_COMP_RE = re.compile(
    r"\$\s*x{2,}(?:[.,]x{3})*\b|\$\s*#{2,}(?:[.,]#{3})*\b|\$\s*n{2,}(?:[.,]n{3})*\b",
    re.I,
)
_PLACEHOLDER_INSTRUCTION_RE = re.compile(
    r"\binsert (?:the )?(?:job )?title here\b|\breplace\s+(?:this|the)\s+"
    r"(?:text|placeholder)\s+with\b|\b\[insert[^\]]*\]|"
    r"\bdo not (?:remove|delete) this (?:line|section)\b|"
    r"\bplaceholder text\b|\btemplate instructions?\b",
    re.I,
)
_PLACEHOLDER_LOREM_RE = re.compile(r"\blorem ipsum\b", re.I)
_WS_COLLAPSE_RE = re.compile(r"\s+")


def _repeated_line_hits(description: str, *, min_len: int = 24,
                        min_repeats: int = 3) -> list[str]:
    """Non-trivial lines/sentences repeated verbatim >= `min_repeats` times.

    A generic signal for an unfilled ATS template that duplicates the SAME
    instructional/placeholder block across multiple JD sections — literal-
    duplicate-content detection, never a per-company alias.
    """
    lines = [_WS_COLLAPSE_RE.sub(" ", ln).strip()
              for ln in re.split(r"[\n.]", description or "")]
    counts = Counter(ln for ln in lines if len(ln) >= min_len)
    return sorted(ln for ln, n in counts.items() if n >= min_repeats)


def assess_posting_quality(title: str | None, description: str | None) -> dict:
    """Detect an unfilled ATS template so it is never accepted as a real match.

    Tri-state, mirroring the title gate: an unmistakable bracket/placeholder
    TITLE token is STRONG evidence and a hard `no_match`. A repeated block, bare
    compensation placeholder (``$XXX,XXX``), or generic instructional phrase is
    weaker and goes to `review`: legitimate boards sometimes repeat legal,
    benefit, or boilerplate sentences, so repetition alone must not hard-reject.
    """
    blob = f"{title or ''}\n{description or ''}"
    strong: list[str] = []
    weak: list[str] = []
    if _PLACEHOLDER_TITLE_RE.search(blob):
        strong.append("placeholder_title")
    if _PLACEHOLDER_LOREM_RE.search(blob):
        strong.append("placeholder_lorem_ipsum")
    if _repeated_line_hits(description or ""):
        weak.append("repeated_template_block")
    if _PLACEHOLDER_COMP_RE.search(blob):
        weak.append("placeholder_compensation")
    if _PLACEHOLDER_INSTRUCTION_RE.search(blob):
        weak.append("placeholder_instructions")

    if strong:
        decision = "no_match"
    elif weak:
        decision = "review"
    else:
        decision = "match"
    hits = strong + weak
    return {
        "domain": "quality",
        "decision": decision,
        "result": decision,
        "accepted": decision != "no_match",
        "confidence": "high" if strong else ("low" if weak else "unknown"),
        "rule_ids": [f"quality.{h}" for h in hits],
        "evidence": list(hits),
        "review_reasons": (["posting_template_placeholder"] if decision == "review"
                           else []),
    }


def posting_quality_ok(posting: JobPosting) -> bool:
    """Record the quality assessment and drop only a definite unfilled template."""
    assessment = assess_posting_quality(posting.title, posting.description)
    posting.filter_assessments["quality"] = assessment
    if assessment["review_reasons"]:
        posting.review_reasons = list(dict.fromkeys(
            [*posting.review_reasons, *assessment["review_reasons"]]))
    return assessment["decision"] != "no_match"


def date_ok(posting: JobPosting, max_age_days: float | None) -> bool:
    if max_age_days is None:
        return True
    if posting.age_days is None:      # unknown date -> keep, flag in reasons
        return True
    return posting.age_days <= max_age_days


def parse_min_required_years(text: str | None) -> int | float | None:
    """Return only a high-confidence general minimum YOE.

    Preferred or tool-specific/contextual YOE may still be shown in metadata, but
    it is not safe to use as a hard search filter.
    """
    details = extract_required_yoe_details(text)
    return details.get("min") if details.get("confidence") == "high" else None


def experience_ok(posting: JobPosting, profile: dict) -> bool:
    """Drop postings whose stated minimum YOE exceeds profile max_years_experience.

    Uses the shared ``assess_required_yoe`` so the hard filter, the score penalty,
    and the variant corpus all agree on which requirements are decisive.
    """
    cap = profile.get("max_years_experience")
    if cap is None:
        return True
    blob = "\n".join(x for x in (posting.title, posting.description) if x)
    return assess_required_yoe(blob, cap=int(cap))["decision"] != "no_match"


# --------------------------------------------------------------------------- #
# AI-native / AI-transitioning company signal
# --------------------------------------------------------------------------- #
def ai_company_hits(posting: JobPosting, profile: dict) -> list[str]:
    """AI-native/AI-transitioning signals found in the JD (title + description).

    A JD-text heuristic that works on EVERY source (company boards + Indeed/
    LinkedIn hits), unlike the registry tag which only covers curated boards.
    Signals come from `profile["ai_company"]["signals"]`.
    """
    cfg = profile.get("ai_company", {}) or {}
    signals = cfg.get("signals") or []
    if not signals:
        return []
    blob = normalize((posting.title or "") + " " + (posting.description or ""))
    return [s for s in signals if term_matches(s, blob)]


def ai_company_ok(posting: JobPosting, profile: dict,
                  is_ai_native_company: bool = False) -> bool:
    """Hard-filter to AI-native/AI-transitioning employers when configured.

    Only active when `ai_company.require` is truthy (set by `--ai-native-only` or
    the profile). A posting passes if its company is a registry AI-native employer
    OR its JD carries at least one AI-company signal. Default (soft) mode keeps
    everything and lets `score_posting` apply the boost instead.
    """
    cfg = profile.get("ai_company", {}) or {}
    if not cfg.get("require"):
        return True
    return is_ai_native_company or bool(ai_company_hits(posting, profile))


# --------------------------------------------------------------------------- #
# Level / experience fit
# --------------------------------------------------------------------------- #
# Google-equivalent numeric bands per normalized seniority word. Mirrors
# job_metadata.GENERIC_GOOGLE_EQUIVALENTS so the level-fit penalty speaks the
# same scale as the discovery table's "Level (Google eq.)" column.
_LEVEL_BANDS = {
    "intern": (2.0, 2.8), "entry": (3.0, 3.8), "mid": (4.0, 4.8),
    "senior": (5.0, 5.8), "staff": (6.0, 6.8), "senior_staff": (7.0, 7.8),
    "principal": (8.0, 8.8), "distinguished": (9.0, 10.0),
}


def target_level_band(profile: dict) -> tuple[float, float] | None:
    """Desired Google-equivalent level range spanning every `seniority.target` word.

    Returns ``(low, high)`` or ``None`` when no recognized target is configured
    (so the caller skips the level-fit penalty entirely). ``senior staff`` and
    ``senior_staff`` are both accepted.
    """
    target = (profile.get("seniority", {}) or {}).get("target") or []
    bands = [_LEVEL_BANDS[key] for t in target
             if (key := normalize(t).replace(" ", "_")) in _LEVEL_BANDS]
    if not bands:
        return None
    return min(b[0] for b in bands), max(b[1] for b in bands)


def level_fit_delta(posting: JobPosting, band: tuple[float, float] | None,
                    weight: float) -> tuple[float, str | None]:
    """Non-positive score adjustment for how far a posting sits outside `band`.

    Overlapping (in-band) or unknown levels are not penalized. Distance is in
    Google-ladder steps (~1.0 per level), scaled by `weight`.
    """
    if band is None or weight <= 0:
        return 0.0, None
    level = posting.job_level or {}
    low, high = level.get("min"), level.get("max")
    if low is None and high is None:
        return 0.0, None
    lo = float(low if low is not None else high)
    hi = float(high if high is not None else low)
    b_lo, b_hi = band
    if hi < b_lo:                       # under-leveled (e.g. entry role for a senior search)
        dist, kind = b_lo - hi, "under-leveled"
    elif lo > b_hi:                     # over-leveled (e.g. staff+ role for a senior search)
        dist, kind = lo - b_hi, "over-leveled"
    else:
        return 0.0, None                # overlaps the target band -> good fit
    penalty = round(dist * weight, 1)
    return -penalty, f"{kind} (-{penalty:g})"


def score_posting(posting: JobPosting, profile: dict,
                  sponsor_index: dict | None = None,
                  is_ai_native_company: bool = False) -> None:
    """Compute posting.score and posting.reasons in place.

    `is_ai_native_company` is precomputed by the caller (search_jobs) from the
    registry AI-native tag set, so scoring.py stays free of a registry import.
    """
    kw = profile.get("keywords", {}) or {}
    ntitle = normalize(posting.title)
    ndesc = normalize(posting.description)
    score = 0.0
    reasons: list[str] = []

    strong = [k for k in (kw.get("strong") or []) if term_matches(k, ntitle + " " + ndesc)]
    good = [k for k in (kw.get("good") or []) if term_matches(k, ndesc)]
    neg = [k for k in (kw.get("negative") or []) if term_matches(k, ntitle + " " + ndesc)]

    for k in strong:
        bump = 8 if term_matches(k, ntitle) else 4
        score += bump
    for k in good:
        score += 1.5
    for k in neg:
        score -= 4
    if strong:
        reasons.append("strong: " + ", ".join(strong[:6]))
    if good:
        reasons.append("skills: " + ", ".join(good[:6]))
    if neg:
        reasons.append("mismatch: " + ", ".join(neg[:6]))

    # Seniority hint
    sen_cfg = profile.get("seniority", {}) or {}
    target = [s.lower() for s in sen_cfg.get("target", [])]
    if "staff" in target and term_matches("staff", ntitle):
        score += 4; reasons.append("staff-level title")
    elif "senior" in target and (term_matches("senior", ntitle) or term_matches("sr", ntitle)):
        score += 3; reasons.append("senior-level title")

    # Level fit: demote roles whose parsed Google-equivalent level sits outside the
    # target seniority band, so a "senior" search isn't topped by staff+/entry roles.
    # Reuses the level parsed by enrich_posting_metadata; `fit_weight: 0` disables it.
    band = target_level_band(profile)
    fit_delta, fit_note = level_fit_delta(
        posting, band, float(sen_cfg.get("fit_weight", 6.0)))
    if fit_delta:
        score += fit_delta
        reasons.append("level " + fit_note)

    # Decision 3c (conflict half): an explicit JD-body level phrase that
    # materially exceeds the target band is flagged for review — the Snowflake
    # case (a bare/under-signaled title whose JD body actually calls for a
    # Staff+ engineer) — WITHOUT changing occupation or the title-derived
    # job_level. This is independent of `enrich_posting_metadata`'s own
    # silent-title-and-YOE fill, so it also fires when the title already
    # carries its OWN (lower) level word.
    if band is not None:
        jd_level, jd_signal = classify_level_from_jd_body(posting.description)
        jd_band = _LEVEL_BANDS.get(jd_level)
        if jd_band is not None and jd_band[0] > band[1]:
            posting.review_reasons = list(dict.fromkeys(
                [*posting.review_reasons, "jd_level_conflicts_title"]))
            reasons.append(f"jd body states {jd_level} level (review: {jd_signal!r})")

    # YOE fit (opt-in): demote roles asking materially more experience than the
    # candidate has. Active only when the profile states `years_experience`.
    cand_yoe = profile.get("years_experience")
    if cand_yoe is not None:
        required_yoe = posting.required_yoe or {}
        req_min = (required_yoe.get("min")
                   if required_yoe.get("confidence") == "high" else None)
        if req_min is not None and float(req_min) > float(cand_yoe):
            over = float(req_min) - float(cand_yoe)
            penalty = round(over * float(sen_cfg.get("yoe_fit_weight", 1.0)), 1)
            if penalty:
                score -= penalty
                reasons.append(f"yoe over-reach +{over:g}y (-{penalty:g})")

    # Visa
    if posting.visa_label == "yes":
        score += 15; reasons.append("visa: sponsorship stated (" + ", ".join(posting.visa_hits[:3]) + ")")
    elif posting.visa_label == "unclear":
        reasons.append("visa: not stated (verify)")
    tags = visa_tags(posting.description)
    if "h1b_transfer_friendly" in tags:
        score += 5; reasons.append("h1b transfer friendly")

    # AI-native / AI-transitioning company signal (boost; hard-filter is optional
    # and handled by ai_company_ok). Rewards "infra role AT an AI-native company".
    ai_cfg = profile.get("ai_company", {}) or {}
    if ai_cfg:
        hits = ai_company_hits(posting, profile)
        if hits:
            per = float(ai_cfg.get("boost_per_hit", 2))
            cap = float(ai_cfg.get("max_boost", 10))
            score += min(cap, per * len(hits))
            reasons.append("ai-signal: " + ", ".join(hits[:5]))
        if is_ai_native_company:
            score += float(ai_cfg.get("company_boost", 6))
            reasons.append("ai-native company")

    # Employer sponsorship history (optional DOL enrichment)
    if sponsor_index:
        key = _norm_company(posting.company)
        rec = sponsor_index.get(key)
        if rec:
            h1b = rec.get("h1b", 0); perm = rec.get("perm", 0)
            if h1b or perm:
                score += min(10, (h1b + perm * 2) / 20.0)
                reasons.append(f"DOL: {h1b} H-1B / {perm} PERM filings")

    # Location
    loc_assessment = posting.filter_assessments.get("location", {})
    if loc_assessment.get("category") == "metro":
        score += 5; reasons.append(f"location: {posting.location}")
    if (loc_assessment.get("category") == "us_remote"
            and loc_assessment.get("workplace") == "remote"):
        score += 3; reasons.append("remote")
    if loc_assessment.get("decision") == "review":
        reasons.append("location: manual review")

    # Recency (mild boost for very fresh)
    if posting.age_days is not None and posting.age_days <= 1:
        score += 3; reasons.append("posted <24h")

    posting.score = round(score, 1)
    posting.reasons = reasons


def _norm_company(name: str) -> str:
    n = normalize(name)
    for suffix in (" inc", " llc", " ltd", " corp", " corporation", " labs",
                   " technologies", " technology", " ai", " io", " the "):
        n = n.replace(suffix, " ")
    return " ".join(n.split())
