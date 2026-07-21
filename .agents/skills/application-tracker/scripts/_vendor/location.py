"""Classify a posting location string against the configured location policy.

The active job-search location policy (see ``config.location_policy``) decides
which postings are acceptable — a set of preferred-metro tokens plus a US-remote /
``us_only`` rule. Every application's ``meta.yaml`` records the posting ``location``
(top-level for a single role, per-entry under ``jobs:`` for a multi-role
application). This module turns those free-text location strings into one of a few
categories and a match/no-match verdict so that
``.agents/skills/application-tracker/scripts/status.py --check-locations`` and
``.agents/skills/resume-writer/scripts/check.py`` can flag drafts that do not
respect the location criteria.

This module is policy-injected and carries NO candidate-specific defaults: the
preferred-metro list is empty here and supplied at call time via ``policy`` (from
``config.location_policy``). It mirrors the location logic in
``.agents/skills/job-search/scripts/scoring.py`` (``location_ok``) but works from
the raw location string alone (there is no separate ``remote`` field here).

Categories:
    metro      -> match  (a preferred-metro office is listed)
    us_remote  -> match  (US / North-America remote or US-eligible, no fixed
                          non-preferred office required)
    other_us   -> NO match (on-site / hybrid in a non-preferred US city)
    foreign    -> NO match (non-US only)
    unknown    -> NO match (blank / unrecognized — review manually)
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass

# Preferred-metro tokens. This module ships with NO built-in metros — the real
# list is candidate-specific and injected at call time via ``config.location_policy``
# (``metro`` key). A listed preferred-metro token in a posting location -> match.
DEFAULT_METRO: tuple[str, ...] = ()

# Generic workplace markers are NEVER metro tokens. A profile's preferred-metro
# list may legitimately include a workplace word such as "remote" (meaning "I am
# happy with US-remote"), but if such a word were treated as a preferred-metro
# token it would make ANY location containing that word — e.g. "Canada (Remote)"
# — match as a preferred metro and leak a foreign posting into a US-only
# shortlist. Workplace eligibility is decided by the us_remote / workplace path
# (``allow_us_remote`` + full-evidence workplace assessment), not by the metro
# list, so these words are stripped from the injected metro tokens.
_GENERIC_WORKPLACE_MARKERS = frozenset({
    "remote", "remotely", "remote-first", "remote first", "fully remote",
    "hybrid", "onsite", "on-site", "on site", "in-office", "in office",
    "in-person", "in person", "distributed", "wfh", "work from home",
    "work remotely", "anywhere", "worldwide", "global", "flexible",
})

# Remote signals. "hybrid" / "in-office" / "on-site" are deliberately NOT here —
# a hybrid role in a specific non-preferred city still requires being in that city.
# "distributed" is deliberately NOT a remote signal: a bare "Distributed" location
# tag is a company-structure descriptor, not a work-location grant, and it rode a
# US-remote match onto globally-pinned roles whose title/JD names a foreign city
# (e.g. a "Distributed" tag on a Melbourne-only role). Such a tag is unverified —
# it classifies as "unknown" (review manually) rather than a us_remote match.
REMOTE_TOKENS = (
    "remote", "work from home", "wfh", "fully remote", "anywhere",
    "worldwide", "global",
)

# Broad regions that imply remote across North America (include the US).
US_REMOTE_REGIONS = (
    "united states", "usa", "u.s.", "u.s.a", "us remote", "remote us",
    "remote - us", "remote, us", "remote (us", "north america", "namer",
    "americas",
)

# Non-US-only regions -> foreign.
FOREIGN_REGIONS = ("emea", "apac", "latam", "europe")

_US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
}
_US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
# Non-preferred US hub cities -> a specific US office (on-site/hybrid) when not remote.
_US_HUBS = {
    "san francisco", "bay area", "silicon valley", "mountain view", "palo alto",
    "menlo park", "sunnyvale", "santa clara", "san jose", "cupertino", "oakland",
    "redwood city", "san mateo", "foster city", "new york", "nyc", "brooklyn",
    "boston", "cambridge", "austin", "dallas", "houston", "denver", "boulder",
    "chicago", "atlanta", "miami", "los angeles", "san diego", "portland",
    "phoenix", "raleigh", "durham", "pittsburgh", "philadelphia", "minneapolis",
    "nashville", "salt lake", "washington, d", "livingston", "richardson",
    "sandy", "arlington", "seattle", "bellevue", "redmond", "kirkland",
    "tacoma", "everett",
}
_FOREIGN_TOKENS = (
    "united kingdom", " uk", "uk)", "u.k", "london", "england", "scotland",
    "ireland", "dublin", "germany", "berlin", "munich", "hamburg", "cologne",
    "frankfurt", "karlsruhe", "nuremberg", "bremen", "stuttgart", "canada",
    "toronto", "vancouver", "montreal", "france", "paris", "india",
    "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "chennai",
    "singapore", "australia", "sydney", "melbourne", "canberra",
    "netherlands", "amsterdam",
    "spain", "madrid", "barcelona", "portugal", "lisbon", "poland", "warsaw",
    "italy", "italian", "milan", "rome", "turin", "bologna",
    "brazil", "sao paulo", "mexico", "japan", "tokyo", "korea", "china",
    "israel", "tel aviv", "zurich", "geneva", "sweden", "stockholm", "denmark",
    "copenhagen", "romania", "bucharest", "philippines", "manila", "argentina",
    "colombia", "nigeria", "kenya", "new zealand", "vietnam", "indonesia",
    "malaysia", "dubai", "abu dhabi", "nordic",
    # High-confidence foreign COUNTRY names surfaced by the live-snapshot audit.
    # Countries (not bare city names) are chosen deliberately: they are
    # unambiguous foreign scope and avoid the US-city name collisions that make a
    # city list brittle (e.g. Vienna VA, Athens GA, Ontario CA, Peru IL). Cities
    # are added only when they are not also US place names.
    "czech republic", "czechia", "prague", "serbia", "finland", "helsinki",
    "austria", "estonia", "tallinn", "latvia", "lithuania", "vilnius",
    "qatar", "doha", "saudi arabia", "riyadh", "greece", "iceland", "reykjavik",
    "norway", "oslo", "hungary", "budapest", "hong kong", "chile", "costa rica",
    "taiwan", "taipei", "thailand", "bangkok", "luxembourg", "slovakia",
    "slovenia", "croatia", "bulgaria", "ukraine", "turkey", "egypt", "cairo",
    "south africa", "morocco", "pakistan", "karachi", "bangladesh", "sri lanka",
    "uruguay", "ecuador", "guatemala", "panama", "seoul", "jakarta", "gurugram",
    "gurgaon", "kuwait", "bahrain", "qatar",
    # Canadian provinces (Canada itself is above; province-only strings are common
    # and unambiguous — none collide with a US state name).
    "british columbia", "alberta", "saskatchewan", "manitoba", "quebec",
)

# Short foreign abbreviations that need word-boundary matching (a bare "uk"/"eu"
# substring would otherwise ride inside unrelated words, and a leading-space token
# misses "UK remote" / "UK, ...").
_FOREIGN_ABBR_RE = re.compile(r"\b(uk|u\.k\.?|eu)\b")

MATCH_CATEGORIES = ("metro", "us_remote")

_WORKPLACE_VALUES = {"remote", "hybrid", "onsite", "unknown"}
_REMOTE_JD_RULES = (
    ("jd_fully_remote", re.compile(r"\bfully\s+remote\b", re.I)),
    ("jd_remote_role", re.compile(
        r"\bremote(?:[- ]first)?\s+(?:role|position|job|opportunity)\b", re.I)),
    ("jd_work_remotely", re.compile(r"\bwork(?:ing)?\s+remotely\b", re.I)),
    ("jd_remote_scope", re.compile(
        r"\bremote(?:ly)?\s+(?:within|in|from|across)\s+(?:the\s+)?"
        r"(?:united states|u\.?s\.?a?|north america|americas)\b", re.I)),
    ("jd_office_or_remote", re.compile(
        r"\b(?:hub|office|location)s?\b.{0,120}\bor\s+remotely\b|"
        r"\bor\s+remotely\b.{0,120}\b"
        r"(?:united states|u\.?s\.?a?|north america|americas)\b", re.I | re.S)),
    ("jd_role_can_be_remote", re.compile(
        r"\b(?:role|position|job)\b.{0,180}\b(?:can|may|could)\b.{0,100}"
        r"\b(?:held|based|performed|worked)?\b.{0,80}\bremot(?:e|ely)\b",
        re.I | re.S)),
)
_HYBRID_JD_RULES = (
    ("jd_hybrid_role", re.compile(
        r"\bhybrid\s+(?:role|position|job|schedule|work)\b|"
        r"\b(?:role|position|job)\b.{0,100}\bhybrid\b", re.I | re.S)),
    ("jd_office_days", re.compile(
        r"\b(?:in[- ]office|onsite|on[- ]site)\b.{0,80}"
        r"\b(?:day|days|time)s?\s+(?:per|a|each)\s+week\b", re.I | re.S)),
)
_ONSITE_JD_RULES = (
    ("jd_not_remote", re.compile(
        r"\b(?:not|isn'?t|cannot|can'?t)\s+(?:a\s+)?remote\b|"
        r"\bremote\s+(?:work|arrangement)s?\s+(?:is|are)\s+not\s+available\b",
        re.I)),
    ("jd_onsite_required", re.compile(
        r"\b(?:onsite|on[- ]site|in[- ]office|in the office)\b.{0,60}"
        r"\b(?:required|requirement|must|five days|5 days)\b|"
        r"\bmust\b.{0,50}\b(?:work|be)\b.{0,40}\b(?:onsite|on[- ]site|"
        r"in[- ]office|in the office)\b", re.I | re.S)),
)

# A negated in-office/onsite obligation ("there is no minimum in-office
# requirement", "no in-office requirement", "not required to be onsite") is the
# OPPOSITE of an onsite mandate and must not fire ``jd_onsite_required``. Checked
# against the short window immediately BEFORE the onsite match.
_ONSITE_NEGATION_RE = re.compile(
    r"(?:\bno\b|\bnot\b|\bno\s+minimum\b|\bwithout\b|\bisn'?t\b|\baren'?t\b|"
    r"\bnever\b|\bzero\b)\s*$", re.I)

# Hybrid framed as an OPTION/opportunity/CHOICE rather than a mandate. When the JD
# also grants remote work, an optional-hybrid perk — or an explicit
# "remote or hybrid" choice, where the candidate may simply pick remote — is not a
# competing obligation, so it must not manufacture a remote/hybrid conflict;
# remote is the baseline. A truly required hybrid schedule (e.g. "hybrid role with
# three office days each week") does NOT match this and remains a genuine conflict
# when it opposes a remote grant.
_OPTIONAL_HYBRID_RE = re.compile(
    r"\bremote\s+or\s+hybrid\b|\bhybrid\s+or\s+remote\b|"
    r"\b(?:option(?:al|s)?|opportunit(?:y|ies)|choice|choose|flexib\w*|"
    r"if\s+you\s+(?:prefer|want|choose|like)|prefer\s+to|"
    r"can\s+(?:also\s+)?(?:work|choose|opt)|welcome\s+to)\b[^.\n]{0,40}\bhybrid\b"
    r"|\bhybrid\b[^.\n]{0,40}\b(?:option(?:al)?|available|encouraged|welcome|"
    r"if\s+you\s+(?:prefer|want|choose)|is\s+not\s+required|not\s+required)\b",
    re.I,
)


@dataclass(frozen=True)
class LocationAssessment:
    """Explainable posting-level location/workplace policy assessment.

    ``decision`` is deliberately three-valued. ``review`` means the available
    fields are silent or contradictory, so a caller must preserve the posting for
    manual review rather than silently treating uncertainty as a match or reject.
    """

    category: str
    workplace: str
    decision: str
    confidence: str
    evidence: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return self.decision == "match"

    @property
    def result(self) -> str:
        return self.decision

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.evidence, *self.review_reasons)))

    @property
    def reason(self) -> str:
        if self.review_reasons:
            return "Manual review: " + ", ".join(self.review_reasons)
        return f"{self.category} / {self.workplace}: {self.decision}"

    @property
    def structural_signature(self) -> str:
        material = "|".join([
            "location",
            self.category,
            self.workplace,
            self.decision,
            ",".join(sorted(self.rule_ids)),
        ])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        data["review_reasons"] = list(self.review_reasons)
        data["matched"] = self.matched
        data["result"] = self.result
        data["rule_ids"] = list(self.rule_ids)
        data["reason"] = self.reason
        data["structural_signature"] = self.structural_signature
        return data


def _policy_lists(policy: dict | None):
    """Resolve an injectable policy to the values classify_location needs.

    Returns ``(metro, remote_tokens, us_remote_regions, allow_us_remote,
    us_only)``. A ``None`` policy — or any absent/empty list key — falls back to
    this module's default constants (an EMPTY preferred-metro list, so no metro
    matches unless the policy supplies one). Provided token lists are lowercased to
    match the normalized location text.
    """
    policy = policy or {}

    def _tokens(key, default):
        val = policy.get(key)
        if not val:
            return default
        return tuple(str(v).lower() for v in val)

    def _metro(default):
        # Strip generic workplace markers so a preferred word such as "remote"
        # can never turn a foreign posting into a preferred-metro match.
        val = policy.get("metro")
        if not val:
            return default
        return tuple(
            tok for v in val
            if (tok := str(v).lower().strip())
            and tok not in _GENERIC_WORKPLACE_MARKERS
        )

    return (
        _metro(DEFAULT_METRO),
        _tokens("remote_tokens", REMOTE_TOKENS),
        _tokens("us_remote_regions", US_REMOTE_REGIONS),
        bool(policy.get("allow_us_remote", True)),
        bool(policy.get("us_only", True)),
    )


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    t = text.lower()
    t = t.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    # Fold accents to their base ASCII letter (NFKD then drop combining marks) so a
    # foreign city written with diacritics — "São Paulo", "Zürich", "Reykjavík",
    # "Mäntsälä" — normalizes to its plain-ASCII token and still matches the
    # foreign-scope lists below instead of being shredded into unknown fragments.
    t = "".join(
        ch for ch in unicodedata.normalize("NFKD", t)
        if not unicodedata.combining(ch)
    )
    t = re.sub(r"[^a-z0-9\-+/.,#& ]+", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _has(tokens, nloc: str) -> bool:
    return any(tok in nloc for tok in tokens)


def _has_us_state(nloc: str) -> bool:
    return any(re.search(rf"\b{re.escape(s)}\b", nloc) for s in _US_STATE_NAMES)


def _has_state_abbr(original: str) -> bool:
    return any(ab in _US_STATE_ABBR
               for ab in re.findall(r"\b[A-Z]{2}\b", original or ""))


def _rule_hits(text: str, rules) -> list[str]:
    return [rule_id for rule_id, pattern in rules if pattern.search(text or "")]


def _onsite_rule_hits(text: str) -> list[str]:
    """Onsite JD rules with a negation guard on ``jd_onsite_required``.

    An in-office/onsite phrase that is immediately negated ("no minimum in-office
    requirement") states the ABSENCE of an onsite obligation and must not be
    recorded as ``jd_onsite_required``; only an un-negated occurrence counts.
    """
    text = text or ""
    hits: list[str] = []
    for rule_id, pattern in _ONSITE_JD_RULES:
        matches = list(pattern.finditer(text))
        if rule_id == "jd_onsite_required":
            matches = [
                m for m in matches
                if not _ONSITE_NEGATION_RE.search(text[max(0, m.start() - 34):m.start()])
            ]
        if matches:
            hits.append(rule_id)
    return hits


def _workplace_assessment(
    location: str,
    description: str,
    workplace_hint: str,
    hint_trusted: bool,
) -> tuple[str, str, list[str], list[str]]:
    """Return workplace, confidence, evidence IDs, and review reasons."""
    nloc = _normalize(location)
    hint = _normalize(workplace_hint)
    hint = hint if hint in _WORKPLACE_VALUES else "unknown"

    loc_hybrid = "hybrid" in nloc
    loc_remote = _has(REMOTE_TOKENS, nloc)
    remote_hits = _rule_hits(description, _REMOTE_JD_RULES)
    hybrid_hits = _rule_hits(description, _HYBRID_JD_RULES)
    onsite_hits = _onsite_rule_hits(description)
    # An OPTIONAL hybrid perk alongside a remote grant is not a competing
    # obligation, so drop the hybrid signal before evidence and conflict checks —
    # remote stays the baseline. A required hybrid schedule ("three office days
    # each week") does not match the optional pattern and is preserved as a
    # genuine conflict.
    if (_OPTIONAL_HYBRID_RE.search(description or "")
            and (remote_hits or loc_remote)):
        hybrid_hits = []
        loc_hybrid = False
    evidence: list[str] = []
    review: list[str] = []

    if loc_hybrid:
        evidence.append("location_hybrid")
    if loc_remote:
        evidence.append("location_remote")
    evidence.extend(remote_hits)
    evidence.extend(hybrid_hits)
    evidence.extend(onsite_hits)
    if hint != "unknown":
        evidence.append(f"ats_hint_{hint}")

    # Explicit role-level contradictions require review. A raw ATS/scraper hint is
    # never allowed to overrule JD text because those flags are known to be noisy.
    if onsite_hits and (remote_hits or loc_remote or hint == "remote"):
        review.append("remote_onsite_conflict")
    if hybrid_hits and remote_hits and "jd_office_or_remote" not in remote_hits:
        review.append("remote_hybrid_conflict")
    if loc_hybrid and remote_hits and "jd_office_or_remote" not in remote_hits:
        review.append("location_hybrid_jd_remote_conflict")
    if review:
        return "unknown", "low", evidence, review

    if onsite_hits:
        return "onsite", "high", evidence, review
    if "jd_office_or_remote" in remote_hits or remote_hits:
        return "remote", "high", evidence, review
    if hybrid_hits or loc_hybrid:
        return "hybrid", "high", evidence, review
    if loc_remote:
        return "remote", "high", evidence, review

    # A structured hint with no corroborating text remains reviewable rather than
    # ground truth. Explicit onsite hints are safe enough to classify, while a
    # remote/hybrid hint could be the systemically noisy market-scraper flag.
    if hint == "onsite":
        return "onsite", "medium", evidence, review
    if hint in {"remote", "hybrid"} and hint_trusted:
        return hint, "medium", evidence, review
    if hint in {"remote", "hybrid"}:
        review.append("uncorroborated_ats_workplace_hint")
        return hint, "low", evidence, review
    if location:
        return "onsite", "medium", evidence, review
    return "unknown", "unknown", evidence, review


def assess_location(
    location: str | None,
    policy: dict | None = None,
    *,
    title: str | None = "",
    description: str | None = "",
    workplace_hint: str | None = "",
    hint_trusted: bool = True,
) -> LocationAssessment:
    """Assess one posting using all available location/workplace evidence.

    The raw location remains the geographic source. The title is used only to
    catch country/city scope hidden by boards behind generic tags such as
    ``Distributed``. Full JD text supplies role-level workplace alternatives such
    as "one of our US hubs or remotely in the United States".
    """
    original = location or ""
    nloc = _normalize(original)
    ntitle = _normalize(title)
    context = " ".join(x for x in (nloc, ntitle) if x)
    description = description or ""
    (metro, _remote_tokens, us_remote_regions,
     allow_us_remote, us_only) = _policy_lists(policy)
    policy = policy or {}
    require_match = bool(policy.get("require_match", True))

    workplace, confidence, evidence, review = _workplace_assessment(
        original, description, workplace_hint or "", hint_trusted)
    foreign = (_has(_FOREIGN_TOKENS, context) or _has(FOREIGN_REGIONS, context)
               or _FOREIGN_ABBR_RE.search(context) is not None)
    us = (_has(us_remote_regions, context) or _has_us_state(nloc)
          or _has(_US_HUBS, nloc) or _has_state_abbr(original)
          or re.search(r"\bus\b", context) is not None)
    preferred = _has(metro, nloc)
    has_specific_us_office = (_has(_US_HUBS, nloc) or _has_us_state(nloc)
                              or _has_state_abbr(original))

    if preferred:
        category = "metro"
        evidence.append("preferred_metro")
    elif foreign and us:
        category = "unknown"
        review.append("mixed_us_foreign_scope")
    elif foreign:
        category = "foreign"
        evidence.append("foreign_scope")
    elif workplace == "remote":
        category = "us_remote"
        evidence.append("remote_eligible")
    elif has_specific_us_office:
        category = "other_us"
        evidence.append("specific_us_office")
    elif us:
        # A country/region-only answer means US eligibility even if the ATS omitted
        # a workplace mode; preserve the historical policy behavior.
        category = "us_remote" if allow_us_remote else "other_us"
        evidence.append("broad_us_scope")
    else:
        category = "unknown"

    # Definitively foreign-only geography dominates any internal workplace
    # remote/hybrid/onsite tension: the role is out of a US-only search either
    # way, so it is a decisive foreign no_match, not a workplace-conflict review.
    # (Mixed US/foreign scope is category "unknown", not "foreign", so it is not
    # swallowed here and still reaches review below.)
    if category == "foreign":
        review = []
    if review:
        decision = "review"
        confidence = "low"
    elif not require_match and not us_only:
        decision = "match"
    elif category == "metro":
        decision = "match"
    elif category == "us_remote" and allow_us_remote:
        decision = "match"
    elif category in {"foreign", "other_us"}:
        decision = "no_match"
    else:
        decision = "review"
        review.append("unclassified_location")
        confidence = "unknown"

    return LocationAssessment(
        category=category,
        workplace=workplace,
        decision=decision,
        confidence=confidence,
        evidence=tuple(dict.fromkeys(evidence)),
        review_reasons=tuple(dict.fromkeys(review)),
    )


def classify_location(loc: str | None, policy: dict | None = None) -> str:
    """Return the location category for a raw posting-location string.

    ``policy`` supplies the location rule (its ``metro`` / ``remote_tokens`` /
    ``us_remote_regions`` token lists and the ``allow_us_remote`` / ``us_only``
    booleans — see ``_policy_lists``). With ``policy=None`` only the module defaults
    apply, which include NO preferred metros (so nothing classifies as ``metro``);
    callers that enforce a metro rule must pass ``config.location_policy()``.
    """
    return assess_location(loc, policy).category


def is_match(category: str) -> bool:
    return category in MATCH_CATEGORIES


def classify_locations(locs, policy: dict | None = None) -> tuple[str, bool]:
    """Classify a list of location strings for one application.

    Returns (best_category, matched). An application matches when ANY of its
    postings is a preferred-metro or US-remote. ``policy`` is forwarded to
    ``classify_location``; ``None`` keeps the default rule (no preferred metros).
    """
    cats = [classify_location(x, policy)
            for x in (locs or []) if str(x or "").strip()]
    if not cats:
        return "unknown", False
    for want in ("metro", "us_remote"):
        if want in cats:
            return want, True
    for cat in ("other_us", "foreign"):
        if cat in cats:
            return cat, False
    return "unknown", False


# Location line as written at the top of a JD file:
#   Location: ...   |   **Location:** ...   |   - Location: ...
#   Primary location: ...   |   Work Location: ...
# Requires a colon right after the word "location" so plural "locations:" lines
# (e.g. "Additional locations: ...") do not match.
_JD_LOC_RE = re.compile(
    r"^\s*[-*]*\s*\**\s*(?:primary\s+|work\s+)?locations?\**\s*:\s*(.+?)\s*$",
    re.I,
)


# Segments that ride along on the same "Location:" line but are not the location
# (e.g. "**Location**: SF | **Compensation**: $...").
_NON_LOCATION_SEG = re.compile(
    r"(compensation|salary|equity|posted|department|employment type|job type|"
    r"\$\d)", re.I,
)


def _clean_location_value(val: str) -> str:
    val = val.strip().strip("*").strip()
    # Drop "| ..." trailing segments that describe comp/posting rather than place.
    if "|" in val:
        segs = [s.strip().strip("*").strip() for s in val.split("|")]
        kept = [s for s in segs if s and not _NON_LOCATION_SEG.search(s)]
        val = " / ".join(kept) if kept else val
    return val.strip()


def extract_jd_locations(text: str) -> list[str]:
    """Pull every 'Location:' value from a JD file's text (in order, de-duped)."""
    out: list[str] = []
    for line in (text or "").splitlines():
        m = _JD_LOC_RE.match(line)
        if not m:
            continue
        val = _clean_location_value(m.group(1))
        # Skip placeholder rows like "*Job Posting Only: USA1"
        if val and val not in out:
            out.append(val)
    return out


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        cat = classify_location(arg)
        print(f"{'MATCH ' if is_match(cat) else 'NO    '} {cat:<13} {arg}")
