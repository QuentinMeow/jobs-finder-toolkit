"""The ONE reader of the candidate profile's ``## Skills`` vocabulary.

The profile markdown (``config.profile_md_path()``) is the canonical skill
vocabulary: a ``## Skills`` section holding ``### Approved`` / ``### Weak`` /
``### Never`` subsections whose bullets read ``- Label: item, item (a, b), item``.
Three consumers read it — the render-time gate
(``skills/resume-writer/scripts/check.py``), the gardener's drift report
(``automation/gardener/skill_drift.py``), and the tailoring-card builder
(``skills/resume-writer/scripts/build_tailoring_card.py``).

WHY THIS MODULE EXISTS
----------------------
Each of those three used to carry its own copy of the section-boundary rule, and
two of the copies had DIFFERENT boundaries::

    check.py      r"^## Skills\\s*$(.*?)(?=^## )"          # no \\Z alternative
    skill_drift   r"^## Skills\\s*$(.*?)(?=^## |\\Z)"

so a profile whose ``## Skills`` is the LAST ``##`` section — a legal layout in a
user-owned file the agent may not edit without asking — parsed to
approved/weak/never = 0/0/0 in ``check.py`` while the gardener read it fine. The
consequence was silent: ``check_never_skills`` enforced the Never BLOCKLIST
against an empty list (32 blocked skills in the shipped example, zero of them
checked) and every skill token then failed with a misleading "not in the
profile's Approved or Weak lists" message. Two copies of one parsing rule was the
actual defect, so the rule now lives here once and is vendored byte-identical
into the skill that needs it (``automation/vendoring/sync_vendored.py``).

Pure stdlib, no config/IO — callers pass profile TEXT, so every consumer is
testable without the config layer.
"""

from __future__ import annotations

import re

# The canonical vocabulary lives under '## Skills'. The ``\Z`` alternative is
# load-bearing: without it a profile whose '## Skills' is the final '##' section
# parses to nothing at all (see the module docstring). Every reader of the
# section boundary must come through ``skills_section``.
SKILLS_SECTION_RE = re.compile(r"^## Skills\s*$(.*?)(?=^## |\Z)", re.M | re.S)

# The three policy subsections, in the order agents and the card present them.
SUBSECTION_HEADERS = ("Approved", "Weak", "Never")

# Split a comma-separated skill line while keeping parenthesized groups intact
# ("AWS (Lambda, SQS, SNS)" stays ONE token).
_ITEM_SPLIT_RE = re.compile(r",\s*(?![^()]*\))")
_PAREN_RE = re.compile(r"(.+?)\s*\(([^()]*)\)")


def skills_section(profile_text: str) -> str | None:
    """The body of the profile's ``## Skills`` section, or ``None`` if absent.

    ``None`` (no section) and ``""`` (section present but empty) are DIFFERENT
    answers on purpose: a gate that cannot find the section must be able to say
    so rather than report an empty vocabulary as a clean result.
    """
    match = SKILLS_SECTION_RE.search(profile_text or "")
    return match.group(1) if match else None


def split_items(line: str) -> list[str]:
    """Split a comma-separated skill line, keeping parenthesized groups intact."""
    return [t.strip() for t in _ITEM_SPLIT_RE.split(line) if t.strip()]


def norm_spelling(text: str) -> str:
    """Lowercase + whitespace-collapsed form used to compare skill spellings.

    The same function builds the canonical key set and looks tokens up in it, so
    the two sides of that comparison cannot drift apart.
    """
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def _line_payload(line: str) -> str | None:
    """The item text of one skills line, or ``None`` for a blank/comment line.

    Accepts both ``- Label: a, b`` and a bare ``Label: a, b``; a line that is
    empty after stripping the bullet marker, or that opens a parenthesized
    editorial note, carries no tokens.
    """
    stripped = line.strip().lstrip("-").strip()
    if not stripped or stripped.startswith("("):  # placeholder/comment lines
        return None
    return stripped.split(":", 1)[1] if ":" in stripped else stripped


def parse_skill_lists(profile_text: str) -> tuple[list[str], list[str], list[str]]:
    """``(approved, weak, never)`` skill tokens from the ``## Skills`` section.

    An absent section yields three empty lists; use ``skills_section`` when the
    caller must tell "no section" from "an empty one".
    """
    section = skills_section(profile_text) or ""

    def sub_tokens(header: str) -> list[str]:
        match = re.search(rf"^### {header}\b[^\n]*\n(.*?)(?=^### |\Z)",
                          section, re.M | re.S)
        if not match:
            return []
        tokens: list[str] = []
        for line in match.group(1).splitlines():
            payload = _line_payload(line)
            if payload is not None:
                tokens.extend(split_items(payload))
        return tokens

    approved, weak, never = (sub_tokens(header) for header in SUBSECTION_HEADERS)
    return approved, weak, never


def subsection_bullets(profile_text: str) -> dict[str, list[str]]:
    """Raw ``- ...`` bullet LINES per subsection, verbatim (blocklists included).

    The tailoring card reproduces the Never list verbatim, so it needs the
    original lines rather than split tokens — but it must find the section by
    the same rule as every other reader.
    """
    out: dict[str, list[str]] = {header: [] for header in SUBSECTION_HEADERS}
    section = skills_section(profile_text)
    if section is None:
        return out
    current: str | None = None
    for line in section.splitlines():
        if line.startswith("### "):
            head = line[4:].strip().lower()
            current = next((k for k in out if head.startswith(k.lower())), None)
            continue
        if current and line.lstrip().startswith("- "):
            out[current].append(line.rstrip())
    return out


def expand_keys(token: str) -> set[str]:
    """Normalized spellings a canonical token should recognize.

    A plain token maps to itself; a nested "Base (a, b)" token also recognizes the
    base, each member, and "base member", so a baseline "AWS" or "AWS Lambda" is
    not flagged against a canonical "AWS (Lambda, SQS, SNS)".
    """
    norm = norm_spelling(token)
    if not norm:
        return set()
    keys = {norm}
    match = _PAREN_RE.fullmatch(norm)
    if match:
        base = match.group(1).strip()
        members = [x.strip() for x in re.split(r"[,/]", match.group(2)) if x.strip()]
        if base:
            keys.add(base)
        for member in members:
            keys.add(member)
            if base:
                keys.add(f"{base} {member}")
    return keys


def canonical_keys(profile_text: str) -> set[str]:
    """Every canonical skill spelling in the profile's ``## Skills`` section.

    Collects each bullet token under the section (Approved / Weak / Never
    alike), so the returned set is the full canonical vocabulary.
    """
    section = skills_section(profile_text)
    if section is None:
        return set()
    keys: set[str] = set()
    for line in section.splitlines():
        # Bullets only here (unlike ``parse_skill_lists``): this walks the WHOLE
        # section, subsection headings included, so a stray heading line must not
        # be mistaken for a skill token.
        if not line.strip().startswith("-"):
            continue
        payload = _line_payload(line)
        if payload is None:
            continue
        for token in split_items(payload):
            keys.update(expand_keys(token))
    return keys
