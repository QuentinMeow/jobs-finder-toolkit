"""Classify a posting location string against the configured location policy.

The active job-search location policy (see ``config.location_policy``) decides
which postings are acceptable — a set of preferred-metro tokens plus a US-remote /
``us_only`` rule. Every application's ``meta.yaml`` records the posting ``location``
(top-level for a single role, per-entry under ``jobs:`` for a multi-role
application). This module turns those free-text location strings into one of a few
categories and a match/no-match verdict so that
``skills/application-tracker/scripts/status.py --check-locations`` and
``skills/resume-writer/scripts/check.py`` can flag drafts that do not
respect the location criteria.

This module is policy-injected and carries NO candidate-specific defaults: the
preferred-metro list is empty here and supplied at call time via ``policy`` (from
``config.location_policy``). It mirrors the location logic in
``skills/job-search/scripts/scoring.py`` (``location_ok``) but works from
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
from functools import lru_cache

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

# The individual words of the markers above. Some ATS boards put a WORKPLACE WORD
# in the structured location field ("Hybrid", "In-Office", "Distributed") and
# leave the actual cities inside the JD body, so such a field states a work MODE
# and carries no geography at all. Used to recognize that shape — see
# ``_is_workplace_word_only``.
_WORKPLACE_MARKER_WORDS = frozenset(
    word
    for marker in _GENERIC_WORKPLACE_MARKERS
    for word in re.findall(r"[a-z0-9]+", marker)
)

# EVERY token list below is matched on WORD BOUNDARIES (``_token_pattern``), never
# as a bare substring. A substring test over these lists fails in both directions
# and this module has now been bitten by it three times: "ote" inside "remote",
# "apac" inside "capacity", "india" inside "Indianapolis". So: a token here is a
# whole word (or whole phrase), and a token that is only meaningful as a fragment
# does not belong in a list — give it its own anchored regex, as ``_FOREIGN_ABBR_RE``
# does for uk / eu.
#
# Remote signals. "hybrid" / "in-office" / "on-site" are deliberately NOT here —
# a hybrid role in a specific non-preferred city still requires being in that city.
# "distributed" is deliberately NOT a remote signal: a bare "Distributed" location
# tag is a company-structure descriptor, not a work-location grant, and it rode a
# US-remote match onto globally-pinned roles whose title/JD names a foreign city
# (e.g. a "Distributed" tag on a Melbourne-only role). Such a tag is unverified —
# it classifies as "unknown" (review manually) rather than a us_remote match.
REMOTE_TOKENS = (
    "remote", "remotely", "work from home", "wfh", "fully remote", "anywhere",
    "worldwide", "global",
)

# Of those, the ones that assert UNRESTRICTED geography rather than a work MODE.
# "Anywhere" / "Worldwide" / "Global" name a scope that necessarily includes the
# US; "Remote" / "WFH" name how the work is done and say nothing about where. A
# board that puts the bare word "remote" in the location field has stated no
# country at all — a foreign employer's posting scored a confident US-remote match
# on exactly that. So mode-only remoteness needs a US signal from somewhere before
# it can be read as US-remote; unrestricted scope already carries one.
_UNRESTRICTED_SCOPE_TOKENS = ("anywhere", "worldwide", "global")

# Broad regions that imply remote across North America (include the US).
US_REMOTE_REGIONS = (
    "united states", "usa", "u.s.", "u.s.a", "us remote", "remote us",
    "remote - us", "remote, us", "remote (us", "north america", "namer",
    "americas",
)

# Non-US-only regions -> foreign.
FOREIGN_REGIONS = ("emea", "apac", "latam", "europe")

# Ambiguous source-defined region buckets that carry no usable geography by
# themselves. Detection is deliberately token-exact and is only consulted after
# all geographic and workplace signals have failed. Some words here are normally
# decisive signals (for example EMEA/APAC are foreign and "global" is remote);
# those existing classifications win before this list can relabel anything.
# "namer" and "americas" are intentionally absent because they are established
# US-remote regions.
_AMBIGUOUS_REGION_BUCKET_WORDS = frozenset({
    "central", "east", "west", "amer", "emea", "apac", "international",
    "usca", "global", "region", "field",
})

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
# 26 of those abbreviations are ALSO ISO-3166 alpha-2 country codes, so a bare
# two-letter code in a location field is not self-evidently a US signal:
#   AL Albania    AR Argentina  AZ Azerbaijan  CA Canada     CO Colombia
#   DE Germany    GA Gabon      ID Indonesia   IL Israel     IN India
#   KY Cayman Is. LA Laos       MA Morocco     MD Moldova    ME Montenegro
#   MN Mongolia   MO Macao      MS Montserrat  MT Malta      NC New Caledonia
#   NE Niger      PA Panama     SC Seychelles  SD Sudan      TN Tunisia
#   VA Vatican
# ``Bangalore, IN`` and ``Indianapolis, IN`` are the SAME shape — trailing,
# comma-delimited — so position cannot separate them. What separates them is
# whether the rest of the same field already names the country the code stands
# for; see ``_resolve_state_abbrs``.
_STATE_COUNTRY_CODE_COLLISIONS = {
    "AL", "AR", "AZ", "CA", "CO", "DE", "GA", "ID", "IL", "IN", "KY", "LA",
    "MA", "MD", "ME", "MN", "MO", "MS", "MT", "NC", "NE", "PA", "SC", "SD",
    "TN", "VA",
}
# Foreign place tokens -> the ISO code of the country they name, restricted to
# the collision set above. When such a token appears in the SAME field as its own
# code, the code corroborates a country the string already names and is therefore
# a country code, not a state ("Bangalore, IN" -> India). A token naming a
# DIFFERENT country never resolves the code — "Dublin, CA" (Dublin, California is
# real) and "Milan, IN" (Milan, Indiana is real) stay contradictory and reach
# review.
_FOREIGN_TOKEN_COUNTRY_CODE = {
    # Canada
    "canada": "CA", "toronto": "CA", "vancouver": "CA", "montreal": "CA",
    "quebec": "CA", "british columbia": "CA", "alberta": "CA",
    "saskatchewan": "CA", "manitoba": "CA",
    # Germany
    "germany": "DE", "berlin": "DE", "munich": "DE", "hamburg": "DE",
    "cologne": "DE", "frankfurt": "DE", "karlsruhe": "DE", "nuremberg": "DE",
    "bremen": "DE", "stuttgart": "DE",
    # India
    "india": "IN", "bangalore": "IN", "bengaluru": "IN", "hyderabad": "IN",
    "pune": "IN", "mumbai": "IN", "delhi": "IN", "chennai": "IN",
    "gurugram": "IN", "gurgaon": "IN",
    # Israel / Indonesia / Argentina / Colombia / Morocco / Panama
    "israel": "IL", "tel aviv": "IL",
    "indonesia": "ID", "jakarta": "ID",
    "argentina": "AR", "colombia": "CO", "morocco": "MA", "panama": "PA",
}
# The codes whose FOREIGN reading is routinely written as a bare `City, XX` in
# tech postings. When one of these is the ONLY geography in the string ("Remote -
# CA", "IN"), neither reading is earned and the verdict is `review` — see
# ``_bare_contested_code``. Every other collision above keeps its US-state
# reading, because "Remote - VA" is Virginia and not the Vatican: a US job search
# never sees the foreign reading of those codes, and inventing a review for them
# would be noise with no recall to show for it.
_CONTESTED_COUNTRY_CODES = {"CA", "DE", "IN", "IL"}
# Non-preferred US hub cities -> a specific US office (on-site/hybrid) when not remote.
_US_HUBS = {
    "san francisco", "bay area", "silicon valley", "mountain view", "palo alto",
    "menlo park", "sunnyvale", "santa clara", "san jose", "cupertino", "oakland",
    "redwood city", "san mateo", "foster city", "new york", "nyc", "brooklyn",
    "boston", "cambridge", "austin", "dallas", "houston", "denver", "boulder",
    "chicago", "atlanta", "miami", "los angeles", "san diego", "portland",
    "phoenix", "raleigh", "durham", "pittsburgh", "philadelphia", "minneapolis",
    "nashville", "salt lake", "washington, dc", "washington, d.c",
    "livingston", "richardson",
    "sandy", "arlington", "seattle", "bellevue", "redmond", "kirkland",
    "tacoma", "everett",
}
# Every US place name this module knows, for the containment rule in
# ``_foreign_matches``: a word boundary separates "India" from "Indianapolis",
# but not "Mexico" from "New Mexico", where one whole place name CONTAINS
# another. The longest place name wins.
_US_PLACE_NAMES = tuple(sorted(set(_US_STATE_NAMES) | set(_US_HUBS)))
_FOREIGN_TOKENS = (
    # uk / u.k / eu are NOT here: they are fragments, not words, and belong to
    # the anchored `_FOREIGN_ABBR_RE` below (which already runs over the same
    # text). A space-prefixed " uk" entry is exactly the kind of hand-rolled
    # boundary this module no longer needs.
    "united kingdom", "london", "england", "scotland",
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
    "malaysia", "dubai", "abu dhabi",
    # Inflections get their OWN entry now that matching is whole-word: boards
    # write both "Nordic" and "Nordics", and a prefix can no longer cover both.
    "nordic", "nordics",
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

# Short foreign abbreviations. These live in their own anchored regex rather than
# in `_FOREIGN_TOKENS` because they are two letters that occur inside ordinary
# words; the boundary is the whole point of the entry.
_FOREIGN_ABBR_RE = re.compile(r"\b(uk|u\.k\.?|eu)\b")

# A foreign city name that is IMMEDIATELY qualified by a US state names the US
# city of that name. "Vancouver, WA, US" is Vancouver, Washington — it read as
# mixed US/foreign scope and went to review, and the same shape recurs for every
# transplanted place name a US map carries (#247).
#
# Only a comma-delimited abbreviation or a spelled-out state counts, so "London
# or Toronto" cannot be rescued by the Oregon abbreviation sitting in "or".
_US_STATE_SUFFIX_RE = re.compile(
    r"\s*,\s*(?P<state>"
    + "|".join(sorted((*(s.lower() for s in _US_STATE_ABBR),
                       *_US_STATE_NAMES), key=lambda t: (-len(t), t)))
    + r")(?![a-z0-9])"
    r"|\s+(?P<name>"
    + "|".join(sorted(_US_STATE_NAMES, key=lambda t: (-len(t), t)))
    + r")(?![a-z0-9])")

# Canada's own place tokens. Named separately because a US posting routinely
# offers the two countries TOGETHER, and that pair is not "mixed scope" — the US
# branch of it is exactly the eligibility a US candidate needs.
_CANADA_TOKENS = frozenset({
    "canada", "toronto", "vancouver", "montreal", "quebec",
    "british columbia", "alberta", "saskatchewan", "manitoba",
})

# The US and Canada named as ONE coordinated country-level scope: "Remote in the
# United States or Canada", "US & Canada", "US/Canada — ET hours", and the ATS
# short form "USCA". Each of these was reaching `mixed_us_foreign_scope` review
# (or `weird_location_format`) even though a US candidate plainly satisfies the
# US branch — a plainly eligible remote role presented as an unclassified
# location failure (#262, #247).
#
# Coordination is required: this recognizes a country PAIR, never the mere
# co-occurrence of a US and a Canadian place, so "San Francisco, CA / Toronto,
# Canada" keeps the mixed-scope reading it has always had.
_US_CANADA_PAIR_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    r"(?:united states|u\.s\.a\.?|u\.s\.?|usa|us|north america)"
    r"\s*(?:,\s*)?(?:/|&|\+|-|or|and)\s*(?:the\s+)?canada"
    r"|canada\s*(?:,\s*)?(?:/|&|\+|-|or|and)\s*(?:the\s+)?"
    r"(?:united states|u\.s\.a\.?|u\.s\.?|usa|us)"
    r"|usca"
    r")(?![a-z0-9])")

MATCH_CATEGORIES = ("metro", "us_remote")

_WORKPLACE_VALUES = {"remote", "hybrid", "onsite", "unknown"}
_REMOTE_JD_RULES = (
    ("jd_fully_remote", re.compile(r"\bfully\s+remote\b", re.I)),
    ("jd_remote_role", re.compile(
        r"\bremote(?:[- ]first)?\s+(?:role|position|job|opportunity)\b", re.I)),
    ("jd_work_remotely", re.compile(r"\bwork(?:ing)?\s+remotely\b", re.I)),
    # The noun form of the same grant. "work remotely" is an ADVERB phrase, so a
    # JD that only ever says "Work From Home 100% of the time" — or the "WFH"
    # abbreviation every US job board prints — stated remote work and was not
    # recognized as remote at all. The negative lookahead keeps the PERK out: a
    # "work from home stipend" is a benefit line, not a statement about where
    # this role is performed.
    ("jd_work_from_home", re.compile(
        r"\b(?:work(?:s|ing)?\s+from\s+home|wfh)\b"
        r"(?!\s*(?:stipend|allowance|budget|reimbursement|equipment|setup|"
        r"office\s+stipend))", re.I)),
    ("jd_remote_scope", re.compile(
        r"\bremote(?:ly)?\s+(?:within|in|from|across)\s+(?:the\s+)?"
        r"(?:united states|u\.?s\.?a?|north america|americas)\b", re.I)),
    ("jd_office_or_remote", re.compile(
        r"\b(?:hub|office|location)s?\b.{0,120}\bor\s+remotely\b|"
        r"\bor\s+remotely\b.{0,120}\b"
        r"(?:united states|u\.?s\.?a?|north america|americas)\b", re.I | re.S)),
    # "<role> can/may/could … remote" needs a verb that binds remote to THIS
    # role. Without one the rule reduces to three common words in one paragraph
    # and any JD sentence about somebody else's remote work grants remote work:
    # "The job may also involve mentoring remote interns." The qualifier group
    # used to carry a trailing `?`, and `\b…?\b` collapses to zero width, so the
    # binding was optional — i.e. absent. Either a qualifying verb runs between
    # the modal and "remote", or the modal is followed directly by "be (fully)
    # remote"; the spans are tight enough to keep the three anchors in one
    # clause. ("filled" is deliberately absent: "can be filled by a remote
    # contractor" describes hiring, not where the job is done.)
    ("jd_role_can_be_remote", re.compile(
        r"\b(?:role|position|job)\b.{0,80}\b(?:can|may|could)\b"
        r"(?:"
        r".{0,40}\b(?:held|based|perform(?:ed)?|work(?:ed|ing)?|done|"
        r"locat(?:ed)?)\b.{0,40}\bremot(?:e|ely)\b"
        r"|"
        r"\s+(?:also\s+)?be\s+(?:fully\s+|entirely\s+|completely\s+|100%\s+)?"
        r"remot(?:e|ely)\b"
        r")",
        re.I | re.S)),
    # An employer STATING it will hire remotely. "Hiring for Santa Clara, San
    # Diego, Austin and Boxborough locations. Open to hire for Remote work as
    # well." is as explicit a remote grant as a JD gets, and no rule above could
    # see it: it names no "remote role", no "work remotely", no hub-or-remotely
    # alternation. The posting therefore carried only its board's `remote` flag,
    # which — untrusted, uncorroborated — sent a direct-fit role to review
    # instead of the shortlist (#290).
    #
    # The remote NOUN is mandatory. Without it the rule reduces to "open to …
    # remote" and any JD that welcomes candidates with remote-team experience
    # becomes a remote posting.
    ("jd_remote_eligible_offer", re.compile(
        r"\b(?:open\s+to|available\s+for|eligible\s+for|will\s+consider|"
        r"can\s+consider|happy\s+to\s+consider|considering)\b"
        r"[^.;:!?\n]{0,40}?\bremote\b\s*"
        r"(?:work(?:ers?|ing)?|candidates?|hir(?:e|es|ing)|employees?|"
        r"applicants?|arrangements?|options?|opportunit(?:y|ies)|roles?|"
        r"positions?|locations?)\b", re.I)),
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
    # An onsite TOTALITY word. "100% onsite" / "fully on-site" is as absolute an
    # office obligation as "must work onsite", but it names no requirement verb
    # and carries no day count, so `jd_onsite_required` never saw it and the role
    # read as having no workplace evidence at all.
    ("jd_onsite_absolute", re.compile(
        r"\b(?:100\s*%|fully|entirely|completely|strictly)\s*"
        r"(?:-\s*)?(?:onsite|on[- ]site|in[- ]office|in\s+office|"
        r"in[- ]person)\b", re.I)),
    # A STRUCTURED field whose value is onsite. Several ATS templates emit the
    # workplace mode as a labelled field in the JD body ("Position Role Type:
    # Onsite", "Work Setting: In-office") rather than as prose, so no
    # sentence-shaped rule could ever reach it. The label and the value must be
    # adjacent, which is what keeps this from firing on incidental prose.
    ("jd_onsite_field", re.compile(
        r"\b(?:position\s+role\s+type|role\s+type|work\s+setting|"
        r"work\s+type|workplace\s+type|work\s+arrangement|work\s+model|"
        r"location\s+type)\b\s*[:\-–—]\s*"
        r"(?:onsite|on[- ]site|in[- ]office|in\s+office|in[- ]person)\b", re.I)),
)

# A negated in-office/onsite obligation ("there is no minimum in-office
# requirement", "no in-office requirement", "not required to be onsite") is the
# OPPOSITE of an onsite mandate and must not fire ``jd_onsite_required``. Checked
# against the short window immediately BEFORE the onsite match.
_ONSITE_NEGATION_RE = re.compile(
    r"(?:\bno\b|\bnot\b|\bno\s+minimum\b|\bwithout\b|\bisn'?t\b|\baren'?t\b|"
    r"\bnever\b|\bzero\b)\s*$", re.I)

# The onsite rules whose match is PROSE, and so can be preceded by a negation
# that reverses it. `jd_onsite_field` is excluded on purpose: its match is a
# `label: value` pair, where a preceding word is part of a different field.
_ONSITE_NEGATABLE_RULES = frozenset({"jd_onsite_required", "jd_onsite_absolute"})

# A remote field label whose VALUE is negative. Boards emit the workplace mode as
# a labelled field ("Remote Position: No", "Remote: No", "Remote? No"), and the
# label alone is worded exactly like a remote grant — `jd_remote_role` matched
# the "Remote Position" of "Remote Position: No" and classified an office-bound
# role as remote. Checked against the text immediately AFTER a remote match, and
# the separator is required: a sentence that merely ENDS before a new one
# starting with "No" ("...a fully remote role. No prior experience needed.")
# is not a negated field and must keep its remote evidence.
_REMOTE_NEGATED_VALUE_RE = re.compile(
    r"^\s*[:?=\-–—]\s*(?:no|none|false|n)\b", re.I)

# A remote grant that is NEGATED before it is even stated. The onsite rules have
# had this guard since "no minimum in-office requirement"; the remote rules had
# only the trailing field-value guard above, so the mirror-image sentence —
# "There is NO work from home for this position", "primarily onsite with little
# or NO WFH" — fired ``jd_work_from_home`` and classified a cleared, badge-in,
# five-days-a-week role as a confident US-remote MATCH.
#
# The window is clause-local by construction: ``[^.;:!?\n]{0,24}$`` cannot cross
# a sentence break, so a negative statement about something else earlier in the
# document ("We are not able to sponsor visas. You may work from home.") can
# never reach the grant.
_REMOTE_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|without|cannot|can'?t|isn'?t|aren'?t|nor|zero|little|"
    r"minimal|unable|rarely|seldom)\b[^.;:!?\n]{0,24}$", re.I)

# The remote rules whose match is PROSE, and so can be reversed by a negation
# immediately before it. ``jd_office_or_remote`` and ``jd_role_can_be_remote``
# are excluded: both already bind remote to this role across a span of their
# own, so their match START sits mid-clause where a preceding word is part of
# the rule's own subject rather than a negation of it.
_REMOTE_NEGATABLE_RULES = frozenset({
    "jd_fully_remote", "jd_remote_role", "jd_work_remotely",
    "jd_work_from_home", "jd_remote_scope", "jd_remote_eligible_offer",
})

# A remote allowance with an ANNUAL CEILING is a benefit, not a work mode. Boards
# print "you may work fully remote from anywhere for up to four weeks per year"
# in the perks section of a role that is required in-office three days a week;
# read as a workplace declaration it manufactured a remote/hybrid contradiction
# and buried an unambiguous local role in a four-digit review queue (#301).
_LIMITED_REMOTE_BENEFIT_RE = re.compile(
    r"\b(?:up\s+to\s+)?(?:\d{1,3}|one|two|three|four|five|six|seven|eight|"
    r"nine|ten|eleven|twelve)\s+(?:business\s+|working\s+|calendar\s+)?"
    r"(?:days?|weeks?|months?)\b[^.;:!?\n]{0,24}?"
    r"\b(?:per|a|each|every)\s+(?:calendar\s+)?(?:year|month|quarter)\b", re.I)

# Sentence/clause delimiters. A guard that reads "the text around this match"
# means the clause it sits in, never the paragraph: crossing a delimiter is how
# a benefits line comes to speak for a requirement two sentences away.
_CLAUSE_BREAKS = ".;:!?\n"

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


# A remote grant that names its own residency metro. Boards routinely write
# "this is a remote role BUT you must reside in <Metro>" — the grant satisfies
# `_REMOTE_JD_RULES`, the restriction was invisible, and the posting became a
# confident us_remote MATCH tied to a metro the candidate never asked for. Three
# of four confident matches in one live company re-check were this shape.
#
# The requirement word is mandatory and the span between it and the residency verb
# is tight, the way `jd_role_can_be_remote` binds "remote" to THIS role: without
# it, "many of our engineers live in Austin" describes somebody else's address and
# would rewrite the posting's geography.
# ``gap`` and ``prep`` are named only so ``_residency_names_us_country`` can read
# them; they do not change what the pattern matches.
_JD_RESIDENCY_RE = re.compile(
    r"\b(?:must|required?|requirement|need\s+to|expected\s+to|have\s+to)\b"
    r"(?P<gap>[^.;:!?\n]{0,60}?)"
    r"\b(?:resid(?:e|es|ing|ency)|live|living|located|based)\b\s+"
    r"(?P<prep>in|within|near)\s+(?:the\s+)?"
    r"(?P<place>[^.;:!?\n]{2,60})",
    re.I,
)

# A residency clause that is NEGATED states no requirement: "you do not need to
# reside in the United States", "there is no requirement to live in the US". It
# is checked only where a negation would flip the answer (see
# ``_residency_names_us_country``), so its worst case is leaving a posting at
# review — never a confident wrong verdict.
#
# The window is short and anchored to the requirement word on purpose. A negative
# clause EARLIER in the same sentence usually negates something else entirely
# ("we are not able to sponsor visas; you must reside in the United States"), and
# a sentence-wide search reads that as "residency not required" and throws the
# posting away. Both real shapes put the negation adjacent to the requirement
# word — before it ("do NOT need to", "there is NO requirement", "are NOT
# required") or inside the gap that follows it ("must NOT reside in").
_RESIDENCY_NEGATION_RE = re.compile(r"(?:\b(?:no|nor|not|never)\b|n't)", re.I)
_RESIDENCY_NEGATION_WINDOW = 16


# ---------------------------------------------------------------------------
# Residence EXCLUSIONS and time-zone bounds on an otherwise open US-remote grant
#
# "Remote - US" is a grant with a hole in it more often than not: the JD then
# names the states or metros the employer cannot hire in, or the time zones the
# candidate must sit in. Neither was read, so 27 postings that explicitly could
# not employ this candidate came back `match` / confidence `high` with no review
# reason at all (#297), and Washington-excluded / EST-CST-only remote roles were
# ranked for a Seattle candidate (#242). Remote does not mean hireable from
# every US location.
# ---------------------------------------------------------------------------

# The cue that opens an exclusion, plus everything to the end of its clause.
_RESIDENCE_EXCLUSION_RE = re.compile(
    r"\b(?:"
    r"except(?:\s+(?:for|in))?|excluding|exclusive\s+of|"
    r"not\s+(?:open|available|eligible)\s+(?:to|in|for)|"
    r"(?:unable|not\s+able)\s+to\s+(?:hire|employ)\s+(?:in|from)|"
    r"(?:do(?:es)?\s+not|cannot|can'?t)\s+(?:hire|employ)\s+(?:in|from)|"
    r"ineligible\s+(?:in|from)"
    r")\b(?P<places>[^.;:!?\n]{2,180})", re.I)

# A pay-geography clause is not a hiring restriction. Colorado/NYC pay
# transparency law makes employers list states in a COMPENSATION sentence, and
# reading that as an eligibility list would reject the postings that comply.
_COMP_CONTEXT_RE = re.compile(
    r"\$|\b(?:salary|salaries|compensation|pay|paid|wage|bonus|equity|"
    r"base\s+range|pay\s+range|pay\s+transparency|equal\s+pay)\b", re.I)

# "Washington" the state versus "Washington, DC" the city: an exclusion naming
# the capital must not exclude a Seattle candidate.
_WASHINGTON_DC_RE = re.compile(r"washington\s*,?\s*d\.?c\.?", re.I)

# Preferred-metro token -> the US state that contains it, so a JD that excludes
# a STATE ("open in all US states except … Washington …") is understood to
# exclude the metro the candidate actually named. Generic US geography, not
# candidate data: the metro list itself always comes from the policy.
_METRO_STATE = {
    "seattle": "washington", "bellevue": "washington", "redmond": "washington",
    "kirkland": "washington", "tacoma": "washington", "everett": "washington",
    "portland": "oregon",
    "san francisco": "california", "bay area": "california",
    "silicon valley": "california", "mountain view": "california",
    "palo alto": "california", "menlo park": "california",
    "sunnyvale": "california", "santa clara": "california",
    "san jose": "california", "cupertino": "california",
    "oakland": "california", "redwood city": "california",
    "san mateo": "california", "foster city": "california",
    "los angeles": "california", "san diego": "california",
    "new york": "new york", "nyc": "new york", "brooklyn": "new york",
    "boston": "massachusetts", "cambridge": "massachusetts",
    "austin": "texas", "dallas": "texas", "houston": "texas",
    "richardson": "texas",
    "denver": "colorado", "boulder": "colorado",
    "chicago": "illinois", "atlanta": "georgia", "miami": "florida",
    "phoenix": "arizona", "raleigh": "north carolina",
    "durham": "north carolina", "pittsburgh": "pennsylvania",
    "philadelphia": "pennsylvania", "minneapolis": "minnesota",
    "nashville": "tennessee", "salt lake": "utah", "sandy": "utah",
    "arlington": "virginia",
}

# US time zones as a JD writes them, folded onto four buckets.
_TZ_ZONE_TOKENS = {
    "est": "ET", "edt": "ET", "et": "ET", "eastern": "ET", "east coast": "ET",
    "cst": "CT", "cdt": "CT", "ct": "CT", "central": "CT",
    "mst": "MT", "mdt": "MT", "mt": "MT", "mountain": "MT",
    "pst": "PT", "pdt": "PT", "pt": "PT", "pacific": "PT", "west coast": "PT",
}
_TZ_ZONE_ALT = "|".join(
    sorted((re.escape(t) for t in _TZ_ZONE_TOKENS), key=lambda t: (-len(t), t)))
# A zone name is only a BOUND when the clause also carries the noun that makes
# it one. "CT" in a list of excluded states is Connecticut; "9am-5pm Pacific" is
# a working-hours note, not a residency rule. Requiring "time zone(s)" or
# "hours" AFTER the zone name (or the zone after "time zone") separates them.
# "overlap" is deliberately NOT a bound noun: "4 hours of ET overlap" is a soft
# expectation that most Pacific candidates satisfy, and hard-rejecting it would
# lose real roles.
_TZ_BOUND_RE = re.compile(
    r"(?<![a-z0-9])(?:" + _TZ_ZONE_ALT + r")(?![a-z0-9])"
    r"(?:[^.;:!?\n]{0,40}?(?<![a-z0-9])(?:" + _TZ_ZONE_ALT + r")(?![a-z0-9]))*"
    r"[^.;:!?\n]{0,30}?\b(?:time\s*zones?|hours)\b"
    r"|\btime\s*zones?\b[^.;:!?\n]{0,30}?"
    r"(?<![a-z0-9])(?:" + _TZ_ZONE_ALT + r")(?![a-z0-9])")
_TZ_ZONE_SCAN_RE = re.compile(
    r"(?<![a-z0-9])(?:" + _TZ_ZONE_ALT + r")(?![a-z0-9])")
_METRO_TIMEZONE = {
    "seattle": "PT", "bellevue": "PT", "redmond": "PT", "kirkland": "PT",
    "tacoma": "PT", "everett": "PT", "portland": "PT",
    "san francisco": "PT", "bay area": "PT", "silicon valley": "PT",
    "mountain view": "PT", "palo alto": "PT", "menlo park": "PT",
    "sunnyvale": "PT", "santa clara": "PT", "san jose": "PT",
    "cupertino": "PT", "oakland": "PT", "redwood city": "PT",
    "san mateo": "PT", "foster city": "PT", "los angeles": "PT",
    "san diego": "PT",
    "denver": "MT", "boulder": "MT", "salt lake": "MT", "sandy": "MT",
    "phoenix": "MT",
    "chicago": "CT", "austin": "CT", "dallas": "CT", "houston": "CT",
    "richardson": "CT", "minneapolis": "CT", "nashville": "CT",
    "new york": "ET", "nyc": "ET", "brooklyn": "ET", "boston": "ET",
    "cambridge": "ET", "atlanta": "ET", "miami": "ET", "raleigh": "ET",
    "durham": "ET", "pittsburgh": "ET", "philadelphia": "ET",
    "arlington": "ET", "livingston": "ET",
}


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


def _token_key(tokens) -> tuple[str, ...]:
    """A hashable, order-stable cache key for a token list."""
    if isinstance(tokens, tuple):
        return tokens
    return tuple(sorted(tokens))


@lru_cache(maxsize=64)
def _token_pattern(tokens: tuple[str, ...]):
    """Compile ONE word-bounded alternation for a token list.

    The boundary is ``(?<![a-z0-9]) … (?![a-z0-9])`` rather than ``\\b`` because
    several tokens begin or end with punctuation — ``u.s.``, ``remote (us``,
    ``washington, d.c`` — where ``\\b`` asserts about the wrong character. The
    lookarounds treat every separator this module's normalizer keeps (space,
    comma, dot, hyphen, slash, parenthesis) as a boundary, which is what a
    location field actually uses.

    Alternation is longest-first so a longer token is never shadowed by a
    shorter one that prefixes it. One compiled pattern per list keeps the cost at
    one scan per call rather than N substring scans, and the cache makes the
    policy-supplied lists (metro, remote tokens) as cheap as the constants.
    """
    parts = sorted({str(t) for t in tokens if str(t).strip()},
                   key=lambda t: (-len(t), t))
    if not parts:
        return None
    return re.compile(r"(?<![a-z0-9])(?:"
                      + "|".join(re.escape(p) for p in parts)
                      + r")(?![a-z0-9])")


def _has(tokens, nloc: str) -> bool:
    pattern = _token_pattern(_token_key(tokens))
    return bool(nloc and pattern is not None and pattern.search(nloc))


def _has_us_state(nloc: str) -> bool:
    return _has(_US_STATE_NAMES, nloc)


def _state_qualified_us_city(text: str, hit: str, end: int) -> bool:
    """Whether a foreign city token is immediately qualified by a US state.

    "Vancouver, WA" / "Vancouver, Washington" is the US city; "Vancouver, CA" and
    "Vancouver, BC" are not. Only a token whose own country CODE is known can be
    resolved this way, so the shapes the module deliberately leaves contradictory
    — "Dublin, CA", "Milan, IN" — keep their review, and a code that names the
    token's OWN country ("Delhi, IN", "Toronto, CA") still reads as foreign.
    """
    m = _US_STATE_SUFFIX_RE.match(text, end)
    if m is None:
        return False
    code = _FOREIGN_TOKEN_COUNTRY_CODE.get(hit)
    if code is None:
        return False
    state = m.group("state")
    if state is None or state in _US_STATE_NAMES:
        return True
    return state.upper() != code


def _foreign_matches(text: str) -> tuple[str, ...]:
    """Foreign place tokens in ``text``, minus any a US reading accounts for.

    Word boundaries stop a token from riding inside a longer WORD ("india" in
    "Indianapolis"). They do not stop one whole place NAME from sitting inside
    another: "New Mexico" is a US state whose second word is a foreign country.
    So a foreign hit whose span lies inside a US place name's span is not
    foreign evidence — the longest place name wins. Nor do they stop a foreign
    city name that a US STATE immediately qualifies ("Vancouver, WA").
    """
    pattern = _token_pattern(_FOREIGN_TOKENS + FOREIGN_REGIONS)
    if not text or pattern is None:
        return ()
    us_pattern = _token_pattern(_US_PLACE_NAMES)
    us_spans = [m.span() for m in us_pattern.finditer(text)] if us_pattern else []
    hits = [
        m.group(0) for m in pattern.finditer(text)
        if not any(start <= m.start() and m.end() <= end
                   for start, end in us_spans)
        and not _state_qualified_us_city(text, m.group(0), m.end())
    ]
    return tuple(dict.fromkeys(hits))


def _us_canada_pair(ntext: str, foreign_hits: tuple[str, ...]) -> bool:
    """Whether ``ntext`` names the US and Canada as ONE coordinated scope.

    True only when the pair is written as a coordination (or the ``USCA`` short
    form) AND nothing else foreign is named — a third country makes it a genuine
    multi-region posting again, and ``uk``/``eu`` never ride along.
    """
    if not ntext or not _US_CANADA_PAIR_RE.search(ntext):
        return False
    if _FOREIGN_ABBR_RE.search(ntext):
        return False
    return all(hit in _CANADA_TOKENS for hit in foreign_hits)


def _residence_places(description: str) -> list[str]:
    """Normalized place lists from every residence-EXCLUSION clause in a JD.

    A clause is kept only when it is not a compensation-geography sentence and
    it actually names US geography — which is what keeps ordinary "except as
    required by law" boilerplate out.
    """
    out: list[str] = []
    for m in _RESIDENCE_EXCLUSION_RE.finditer(description or ""):
        clause = _clause_around(description, m.start(), m.end())
        if _COMP_CONTEXT_RE.search(clause):
            continue
        nplaces = _normalize(m.group("places"))
        if not (_has_us_state(nplaces) or _has(_US_HUBS, nplaces)):
            continue
        out.append(nplaces)
    return out


def _metro_is_excluded(token: str, nplaces: str) -> bool:
    """Whether one preferred-metro token is named by an exclusion list.

    Either by name ("… excluding … Seattle Metro") or by the state that contains
    it ("… all US states except … Washington …"). The capital is subtracted from
    the state reading so "Washington, DC" cannot exclude Seattle.
    """
    if _has((token,), nplaces):
        return True
    state = _METRO_STATE.get(token)
    if not state:
        return False
    if state == "washington":
        nplaces = _WASHINGTON_DC_RE.sub(" ", nplaces)
    return _has((state,), nplaces)


def _residence_exclusion_verdict(description: str, metro) -> str | None:
    """How a JD's residence exclusions bear on the configured preferred metros.

    ``"all_excluded"`` — every configured metro is named (directly or by state),
    so the employer has said it cannot hire this candidate anywhere they asked
    for. ``"unverifiable"`` — an exclusion exists but the policy configured no
    metros, so nothing can be checked and a human must read it. ``None`` — no
    exclusion, or at least one configured metro survives it.

    Deliberately asymmetric, like the residency reader: it can only NARROW an
    already-granted US-remote posting, never grant one.
    """
    clauses = _residence_places(description)
    if not clauses:
        return None
    if not metro:
        return "unverifiable"
    excluded = {
        token for token in metro
        if any(_metro_is_excluded(token, places) for places in clauses)
    }
    return "all_excluded" if len(excluded) == len(set(metro)) else None


def _bounded_timezones(text: str) -> frozenset[str]:
    """Time zones a posting explicitly BOUNDS itself to, as ET/CT/MT/PT."""
    ntext = _normalize(text)
    if not ntext:
        return frozenset()
    zones = {
        _TZ_ZONE_TOKENS[hit.group(0)]
        for m in _TZ_BOUND_RE.finditer(ntext)
        for hit in _TZ_ZONE_SCAN_RE.finditer(m.group(0))
    }
    return frozenset(zones)


def _timezone_verdict(allowed: frozenset[str], metro) -> str | None:
    """Whether a time-zone bound admits any configured preferred metro.

    ``"excluded"`` only when EVERY configured metro maps to a zone and none of
    them is allowed. One unmappable metro is enough for ``"unresolved"``: it may
    well sit in an allowed zone, and guessing in the rejecting direction is how
    a location gate loses real roles.
    """
    if not allowed or not metro:
        return "unresolved" if allowed else None
    mapped = [_METRO_TIMEZONE.get(token) for token in metro]
    known = [zone for zone in mapped if zone]
    if not known:
        return "unresolved"
    if any(zone in allowed for zone in known):
        return None
    return "excluded" if len(known) == len(mapped) else "unresolved"


def _resolve_state_abbrs(
    original: str, location_foreign_tokens,
) -> tuple[bool, tuple[str, ...]]:
    """Read the two-letter codes in a location as US states or country codes.

    Returns ``(us_state_signal, contested_codes)``.

    A code is read as a US state UNLESS the same field also names the country
    that code stands for — ``Bangalore, IN`` names India, so ``IN`` is India's
    code and supplies no US signal, while ``Indianapolis, IN`` names no country
    and keeps Indiana. Only the LOCATION may resolve the code, never the title:
    a title region ("Solutions Architect, Canada") is a coverage descriptor, and
    letting it rewrite ``Sacramento, CA`` into Canada would drop a real US
    posting — the exact failure direction this module exists to avoid.

    ``contested_codes`` are the still-unresolved codes whose foreign reading is
    plausible; the caller escalates to review when one of them is all the
    geography there is.
    """
    codes = tuple(dict.fromkeys(
        ab for ab in re.findall(r"\b[A-Z]{2}\b", original or "")
        if ab in _US_STATE_ABBR))
    if not codes:
        return False, ()
    # Only a code that actually collides with a state abbreviation can cancel a
    # state signal; anything else was never read as a state to begin with.
    named_countries = {
        code for tok in location_foreign_tokens
        if (code := _FOREIGN_TOKEN_COUNTRY_CODE.get(tok))
        in _STATE_COUNTRY_CODE_COLLISIONS
    }
    unresolved = tuple(c for c in codes if c not in named_countries)
    contested = tuple(c for c in unresolved if c in _CONTESTED_COUNTRY_CODES)
    return bool(unresolved), contested


def _bare_contested_code(nloc: str, contested: tuple[str, ...]) -> bool:
    """Whether a contested code is the ONLY geography in the location.

    ``Remote - CA`` is California or Canada and the string says nothing else;
    ``Sacramento, CA`` names a place, so the code is corroborated enough to
    read as a state. Workplace words carry no geography and are ignored.
    """
    if not contested:
        return False
    lowered = {c.lower() for c in contested}
    return not [
        word for word in re.findall(r"[a-z]+", nloc)
        if word not in lowered and word not in _WORKPLACE_MARKER_WORDS
    ]


def _is_ambiguous_region_bucket(nloc: str) -> bool:
    """Whether every normalized word is an unresolvable region-bucket word."""
    words = re.findall(r"[a-z0-9]+", nloc)
    return bool(words) and all(
        word in _AMBIGUOUS_REGION_BUCKET_WORDS for word in words)


def _is_workplace_word_only(nloc: str) -> bool:
    """Whether a normalized location is nothing but generic workplace words.

    ``Hybrid`` / ``In-Office`` / ``Distributed`` in an ATS location field name a
    work MODE, not a place: they assert no city, state, country or region. Such a
    field therefore cannot supply geography, and it cannot contradict a
    role-specific workplace statement in the JD body either.
    """
    words = re.findall(r"[a-z0-9]+", nloc)
    return bool(words) and all(word in _WORKPLACE_MARKER_WORDS for word in words)


def _residency_names_us_country(match, nplace: str, us_remote_regions) -> bool:
    """Whether a residency clause pins the role to the US as a COUNTRY.

    "You must reside in the United States" is the most common sentence in
    US-remote boilerplate, and it is a residency requirement that the whole
    country satisfies — the narrowest reading of it is still open US-remote. It
    was reaching ``unknown`` because this function did not exist: the residency
    reader knew preferred metros, US states, US hubs and foreign places, and the
    one shape it could not name was the country itself.

    Bare ``us`` is accepted separately from the region list, which carries
    ``usa`` / ``u.s.`` / ``united states`` but not the two bare letters, and only
    after ``in``/``within``. After ``near`` the word is the pronoun — "you must
    live near us" is an office, not a country — and that reading must not become
    a confident US match.
    """
    if _residency_is_negated(match):
        return False
    if _has(us_remote_regions, nplace):
        return True
    return (match.group("prep").lower() in {"in", "within"}
            and re.search(r"\bus\b", nplace) is not None)


def _residency_is_negated(match) -> bool:
    """Whether the matched residency requirement is negated.

    See ``_RESIDENCY_NEGATION_RE``: only the short window immediately before the
    requirement word and the gap between it and the residency verb are read, so
    an unrelated negative clause earlier in the same sentence cannot cancel a
    real requirement.
    """
    text = match.string
    start = max(0, match.start() - _RESIDENCY_NEGATION_WINDOW)
    return bool(_RESIDENCY_NEGATION_RE.search(text[start:match.start()])
                or _RESIDENCY_NEGATION_RE.search(match.group("gap") or ""))


def _residency_category(description: str, metro, us_remote_regions) -> str | None:
    """Geography a JD's residency requirement pins a remote grant to.

    Returns ``"metro"`` / ``"other_us"`` / ``"foreign"`` / ``"us_remote"`` for a
    place this module can read, ``"unknown"`` when a residency requirement is
    stated but its place is unreadable, and ``None`` when the JD states no
    residency requirement at all.

    Deliberately asymmetric: it exists to NARROW an already-remote posting, never
    to grant one. The place it names replaces the absent geography of a bare
    remote/workplace-tag location field — it is the only place the JD says.
    ``us_remote`` is the widest thing it can return, and only because a
    country-wide residency rule narrows an open remote grant to exactly the
    US-remote category the caller already accepts.

    Order matters and is the safe direction: foreign, then preferred metro, then
    a specific US state/hub, and only then the country. A clause that names both
    ("the United States or Canada", "the United States, preferably California")
    keeps the narrower, more rejecting reading it has always had.
    """
    match = _JD_RESIDENCY_RE.search(description or "")
    if match is None:
        return None
    place = match.group("place")
    nplace = _normalize(place)
    # "Applicants must be located in the EST or CST time zones" is a residency
    # requirement whose PLACE is a time zone, not a city. Read as an unreadable
    # place it produced `residency_restriction_unparsed` — a review that hides
    # the one thing the sentence actually settles. Hand it to the time-zone
    # reader instead, which can compare it against the configured metros (#242).
    if _bounded_timezones(place) and not (
            _has_us_state(nplace) or _has(_US_HUBS, nplace)
            or _foreign_matches(nplace)):
        return "timezone"
    place_foreign = _foreign_matches(nplace)
    # "You must reside in the United States or Canada" is satisfied by a US
    # resident. Reading the pair as plain foreign scope made the most common
    # North-American remote clause a no_match — the same recall bug #262 filed
    # against the location field, one function over.
    if not _us_canada_pair(nplace, place_foreign):
        if place_foreign or _FOREIGN_ABBR_RE.search(nplace):
            return "foreign"
    if _has(metro, nplace):
        return "metro"
    state_abbr, _contested = _resolve_state_abbrs(place, _foreign_matches(nplace))
    if _has_us_state(nplace) or _has(_US_HUBS, nplace) or state_abbr:
        return "other_us"
    if _residency_names_us_country(match, nplace, us_remote_regions):
        return "us_remote"
    return "unknown"


def _jd_names_us_scope(description: str) -> bool:
    """Whether the JD body itself names US geography.

    Used ONLY to corroborate a mode-only remote grant whose location field carries
    no country. Deliberately permissive — any US region, state or hub counts —
    because the failure it guards is the total ABSENCE of a US signal. The bare
    pronoun "us" is excluded: "join us" appears in nearly every JD written.
    """
    ndesc = _normalize(description)
    if not ndesc:
        return False
    return bool(_has(US_REMOTE_REGIONS, ndesc) or _has_us_state(ndesc)
                or _has(_US_HUBS, ndesc))


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
        if rule_id in _ONSITE_NEGATABLE_RULES:
            matches = [
                m for m in matches
                if not _ONSITE_NEGATION_RE.search(text[max(0, m.start() - 34):m.start()])
            ]
        if matches:
            hits.append(rule_id)
    return hits


def _clause_around(text: str, start: int, end: int) -> str:
    """The clause a match sits in, bounded by the nearest sentence delimiters.

    Five ``rfind``/``find`` calls rather than a scan, because this runs once per
    remote-rule match on every posting's full JD.
    """
    left = max((text.rfind(ch, 0, start) for ch in _CLAUSE_BREAKS),
               default=-1) + 1
    rights = [p for p in (text.find(ch, end) for ch in _CLAUSE_BREAKS) if p >= 0]
    return text[left:min(rights) if rights else len(text)]


def _remote_rule_hits(text: str) -> list[str]:
    """Remote JD rules, minus the three shapes that state the OPPOSITE.

    Three guards, each dropping one match rather than the whole rule — a rule
    keeps its hit as long as at least ONE of its matches survives all three:

    * a negated field VALUE after the match ("Remote Position: **No**");
    * a negation immediately BEFORE it ("there is **no** work from home for this
      position", "little or **no** WFH") — the mirror of the onsite guard, whose
      absence let a badge-in cleared role read as a confident US-remote match;
    * an annual CEILING in the same clause ("fully remote … for up to four weeks
      per year"), which is a perk in a benefits list, not this role's work mode.
    """
    text = text or ""
    hits: list[str] = []
    for rule_id, pattern in _REMOTE_JD_RULES:
        negatable = rule_id in _REMOTE_NEGATABLE_RULES
        for m in pattern.finditer(text):
            if _REMOTE_NEGATED_VALUE_RE.match(text[m.end():m.end() + 16]):
                continue
            if negatable and _REMOTE_NEGATION_RE.search(
                    text[max(0, m.start() - 30):m.start()]):
                continue
            if _LIMITED_REMOTE_BENEFIT_RE.search(
                    _clause_around(text, m.start(), m.end())):
                continue
            hits.append(rule_id)
            break
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

    # A location field that is ONLY a workplace word states a mode with no place
    # attached, so it is a board-level tag rather than a role-level obligation.
    bare_workplace_tag = _is_workplace_word_only(nloc)
    loc_hybrid = _has(("hybrid",), nloc)
    loc_remote = _has(REMOTE_TOKENS, nloc)
    remote_hits = _remote_rule_hits(description)
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
        # A PLACE-BEARING hybrid location ("Austin, TX (Hybrid)") genuinely
        # competes with a JD remote grant and needs a human. A bare "Hybrid" tag
        # does not: it names no office to report to, so the role-specific JD text
        # is the only statement of record and remote stands. Without this, boards
        # that park a workplace word in the location field turn every explicitly
        # remote posting into a review the caller reads as a rejection.
        if bare_workplace_tag:
            evidence.append("jd_remote_over_bare_workplace_tag")
        else:
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
    # A city states geographic scope; it does not state how the work is done.
    # When the JD WAS read and never mentions a work mode, the honest label is
    # `unknown` — reporting `onsite` turned an inference into a posting fact that
    # a downstream handoff had no way to tell apart from an explicit "On Site"
    # field (#237). The location verdict is untouched: an allowed city is still
    # a preferred-metro match, and this confidence has never been high enough to
    # reach the `us_scope_without_remote_workplace` branch.
    if location and (description or "").strip():
        return "unknown", "medium", evidence, review
    # No JD at all: the location field is the only statement of record, and a
    # bare city field has always been read as an office. `classify_workplace`
    # (metadata, not the gate) calls this way and depends on that reading.
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

    The raw location is the ONLY source of positive geography. The title is read
    for geography in the REJECTING direction only — it can mark a posting foreign
    (``Distributed`` + "…, Canberra"), but a region word in a title
    ("…, Americas", "…, NAmer") is a market/coverage descriptor, not a grant of
    US work eligibility, so it can never carry a posting to a match on its own.
    Full JD text supplies role-level workplace alternatives such as "one of our US
    hubs or remotely in the United States".
    """
    original = location or ""
    nloc = _normalize(original)
    ntitle = _normalize(title)
    # Foreign scope may be asserted by either field; US scope only by the location.
    context = " ".join(x for x in (nloc, ntitle) if x)
    description = description or ""
    (metro, _remote_tokens, us_remote_regions,
     allow_us_remote, us_only) = _policy_lists(policy)
    policy = policy or {}
    require_match = bool(policy.get("require_match", True))

    workplace, confidence, evidence, review = _workplace_assessment(
        original, description, workplace_hint or "", hint_trusted)
    context_foreign = _foreign_matches(context)
    foreign = (bool(context_foreign)
               or _FOREIGN_ABBR_RE.search(context) is not None)
    # Only the location may resolve a two-letter code (see _resolve_state_abbrs).
    state_abbr, contested_codes = _resolve_state_abbrs(
        original, _foreign_matches(nloc))
    us = (_has(us_remote_regions, nloc) or _has_us_state(nloc)
          or _has(_US_HUBS, nloc) or state_abbr
          or re.search(r"\bus\b", nloc) is not None)
    # "Remote in the United States or Canada", "US & Canada", "USCA": ONE
    # coordinated North-American scope whose US branch a US candidate satisfies
    # outright. It is not mixed scope, and the short form is not an unreadable
    # region bucket (#262, #247).
    us_canada = _us_canada_pair(context, context_foreign)
    if us_canada:
        foreign = False
        us = True
    preferred = _has(metro, nloc)
    has_specific_us_office = (_has(_US_HUBS, nloc) or _has_us_state(nloc)
                              or state_abbr)
    # At this point evidence contains workplace evidence only; geographic
    # evidence is appended below. A non-empty location otherwise defaults to an
    # inferred onsite workplace, which is not itself an explicit signal and must
    # not prevent a bare bucket such as "West" from escalating.
    has_workplace_signal = bool(evidence)
    weird_location_format = (
        _is_ambiguous_region_bucket(nloc)
        and not preferred
        and not foreign
        and not us
        and not has_workplace_signal
    )
    if us_canada:
        evidence.append("us_canada_scope")

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
        # A remote GRANT is not a statement of geography. Two things can still take
        # this posting out of "open US-remote", and neither was being read:
        # a residency requirement in the JD that pins the grant to one metro, and a
        # location field that names a work MODE with no country anywhere behind it.
        residency = _residency_category(description, metro, us_remote_regions)
        if residency == "metro":
            category = "metro"
            evidence.append("jd_residency_preferred_metro")
        elif residency == "us_remote":
            # The JD requires residence in the US and says nothing narrower. That
            # is a restriction the whole country satisfies, so it CONFIRMS open
            # US-remote instead of bounding it — and it is the country signal the
            # bare-remote check below would otherwise go looking for.
            category = "us_remote"
            evidence.append("jd_residency_us_scope")
        elif residency == "timezone":
            # The residency clause bounds TIME, not place. The grant is still an
            # open US-remote one; the time-zone check below decides whether this
            # candidate's metros sit inside the bound.
            category = "us_remote"
            evidence.append("remote_eligible")
        elif residency in {"other_us", "foreign"}:
            category = residency
            evidence.append("jd_remote_bound_to_residency")
        elif residency == "unknown":
            category = "unknown"
            review.append("residency_restriction_unparsed")
        elif (_is_workplace_word_only(nloc) and not us
                and not _has(_UNRESTRICTED_SCOPE_TOKENS, nloc)
                and not _jd_names_us_scope(description)):
            # Nothing — not the location field, not the title, not the JD — has
            # said this role is in the US. "Remote" alone is a work mode, and a
            # foreign employer writes it the same way a US one does.
            #
            # Scoped to a field that is NOTHING BUT workplace words. A field that
            # names a place this module's lists happen not to carry ("Remote
            # (Indianapolis)") did state geography, and demoting it would trade
            # this false positive for a worse false negative.
            category = "unknown"
            review.append("remote_without_us_scope")
        else:
            category = "us_remote"
            evidence.append("remote_eligible")
    elif has_specific_us_office:
        category = "other_us"
        evidence.append("specific_us_office")
    elif us and allow_us_remote and workplace in {"hybrid", "onsite"} \
            and confidence == "high":
        # Region-level US geography ("United States", "Americas") plus an EVIDENCED
        # office obligation from the JD or the location field: the country is known
        # but the office is not, so neither the preferred-metro rule nor US-remote
        # can be confirmed. Reviewable, not a match — and not a no_match either,
        # because the unnamed office may well be a preferred metro. An INFERRED
        # onsite (a bare region tag with no workplace evidence, confidence
        # medium/low) is untouched and keeps its historical us_remote reading.
        category = "unknown"
        review.append("us_scope_without_remote_workplace")
    elif us:
        # A country/region-only answer means US eligibility even if the ATS omitted
        # a workplace mode; preserve the historical policy behavior.
        category = "us_remote" if allow_us_remote else "other_us"
        evidence.append("broad_us_scope")
    else:
        category = "unknown"
        if weird_location_format:
            # This was already an unknown/review result. Give it a distinct
            # investigation reason without changing any match/no_match decision.
            review.append("weird_location_format")
        elif _is_workplace_word_only(nloc):
            # The board stated a work MODE where a place belongs and the JD never
            # named one either. Say so specifically instead of the catch-all
            # `unclassified_location`: the fix is to read the posting, not to
            # widen the token lists.
            review.append("workplace_tag_without_geography")

    # A two-letter code that is both a US state and a country code, with nothing
    # else in the field to corroborate either reading, is genuinely undecidable:
    # "Remote - CA" is California or Canada. Say so instead of picking one — a
    # confident wrong pick either hides a US role or presents a foreign one as
    # eligible. (A string that ALSO carries foreign scope is already a
    # mixed-scope review below, so this only fires where the code stands alone.)
    if not foreign and _bare_contested_code(nloc, contested_codes):
        review.append("ambiguous_state_or_country_code")

    # A US-remote grant is only as wide as the JD leaves it. Two clauses can take
    # this candidate out of an otherwise open grant, and neither was read: an
    # explicit list of residences the employer cannot hire in (#297) and an
    # explicit bound on which time zones an applicant may sit in (#242). Both are
    # candidate-eligibility facts, not preferences, so a posting that names every
    # configured metro in its exclusion list is a decisive no_match rather than a
    # confident match with no review reason at all.
    excluded_residence = False
    if category == "us_remote" and description:
        residence = _residence_exclusion_verdict(description, metro)
        if residence == "all_excluded":
            excluded_residence = True
            evidence.append("jd_excludes_all_preferred_residences")
        elif residence == "unverifiable":
            review.append("residence_exclusion_unverifiable")
        zones = _bounded_timezones(original + "\n" + description)
        if zones:
            verdict = _timezone_verdict(zones, metro)
            if verdict == "excluded":
                excluded_residence = True
                evidence.append("jd_timezone_excludes_preferred_metros")
            elif verdict == "unresolved":
                review.append("remote_timezone_restriction_unresolved")

    # Definitively foreign-only geography dominates any internal workplace
    # remote/hybrid/onsite tension: the role is out of a US-only search either
    # way, so it is a decisive foreign no_match, not a workplace-conflict review.
    # (Mixed US/foreign scope is category "unknown", not "foreign", so it is not
    # swallowed here and still reaches review below.)
    if category == "foreign":
        review = []
    # The two policy flags govern two DIFFERENT categories and must be read
    # separately. `require_match` is the hard-filter on non-preferred US cities
    # (`other_us`); `us_only` is the filter on non-US geography (`foreign`).
    # Conjoining them ("not require_match and not us_only") made
    # `require_match: false` a no-op for every policy that also set
    # `us_only: true` — which is what both shipped search profiles set — so
    # "Chicago, IL" and "Bellevue, WA" were dropped as no_match before anyone
    # could review them, while the profile's own comment promised
    # "false = keep all US + remote, boost preferred".
    #
    # The permissive catch-all below is deliberately kept for the REMAINING
    # categories (an unclassified `unknown`), where both-flags-false has always
    # meant "keep it": splitting only the two categories the flags actually name
    # leaves every other verdict exactly as it was.
    if excluded_residence:
        # The JD named this candidate's every configured residence — or every
        # allowed time zone excludes them. That is settled, not reviewable: a
        # review here would restate a rejection the posting already spelled out.
        decision = "no_match"
        confidence = "high"
        review = []
    elif review:
        decision = "review"
        confidence = "low"
    elif category == "metro":
        decision = "match"
    elif category == "us_remote" and allow_us_remote:
        decision = "match"
    elif category == "other_us":
        decision = "no_match" if require_match else "match"
    elif category == "foreign":
        decision = "no_match" if us_only else "match"
    elif not require_match and not us_only:
        decision = "match"
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
