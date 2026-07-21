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

import re

# Preferred-metro tokens. This module ships with NO built-in metros — the real
# list is candidate-specific and injected at call time via ``config.location_policy``
# (``metro`` key). A listed preferred-metro token in a posting location -> match.
DEFAULT_METRO: tuple[str, ...] = ()

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
    "sandy", "arlington",
}
_FOREIGN_TOKENS = (
    "united kingdom", " uk", "uk)", "u.k", "london", "england", "scotland",
    "ireland", "dublin", "germany", "berlin", "munich", "hamburg", "cologne",
    "frankfurt", "karlsruhe", "nuremberg", "bremen", "stuttgart", "canada",
    "toronto", "vancouver", "montreal", "france", "paris", "india",
    "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "chennai",
    "singapore", "australia", "sydney", "melbourne", "netherlands", "amsterdam",
    "spain", "madrid", "barcelona", "portugal", "lisbon", "poland", "warsaw",
    "brazil", "sao paulo", "mexico", "japan", "tokyo", "korea", "china",
    "israel", "tel aviv", "zurich", "geneva", "sweden", "stockholm", "denmark",
    "copenhagen", "romania", "bucharest", "philippines", "manila", "argentina",
    "colombia", "nigeria", "kenya", "new zealand", "vietnam", "indonesia",
    "malaysia", "dubai", "abu dhabi",
)

# Short foreign abbreviations that need word-boundary matching (a bare "uk"/"eu"
# substring would otherwise ride inside unrelated words, and a leading-space token
# misses "UK remote" / "UK, ...").
_FOREIGN_ABBR_RE = re.compile(r"\b(uk|u\.k\.?|eu)\b")

MATCH_CATEGORIES = ("metro", "us_remote")


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

    return (
        _tokens("metro", DEFAULT_METRO),
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


def classify_location(loc: str | None, policy: dict | None = None) -> str:
    """Return the location category for a raw posting-location string.

    ``policy`` supplies the location rule (its ``metro`` / ``remote_tokens`` /
    ``us_remote_regions`` token lists and the ``allow_us_remote`` / ``us_only``
    booleans — see ``_policy_lists``). With ``policy=None`` only the module defaults
    apply, which include NO preferred metros (so nothing classifies as ``metro``);
    callers that enforce a metro rule must pass ``config.location_policy()``.
    """
    original = loc or ""
    nloc = _normalize(original)
    if not nloc:
        return "unknown"

    (metro, remote_tokens, us_remote_regions,
     allow_us_remote, us_only) = _policy_lists(policy)

    # A US-eligible-but-not-preferred result is reported as us_remote only when the
    # policy allows US-remote; otherwise it is a non-matching US office.
    # (Default allow_us_remote=True -> always "us_remote".)
    us_remote_cat = "us_remote" if allow_us_remote else "other_us"

    # 1) Preferred metro wins — a listed preferred-metro office satisfies the rule
    #    even when other cities are also listed (the candidate can pick that office).
    if _has(metro, nloc):
        return "metro"

    foreign = (_has(_FOREIGN_TOKENS, nloc) or _has(FOREIGN_REGIONS, nloc)
               or _FOREIGN_ABBR_RE.search(nloc) is not None)
    # `us` = the posting is US-scoped (country, region, state, hub city, or bare US).
    us = (_has(us_remote_regions, nloc) or _has_us_state(nloc)
          or _has(_US_HUBS, nloc) or _has_state_abbr(original)
          or re.search(r"\bus\b", nloc) is not None)
    # `remote` = a genuine remote signal only ("United States" alone is NOT remote —
    # it can just be the country of an on-site office).
    remote = _has(remote_tokens, nloc)
    has_specific_us_office = (_has(_US_HUBS, nloc) or _has_us_state(nloc)
                              or _has_state_abbr(original))

    # 2) Remote roles: US / North-America / global remote is a match; a remote
    #    role scoped to a foreign region only is not (unless us_only is False,
    #    which accepts remote-anywhere). Default us_only=True -> foreign-only
    #    remote stays "foreign".
    if remote:
        if us_only and foreign and not us:
            return "foreign"
        return us_remote_cat

    # 3) No remote signal. A specific non-preferred US office (hub city or state)
    #    means on-site / hybrid there -> no match. A country/region-level US listing
    #    with no specific office (e.g. "United States", "NAMER") is US-eligible.
    if has_specific_us_office:
        return "other_us"
    if us:
        return us_remote_cat
    if foreign:
        return "foreign"
    return "unknown"


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
