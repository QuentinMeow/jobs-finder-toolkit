#!/usr/bin/env python3
"""Validate a PR body against this repo's human-facing PR-description format.

The format (see ``skills/github-workflow/SKILL.md``): a PR description OPENS with
a section written for the person who will use the thing, in plain English, before
any technical detail. Three mechanical properties of that rule are checkable, and
this script checks exactly those three:

  1. ``human-first-section`` — the FIRST level-2 (``##``) heading is the
     human-facing one ("## What changes for you"). A body that opens with
     "## Summary" or "## What & why" has buried the reader-facing part.
  2. ``before-after`` — that first section contains at least one ``**Before.**``
     and at least one ``**After.**`` marker. Without the pair, the section
     describes the new state without saying what it replaced.
  3. ``marketing-words`` — no word from ``BANNED_TERMS`` appears anywhere in the
     body. Those words describe how the author feels about the change instead of
     what it does.

Everything else the format asks for ("say plainly when something gets slower",
short sentences, naming the real command) is a judgment call and is deliberately
NOT enforced here: a checker that guesses at those would either pass bad bodies or
fail good ones. This script is a floor, not a review.

Fenced code blocks are skipped for every check, and inline code spans are skipped
for the marketing-word check, so pasted terminal output, example markdown, and a
sentence that *names* a banned word (`` `seamless` ``) cannot trip a finding.

Stdlib only, and it imports nothing from the repo root — a skill's ``scripts/``
may never import repo-root Python (``docs/handbook/skills-and-vendoring.md``).

Usage:
    .venv/bin/python skills/github-workflow/scripts/check_pr_body.py body.md
    gh pr view 42 --json body --jq .body | \
        .venv/bin/python skills/github-workflow/scripts/check_pr_body.py

Exit codes:
    0  the body satisfies the format
    1  one or more findings (each printed with its location)
    2  usage / IO problem (unreadable file, empty input)
"""
from __future__ import annotations

import argparse
import re
import sys

# Words that describe enthusiasm rather than behavior. Edit this list here — it is
# the one definition, and SKILL.md points at it rather than repeating it.
BANNED_TERMS = (
    "leverage", "leverages", "leveraged", "leveraging",
    "seamless", "seamlessly",
    "robust", "robustly",
    "effortless", "effortlessly",
    "blazing fast", "blazingly fast",
    "game changer", "game changing",
    "revolutionary", "revolutionize", "revolutionizes",
    "cutting edge", "state of the art", "best in class", "world class",
    "supercharge", "supercharges", "supercharged",
    "delightful", "magical", "magically",
    "powerful", "powerhouse",
    "unparalleled", "unmatched",
    "turnkey", "frictionless",
)

# The canonical opening heading, and what else counts as it. A heading passes when
# it reads as addressed to the user — "## What changes for you", "## What's
# different for you", "## What changes". Anything else (Summary, Overview,
# What & why, Motivation) is a technical heading and must come later.
CANONICAL_HEADING = "## What changes for you"
HUMAN_HEADING_RE = re.compile(r"\bfor you\b|\bwhat changes\b", re.IGNORECASE)

# ``## Heading`` — level 2 exactly. ``#`` (a title) and ``###`` (a sub-heading
# inside the human section, e.g. one per change) are not section boundaries.
H2_RE = re.compile(r"^##(?!#)\s*(.*?)\s*$")

BEFORE_RE = re.compile(r"\*\*\s*Before\s*[.:]?\s*\*\*", re.IGNORECASE)
AFTER_RE = re.compile(r"\*\*\s*After\s*[.:]?\s*\*\*", re.IGNORECASE)

FENCE_RE = re.compile(r"^\s*(```|~~~)")

# ``code`` / `code` — quoted text, not the author's prose. Removed before the
# marketing scan so a body may name a banned word by backticking it.
INLINE_CODE_RE = re.compile(r"``[^`]+``|`[^`]+`")


def _term_pattern(term: str) -> re.Pattern:
    """Word-boundary matcher for a term, tolerant of spaces vs hyphens.

    "cutting edge" must also catch "cutting-edge"; "game changing" must catch
    "game-changing". Single words are unaffected.
    """
    parts = [re.escape(w) for w in re.split(r"[\s\-]+", term) if w]
    return re.compile(r"\b" + r"[\s\-]+".join(parts) + r"\b", re.IGNORECASE)


BANNED_PATTERNS = tuple((term, _term_pattern(term)) for term in BANNED_TERMS)


def prose_lines(body: str) -> list[tuple[int, str]]:
    """``(1-based line number, text)`` for every line outside a fenced block.

    Fences are skipped so a pasted CI log or an example PR body inside ``` cannot
    produce a finding — the format governs the author's prose, not quoted output.
    """
    out: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    for lineno, line in enumerate(body.splitlines(), start=1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            continue
        if not in_fence:
            out.append((lineno, line))
    return out


def _first_section(lines: list[tuple[int, str]]):
    """Return ``(heading_lineno, heading_text, section_lines)`` or None.

    The section runs from the first ``##`` heading to the next ``##`` heading (or
    the end of the body).
    """
    start = None
    heading = ""
    for idx, (lineno, text) in enumerate(lines):
        match = H2_RE.match(text)
        if match:
            start, heading = idx, match.group(1)
            break
    if start is None:
        return None
    body_lines = []
    for lineno, text in lines[start + 1:]:
        if H2_RE.match(text):
            break
        body_lines.append((lineno, text))
    return lines[start][0], heading, body_lines


def check(body: str) -> list[tuple[str, str]]:
    """Return ``(location, message)`` findings. Empty means the body passes."""
    findings: list[tuple[str, str]] = []
    lines = prose_lines(body)
    section = _first_section(lines)

    if section is None:
        findings.append((
            "whole body",
            f"no `##` heading found — the body must open with the human-facing "
            f"section, e.g. `{CANONICAL_HEADING}`",
        ))
    else:
        heading_lineno, heading, section_lines = section
        if not HUMAN_HEADING_RE.search(heading):
            findings.append((
                f"line {heading_lineno}",
                f"first `##` heading is \"## {heading}\" — the body must open with "
                f"the human-facing section (`{CANONICAL_HEADING}`); technical "
                f"sections come after it",
            ))
        if not any(BEFORE_RE.search(text) for _, text in section_lines):
            findings.append((
                f"section \"## {heading}\"",
                "no `**Before.**` marker — each change states, in concrete terms, "
                "what happened before it",
            ))
        if not any(AFTER_RE.search(text) for _, text in section_lines):
            findings.append((
                f"section \"## {heading}\"",
                "no `**After.**` marker — each change states what happens now",
            ))

    for lineno, text in lines:
        prose = INLINE_CODE_RE.sub(" ", text)
        for term, pattern in BANNED_PATTERNS:
            found = pattern.search(prose)
            if found:
                findings.append((
                    f"line {lineno}",
                    f"marketing word {found.group(0)!r} — name the actual command, "
                    f"file, or behaviour instead",
                ))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Validate a PR body against the human-facing PR-description "
                     "format: the first `##` heading is the human-facing one, it "
                     "carries at least one **Before.** and one **After.**, and the "
                     "body uses no marketing words."),
        epilog=("Reads FILE, or stdin when FILE is omitted or `-`. "
                "Exit 0 = passes, 1 = findings, 2 = usage/IO problem."),
    )
    parser.add_argument(
        "file", nargs="?", default="-",
        help="path to a file holding the PR body (default: read stdin)",
    )
    parser.add_argument(
        "--list-banned", action="store_true",
        help="print the banned marketing words and exit",
    )
    args = parser.parse_args(argv)

    if args.list_banned:
        for term in BANNED_TERMS:
            print(term)
        return 0

    if args.file == "-":
        body = sys.stdin.read()
        source = "<stdin>"
    else:
        try:
            with open(args.file, encoding="utf-8") as handle:
                body = handle.read()
        except OSError as exc:
            print(f"check_pr_body.py: cannot read {args.file}: {exc}", file=sys.stderr)
            return 2
        source = args.file

    if not body.strip():
        print(f"check_pr_body.py: {source} is empty — nothing to check", file=sys.stderr)
        return 2

    findings = check(body)
    if not findings:
        print(f"check_pr_body.py: OK — {source} follows the human-facing PR format")
        return 0

    print(f"check_pr_body.py: FAIL — {len(findings)} finding(s) in {source}",
          file=sys.stderr)
    for location, message in findings:
        print(f"  {location}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
