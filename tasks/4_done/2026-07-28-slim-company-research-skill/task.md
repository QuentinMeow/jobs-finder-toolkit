# Slim skills/company-research/SKILL.md below the instruction budget

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Get company-research/SKILL.md meaningfully under its 600-line pre-commit budget so
later path rewrites can land.

## Context

It measures **595 of 600** lines (`automation/metrics/instruction_budget.py`), leaving
five lines of headroom. Workspace-restructure phase 8 must add `private/`-tree path references
to it and cannot commit until there is room.

`AGENTS.md` constrains how: harness self-edits are delta-only, never full-file rewrites, and
**consolidation never deletes a domain edge case**. Move detail into the skill's
`reference.md` rather than dropping it.

This is a behavioural edit to a skill — run the company-research canaries and record the
result in `evals/results/`.

## Definition of done

- [x] `instruction_budget.py --strict` reports comfortable headroom (target ≤ 550 lines)
- [x] No domain edge case lost — moved content is reachable from `reference.md`
- [x] company-research canaries pass, recorded in `evals/results/`

**Closed 2026-07-30**, after the work had already merged but the folder was left in
`0_backlog`. Each box was verified from the merged trunk rather than taken on trust:

| Box | Evidence on `main` |
|---|---|
| headroom | `instruction_budget.py` reports `skills/company-research/SKILL.md` at **469** lines against the 600 budget — under the 550 target with 81 lines to spare |
| nothing lost | PR #108 moved five blocks into `reference.md` (206 lines), which the SKILL routes to |
| canaries | `evals/results/company-research-046a1f17e5f5-20260730-reference-retier.md`, recorded by PR #110 |

This mattered beyond tidiness: [workspace phase 8](../../0_backlog/2026-07-28-workspace-phase-8-instruction-surface/task.md)
names this task as a **blocking precondition**, so leaving it in `0_backlog` made phase 8
look blocked when it was not.
