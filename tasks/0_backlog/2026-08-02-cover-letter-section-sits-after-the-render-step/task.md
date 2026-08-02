# resume-writer's cover-letter section sits after Step 6, so a step-ordered run renders too early

- **Priority**: P2 (someday)
- **Area**: resume-writer
- **Source**: split out of `2026-08-01-resume-writer-docs-misstate-what-check-py-enforces` (the
  "Also seen, lower value" paragraph); left open there because it is a restructure, not a
  number correction
- **Claimed-by**:

## Goal

An agent following `skills/resume-writer/SKILL.md`'s numbered steps in order writes every bundled
`..._Application_<job title>.txt` before it renders, so `render.py` produces the cover letters on
the first pass instead of a second one.

## Context

`SKILL.md` orders the Quickstart Step 1 → Step 5.5 → **Step 6 (Render + Validate)** → **"Cover
letters & bundled application `.txt` (one per JD)"** → Step 7. The cover-letter section opens with
"Write the bundle(s) before running `render.py`", which is correct — but it sits *after* the render
step, so an agent reading top to bottom has already rendered by the time it gets there. `render.py`
only emits a role's cover letter when that role's bundle already exists, so the first render
produces a resume and no letters, and the agent spends one of its 1-2 permitted render cycles
(SKILL.md Quickstart, "expect 1-2 render cycles; hard stop at 3") to get them.

The correction is ordering, not content: the section belongs before Step 6, or Step 6 needs a
blocking pre-condition line ahead of the render command. Prefer whichever keeps the numbered steps
readable straight through.

**This is an eval-gated edit.** Moving a section between positions is "restructures or retiers a
file" under `evals/README.md`'s MUST-run list, so `evals/canaries/resume-writer.yaml` runs and is
recorded before it merges. There is already an unclaimed canary-debt task for this skill
(`2026-07-31-resume-writer-canary-run-for-gate-honesty`); one run at head discharges both, since a
gated run covers the accumulated state rather than only its own diff.

## Definition of done

- [ ] The bundle-authoring instruction is reachable before the render command on a straight
      top-to-bottom read of `SKILL.md`.
- [ ] `automation/metrics/instruction_budget.py --strict` still passes (SKILL.md has a 600-line cap).
- [ ] `evals/canaries/resume-writer.yaml` run at head and recorded in `evals/results/`.
