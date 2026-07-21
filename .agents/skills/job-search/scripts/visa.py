"""Heuristic visa-sponsorship classification from job-description text.

Returns one of: "no" (explicit denial), "yes" (explicit offer), "unclear".
This is a heuristic on free text and MUST be treated as advisory — the agent
should confirm sponsorship with the employer/posting before relying on it.
"""
from __future__ import annotations

from common import normalize

# Explicit denials -> "no". Kept specific to avoid rejecting boilerplate
# "must be authorized to work" language that even sponsoring employers use.
NEGATIVE = [
    "no sponsorship",
    "no visa sponsorship",
    "not offer sponsorship",
    "does not offer sponsorship",
    "do not offer sponsorship",
    "not offering visa sponsorship",
    "unable to sponsor",
    "not able to sponsor",
    "cannot sponsor",
    "can not sponsor",
    "will not sponsor",
    "does not sponsor",
    "do not sponsor",
    "not provide sponsorship",
    "unable to provide sponsorship",
    "unable to provide visa sponsorship",
    "not able to provide visa sponsorship",
    "sponsorship will not be available",
    "sponsorship support will not be available",
    "without sponsorship",
    "without visa sponsorship",
    "without employer sponsorship",
    "sponsorship is not available",
    "sponsorship not available",
    "not eligible for sponsorship",
    "not eligible for visa sponsorship",
    "does not require sponsorship",
    "do not require sponsorship",
    "must not require sponsorship",
    "not require sponsorship now or in the future",
    "authorized to work in the united states without sponsorship",
    "authorized to work without sponsorship",
    "work authorization without sponsorship",
    "us citizens only",
    "u.s. citizens only",
    "must be a us citizen",
    "must be a u.s. citizen",
    "citizenship is required",
    "green card holders only",
    "gc only",
    "green card required",
    "permanent resident only",
]

# Explicit offers -> "yes".
POSITIVE = [
    "sponsor h-1b",
    "sponsor h1b",
    "h-1b sponsorship",
    "h1b sponsorship",
    "visa sponsorship available",
    "sponsorship available",
    "offer visa sponsorship",
    "provide visa sponsorship",
    "we sponsor",
    "will sponsor",
    "happy to sponsor",
    "open to sponsoring",
    "able to sponsor",
    "sponsor work visas",
    "sponsor visas",
    "green card sponsorship",
    "green card process",
    "perm process",
    "immigration sponsorship",
    "immigration support",
    "relocation and immigration",
    "cap-exempt",
    "cap exempt",
]

# Extra tags of interest for a candidate needing a transfer / green card.
H1B_TRANSFER_HINTS = ["h-1b transfer", "h1b transfer", "transfer your h-1b",
                      "transfer your visa", "cap-exempt", "cap exempt"]
GREENCARD_HINTS = ["green card", "perm", "i-140", "permanent residency",
                   "employment-based green card"]


def classify_visa(text: str) -> tuple[str, list[str]]:
    """Return (label, matched_phrases). Negatives win over positives."""
    norm = normalize(text)
    if not norm:
        return "unclear", []
    neg = [p for p in NEGATIVE if p in norm]
    if neg:
        return "no", neg
    pos = [p for p in POSITIVE if p in norm]
    if pos:
        return "yes", pos
    return "unclear", []


def visa_tags(text: str) -> list[str]:
    """Soft tags relevant to a transfer/green-card candidate."""
    norm = normalize(text)
    tags = []
    if any(h in norm for h in H1B_TRANSFER_HINTS):
        tags.append("h1b_transfer_friendly")
    if any(h in norm for h in GREENCARD_HINTS):
        tags.append("green_card_mentioned")
    return tags
