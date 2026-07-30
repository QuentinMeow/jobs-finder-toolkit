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

- [ ] `instruction_budget.py --strict` reports comfortable headroom (target ≤ 550 lines)
- [ ] No domain edge case lost — moved content is reachable from `reference.md`
- [ ] company-research canaries pass, recorded in `evals/results/`
