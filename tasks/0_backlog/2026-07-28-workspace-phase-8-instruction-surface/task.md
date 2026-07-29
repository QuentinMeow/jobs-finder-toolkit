# Workspace phase 8 — rewrite the instruction surface and reshape examples/

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Bring AGENTS.md, the skills, the handbook, and the public example dataset in line with
the new layout.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 8". 8 of 12 `SKILL.md` files name a
moved path; 5 handbook docs need rewrites; `examples/` gets reshaped to mirror the private
tree and to fix its own two violations (`examples/data/` is a generic bucket,
`examples/templates/` collides with the root `templates/`).

**Hard blocker:** `skills/company-research/SKILL.md` is at 595 lines against a 600-line
pre-commit budget. The slimming task (`2026-07-28-slim-company-research-skill`) must land
first or this phase cannot commit.

This is a "large" edit under the risk-based eval gate — canaries run for **every touched
skill**, recorded in `evals/results/`.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phases 2, 4 and 5 merged, and `2026-07-28-slim-company-research-skill` merged.

## Definition of done

- [ ] `AGENTS.md` describes the private tree and routes into it
- [ ] 8 `SKILL.md` files and 5 handbook docs updated
- [ ] `examples/` mirrors the private tree; `data/` and `templates/` violations fixed
- [ ] ADRs recorded for the layout and any remaining reversals
- [ ] Per-skill canaries pass and are recorded; `instruction_budget.py --strict` clean
- [ ] Gate command + export dry-run clean
