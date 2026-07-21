# Steer drafting agents off full-file `reference.md`/`check.py` reads on the routine path

- **Status**: todo
- **Priority**: P0
- **Area**: resume-writer
- **Source**: `evals/results/stage1-benchmark-20260720.md:51-53`;
  `evals/results/stage2-benchmark-20260720.md:86-87`;
  `evals/results/stage3-benchmark-20260720.md:36-38`

## Goal

Get drafting agents to actually stay inside the tiered Quickstart on the routine
tailoring path — reading `reference.md` and the `check.py` validator source only
via the documented triggers — instead of discretionarily reading both files
nearly in full, which currently costs ~59-70 KB per agent, every pinned benchmark
row since instruction tiering shipped.

**This is currently being actively worked on as part of the ongoing token-usage
optimization round; this file exists to track it for continuity across sessions,
not to introduce a new finding.**

## Context

`.agents/skills/resume-writer/SKILL.md`'s Quickstart is explicitly framed as "the
**complete routine path**... a routine run needs **nothing below this
Quickstart** and **no file beyond the tailoring card**" (SKILL.md line ~18-19),
and it lists specific triggers under which the full `reference.md` /
`check.py`/validator source should be opened (SKILL.md line ~97: "Open the full
documents ONLY on one of these triggers"). This trigger-gated structure already
shipped as part of Stage 2 instruction tiering and measurably cut boot-time
instruction bytes (~55% smaller at boot per the Stage-2 self-audit). Despite that,
three separate pinned benchmark rows (Stage 1, Stage 2, Stage 3 — one per stage of
the token-usage-modes program) recorded the same residual pattern: the drafting
leg chose to read the reference tier plus the validator source close to in full,
rather than following only the listed triggers. The Stage-2 row calls this "the
standing discretionary-read pattern" and names "quickstart wording could steer
agents away from full-file reads... on the routine path" as the still-open
follow-up; the Stage-3 row repeats it near-verbatim as "quickstart steering
remains the known follow-up."

The existing trigger list redirects reading but does not structurally prevent a
curious agent from opening the full files anyway — the gap is in how strongly the
Quickstart discourages that read, not in whether the tiered structure exists.

Relevant files:
- `.agents/skills/resume-writer/SKILL.md` (Quickstart section, the
  "open the full documents only on one of these triggers" language)
- `.agents/skills/resume-writer/reference.md` (the ~59-70 KB file being read in
  full)
- `.agents/skills/resume-writer/scripts/check.py` (the validator source being
  read in full)
- `docs/design/token-usage-modes/` (the program tracking this optimization round)

## Definition of done

- A revised Quickstart wording (or structural change, e.g. a stronger warning, a
  cost estimate inline, or narrowing what triggers actually require) measurably
  reduces full-file `reference.md`/`check.py` reads on a routine-path drafting run
  under a follow-up pinned benchmark row, without regressing the existing canary
  gate (`evals/resume-writer/canaries.yaml`, full suite pass).
- The next `evals/results/*.md` benchmark row that measures a drafting leg no
  longer lists this as a follow-up (or reports a materially smaller residual byte
  count with an explanation of what remains).
