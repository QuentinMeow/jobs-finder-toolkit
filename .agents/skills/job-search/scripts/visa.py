"""Heuristic visa-sponsorship classification from job-description text.

Returns one of: "no" (explicit denial), "yes" (explicit offer), "unclear".
This is a heuristic on free text and MUST be treated as advisory — the agent
should confirm sponsorship with the employer/posting before relying on it.
"""
from __future__ import annotations

import re

from common import normalize
from job_metadata import classify_sponsorship_evidence

_H1B_TRANSFER_RE = re.compile(
    r"\b(?:h-?1b transfer|transfer your h-?1b|transfer your visa|cap[- ]exempt)\b",
    re.I,
)
_GREEN_CARD_RE = re.compile(
    r"\b(?:green card|i-140|permanent residency|employment-based green card|"
    r"perm (?:process|filing|labor certification))\b",
    re.I,
)


def classify_visa(text: str) -> tuple[str, list[str]]:
    """Map the canonical sponsorship assessment to search labels."""
    verdict, hits = classify_sponsorship_evidence(text)
    return {"likely": "yes", "unlikely": "no"}.get(verdict, "unclear"), hits


def visa_tags(text: str) -> list[str]:
    """Soft tags relevant to a transfer/green-card candidate."""
    norm = normalize(text)
    tags = []
    if _H1B_TRANSFER_RE.search(norm):
        tags.append("h1b_transfer_friendly")
    if _GREEN_CARD_RE.search(norm):
        tags.append("green_card_mentioned")
    return tags
