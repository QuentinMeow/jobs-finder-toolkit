#!/usr/bin/env python3
"""Validate a PR body against this repo's human-facing PR-description format.

The format (see ``skills/github-workflow/SKILL.md``): a PR description OPENS with
a section written for the person who will use the thing, in plain English, before
any technical detail. Three mechanical properties of that rule are checkable, and
this script checks exactly those three (plus a fourth property, below, that is only
evaluated when the caller supplies the diff):

  1. ``human-first-section`` — the FIRST level-2 (``##``) heading is the
     human-facing one ("## What changes for you"). A body that opens with
     "## Summary" or "## What & why" has buried the reader-facing part.
  2. ``before-after`` — that first section contains at least one ``**Before.**``
     and at least one ``**After.**`` marker. Without the pair, the section
     describes the new state without saying what it replaced.
  3. ``marketing-words`` — no word from ``BANNED_TERMS`` appears anywhere in the
     body. Those words describe how the author feels about the change instead of
     what it does.

The fourth property needs to know what the PR changed, so it runs only when
``--changed-files`` names a file holding the diff's paths (``git diff --name-only``):

  4. ``eval-gate`` — a PR whose diff touches ``skills/*/{SKILL,LESSONS,reference}.md``
     must DISCHARGE the risk-based eval gate (``AGENTS.md`` → Guardrails,
     ``evals/README.md``) in its body, in one of three ways:
       * **ran** — the body names a recorded run under ``evals/results/``, or carries
         an ``Eval gate: ran — …`` line that says what ran and how it went;
       * **skipped** — an ``Eval gate: skipped — <intention + size>`` line whose
         rationale is actually written. The unfilled template placeholder (the
         angle-bracket text itself) does not count as a rationale;
       * **debt** — an ``Eval gate: debt — …`` line PLUS a ``tasks/0_backlog/`` item
         named in the body and added by this same diff. Pre-merge canary discharge
         is not always reachable at batch size (one measured canary run cost a whole
         session), so the gate accepts TRACKED debt — but only tracked: a debt line
         with no backlog item in the diff is the undischarged case, not a third way
         of saying "skipped".
     Anything else is a finding. The gate was already a hard rule in ``AGENTS.md``
     and in ``evals/README.md``; nothing read the body, so a behavioral edit could
     merge with the gate neither run, skipped, nor owed.

     The verdict line is read with its inline code spans BLANKED (the same rule the
     marketing check uses), so a rationale may name a skill, a canary id or a file
     in backticks and still be judged on its prose. What it may NOT do is live
     entirely inside a span: quoting the form of the line is what every checklist
     item in ``.github/pull_request_template.md`` does, and a template nobody filled
     in must not discharge anything. Inside a fenced block the line is read
     verbatim, because a pasted canary table is evidence rather than prose. The
     ``evals/results/`` record and the ``tasks/0_backlog/`` item are matched against
     the raw body — those are identifiers, and everybody writes a path in code.

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
    # the eval-gate property alone, the way CI runs it:
    git diff --name-only "$(git merge-base BASE HEAD)" HEAD > changed.txt
    .venv/bin/python skills/github-workflow/scripts/check_pr_body.py body.md \
        --changed-files changed.txt --eval-gate-only

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


# ── the eval gate (property 4) ───────────────────────────────────────────────
# The three instruction files AGENTS.md's risk-based eval gate names. A diff that
# touches one of them is a harness edit, and the PR body has to say what happened
# to the gate.
SKILL_INSTRUCTION_RE = re.compile(r"^skills/[^/]+/(?:SKILL|LESSONS|reference)\.md$")

# ``Eval gate: <verdict> …`` anywhere on a line. Bold, a list bullet, or a table
# cell around it are all tolerated — the line is evidence, not prose to police.
# The remainder runs to end of line; ``_eval_gate_lines`` decides WHICH text the
# line is read from, and that is where the backtick rule lives.
EVAL_GATE_RE = re.compile(r"Eval\s+gate\s*\**\s*:\s*\**\s*(.*)$", re.IGNORECASE)

# A recorded run (evals/README.md: "A run is recorded … in `evals/results/`").
EVAL_RECORD_RE = re.compile(r"evals/results/[\w.@+-]+\.md")

_RAN_RE = re.compile(r"^(?:ran|run|pass(?:ed|es)?)\b", re.IGNORECASE)
_SKIPPED_RE = re.compile(r"^skip(?:ped)?\b", re.IGNORECASE)
_DEBT_RE = re.compile(r"^debt\b", re.IGNORECASE)

# A backlog item named in the body. The gate then checks the DIFF for it.
BACKLOG_ITEM_RE = re.compile(r"tasks/0_backlog/[\w.@+/-]+")

# ``<intention + size>`` and friends — an unfilled placeholder is not a rationale.
PLACEHOLDER_RE = re.compile(r"<[^>\n]*>")
MIN_RATIONALE_WORDS = 3

_ACCEPTED_FORMS = (
    "either paste/name a canary run (a path under `evals/results/`, or "
    "`Eval gate: ran — <what ran, how it went>`), or write "
    "`Eval gate: skipped — <intention + size>` with the rationale actually filled "
    "in, or declare tracked debt (`Eval gate: debt — …`) and add the "
    "`tasks/0_backlog/` item you name in the SAME diff"
)


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


def _verdict_rest(text: str) -> str:
    """What follows the verdict word: ``skipped — a typo`` -> ``a typo``."""
    rest = re.sub(r"^[A-Za-z]+", "", text.strip(), count=1)
    return rest.lstrip(" \t—–-:.").strip()


def _has_substance(text: str) -> bool:
    """True when real words remain after the `<placeholder>` spans are removed.

    ``<intention + size>`` collapses to nothing; so do ``N/A`` and ``TBD``, which
    are the other two ways of writing "I did not answer this".
    """
    words = [w for w in re.split(r"[^\w']+", PLACEHOLDER_RE.sub(" ", text)) if w]
    return len(words) >= MIN_RATIONALE_WORDS


def _eval_gate_lines(body: str) -> tuple[list[tuple[str, bool]], bool]:
    """``([(remainder, code_was_removed)], a_line_was_quoted_away)``.

    Which TEXT of a line the verdict is read from, which is the whole subtlety of
    this property:

    * inside a fenced block the line is read verbatim — a pasted canary table is
      evidence, and blanking code there would blank the evidence;
    * outside one, inline code spans are blanked FIRST, exactly as the
      marketing-word check does. Backticks mark quoted text, so a line that quotes
      the FORM of the discharge — which every checklist item in
      .github/pull_request_template.md does, for all three forms — leaves nothing
      behind and cannot pass as a filled-in one.

    Blanking rather than truncating is what makes an ordinary sentence work: a
    rationale that NAMES something in code (``ran — the four `github-workflow`
    canaries, 4/4 pass``) is judged on the words either side of the span, not on
    the two words before it. The second return value flags a line whose only
    ``Eval gate:`` text was inside a span, so the finding can say so instead of
    reporting an empty rationale.
    """
    found: list[tuple[str, bool]] = []
    quoted_away = False
    in_fence = False
    fence_marker = ""
    for line in body.splitlines():
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            continue
        scanned = line if in_fence else INLINE_CODE_RE.sub(" ", line)
        match = EVAL_GATE_RE.search(scanned)
        if match:
            found.append((match.group(1).strip(), scanned != line))
        elif not in_fence and EVAL_GATE_RE.search(line):
            quoted_away = True
    return found, quoted_away


def _named_backlog_items(body: str, changed_files: list[str]):
    """``(named_in_body, present_in_diff)`` for ``tasks/0_backlog/`` paths.

    A body may name the item's folder or its ``task.md``; both count, as long as
    the diff adds something under the path that was named.
    """
    named = [token.rstrip("/.,;:)`") for token in BACKLOG_ITEM_RE.findall(body)]
    present = [path for path in changed_files
               for token in named
               if path == token or path.startswith(token + "/")]
    return named, present


def check_eval_gate(body: str, changed_files: list[str]) -> list[tuple[str, str]]:
    """Findings for the risk-based eval gate. Empty when it does not apply.

    Reads the WHOLE body, fences included: a pasted canary table is evidence, and
    the format's fence exemption exists to protect quoted output from the PROSE
    checks, not to hide the one line this property is looking for.
    """
    touched = sorted({p for p in changed_files if SKILL_INSTRUCTION_RE.match(p)})
    if not touched:
        return []

    shown = ", ".join(touched[:3])
    if len(touched) > 3:
        shown += f" (+{len(touched) - 3} more)"
    location = "eval gate"

    verdicts, quoted_away = _eval_gate_lines(body)
    ran = [(_verdict_rest(v), coded) for v, coded in verdicts if _RAN_RE.match(v)]
    skipped = [(_verdict_rest(v), coded) for v, coded in verdicts
               if _SKIPPED_RE.match(v)]
    debts = [v for v, _ in verdicts if _DEBT_RE.match(v)]

    # The record path and the backlog item are read from the RAW body, backticks
    # and all: those are identifiers, and naming one in code is how everybody
    # writes a path. Only the author's own verdict sentence is subject to the
    # quoted-text rule above.
    #
    # 1. a run: a recorded result file, or a line that says what ran.
    if EVAL_RECORD_RE.search(body) or any(_has_substance(r) for r, _ in ran):
        return []
    # 2. a skip whose rationale is written, not the template's placeholder.
    if any(_has_substance(s) for s, _ in skipped):
        return []
    # 3. tracked debt: the declaration AND the backlog item, in this diff.
    named, present = _named_backlog_items(body, changed_files)
    if debts and present:
        return []

    head = (f"this diff touches {shown}, so the risk-based eval gate "
            f"(AGENTS.md → Guardrails, evals/README.md) has to be discharged in "
            f"the body — ")
    # Never report an empty rationale when the rationale was written in code: that
    # is the one wrong answer this check can give, because the author is looking at
    # words the finding says are not there.
    code_note = (". The words inside `backticks` were read as a quotation and left "
                 "out — name what you like in code, but keep the rationale itself "
                 "in plain prose")
    if debts and named:
        return [(location, head + "the `Eval gate: debt` line names "
                 f"{named[0]}, but this diff adds nothing under it. Tracked debt "
                 "means the backlog item lands with the PR that owes it")]
    if debts:
        return [(location, head + "the `Eval gate: debt` line names no "
                 "`tasks/0_backlog/` item. Debt that is not filed is a skip "
                 "without a rationale")]
    if skipped:
        return [(location, head + "the `Eval gate: skipped` rationale is empty or "
                 "still the template placeholder. Say what the edit was and how "
                 "big it was"
                 + (code_note if any(coded for _, coded in skipped) else ""))]
    if ran:
        return [(location, head + "the `Eval gate: ran` line does not say what ran "
                 "or how it went, and no `evals/results/` record is named"
                 + (code_note if any(coded for _, coded in ran) else ""))]
    if quoted_away:
        return [(location, head + "the only `Eval gate:` text in the body is inside "
                 "an inline code span, which reads as quoting the FORM of the line "
                 "— which is what .github/pull_request_template.md does. Write the "
                 "line as ordinary prose, outside backticks")]
    return [(location, head + _ACCEPTED_FORMS)]


def check(body: str, changed_files: list[str] | None = None) -> list[tuple[str, str]]:
    """Return ``(location, message)`` findings. Empty means the body passes.

    ``changed_files`` is the diff's paths (``git diff --name-only``). Without it
    the eval-gate property cannot be evaluated and is skipped — a body checked on
    its own is checked for the three format properties, exactly as before.
    """
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

    if changed_files is not None:
        findings.extend(check_eval_gate(body, changed_files))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Validate a PR body against the human-facing PR-description "
                     "format: the first `##` heading is the human-facing one, it "
                     "carries at least one **Before.** and one **After.**, and the "
                     "body uses no marketing words. With --changed-files it also "
                     "checks that a diff touching "
                     "skills/*/{SKILL,LESSONS,reference}.md discharges the "
                     "risk-based eval gate (ran / skipped-with-rationale / tracked "
                     "debt)."),
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
    parser.add_argument(
        "--changed-files", metavar="PATH", default=None,
        help="file holding the diff's paths, one per line (`git diff --name-only`). "
             "Enables the eval-gate property; without it that property is skipped",
    )
    parser.add_argument(
        "--eval-gate-only", action="store_true",
        help="check ONLY the eval-gate property, not the three format properties "
             "(what CI runs against a PR body). Requires --changed-files",
    )
    args = parser.parse_args(argv)

    if args.list_banned:
        for term in BANNED_TERMS:
            print(term)
        return 0

    if args.eval_gate_only and args.changed_files is None:
        parser.error("--eval-gate-only needs --changed-files: the eval gate is "
                     "decided by what the diff touched, not by the body alone")

    changed: list[str] | None = None
    if args.changed_files is not None:
        try:
            with open(args.changed_files, encoding="utf-8") as handle:
                changed = [line.strip() for line in handle if line.strip()]
        except OSError as exc:
            print(f"check_pr_body.py: cannot read {args.changed_files}: {exc}",
                  file=sys.stderr)
            return 2

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

    # An empty body is a usage problem when the body is all there is to judge. Once
    # the DIFF is known it is a verdict instead: an empty body discharges no eval
    # gate, and it passes when the diff touched no skill-instruction file.
    if not body.strip() and changed is None:
        print(f"check_pr_body.py: {source} is empty — nothing to check", file=sys.stderr)
        return 2

    if args.eval_gate_only:
        findings = check_eval_gate(body, changed)
        scope = "discharges the eval gate"
    else:
        findings = check(body, changed)
        scope = "follows the human-facing PR format"
        if changed is not None:
            scope += " and discharges the eval gate"
    if not findings:
        print(f"check_pr_body.py: OK — {source} {scope}")
        return 0

    print(f"check_pr_body.py: FAIL — {len(findings)} finding(s) in {source}",
          file=sys.stderr)
    for location, message in findings:
        print(f"  {location}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
