# company-research tells the agent to read reference.md completely, then tells it to read only one section

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: found by the `cr-moat-5whys` and `cr-question-bank` canary runs, 2026-07-30 —
  [the eval record](../../../evals/results/company-research-046a1f17e5f5-20260730-reference-retier.md)
- **Claimed-by**: agent (fix/10-company-research-correctness, 2026-07-31)
## Goal

Make the skill's two instructions about how much of `reference.md` to read agree, so the
task-conditioned pointers do the job they exist to do.

## Context

`skills/company-research/SKILL.md` contains both of these, and both fire on an ordinary
research request:

- § "Acquisition and Output Reference": *"Before live research and before writing outputs, read
  `reference.md` completely."*
- § "Question Bank Guidance": *"**Trigger — drafting the questions themselves:** read ONLY
  `reference.md` § 'Question Bank examples' …"* — and four more pointers of the same shape.

Two independent canary runs reported the contradiction without being asked about it, and both
resolved it the same way: they followed the broader instruction and read all 205 lines. So the
"read ONLY §" triggers currently steer nothing.

**This does not make the retiering wrong.** Its goal was budget headroom — `SKILL.md` was five
lines from a hard 600-line gate that blocks workspace phase 8 — and it delivered 131 lines of
headroom. What it does mean is that the retiering should not be described as a token saving,
because the file is read whole either way. The eval record says so plainly.

The contradiction predates the retiering. What the retiering changed is the stakes: there is
now 145 lines more content behind that blanket instruction than there was.

## What to decide

The two instructions want different things and only one can win per task:

- **Scope the blanket read.** "Before live research, read `reference.md` §§ Sourcing rules and
  Output location" — the parts every run genuinely needs — and let the per-file triggers fetch
  the templates. Cheapest, and it makes the triggers real.
- **Drop the triggers.** Accept that this skill reads its whole reference file and remove the
  "read ONLY §" lines as decoration. Honest, and it costs nothing at runtime.
- **Split `reference.md`.** A small always-read file and a templates file the triggers point
  into. Most faithful to the quickstart-first contract, most churn.

Measure before choosing: `reference.md` is ~13 KB, so reading it whole costs roughly 3.3k
tokens per run. That is the entire size of the prize, and it should be weighed against a
behavioural edit to a skill that currently passes its canaries.

## Definition of done

- [ ] `SKILL.md` gives one answer to "how much of `reference.md` do I read", and the pointers
      that remain are ones an agent can actually act on
- [ ] The eval record's efficiency claim is re-measured against the change, or the change is
      recorded as behaviour-neutral with a rationale
- [ ] company-research canaries pass, recorded in `evals/results/`
