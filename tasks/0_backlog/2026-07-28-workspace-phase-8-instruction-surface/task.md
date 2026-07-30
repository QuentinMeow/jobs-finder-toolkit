# Workspace phase 8 — rewrite the instruction surface and reshape examples/

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Bring AGENTS.md, the skills, the handbook, and the public example dataset in line with
the new layout.

## Context

Detail in [the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) under "Phase 8". `examples/` gets reshaped to mirror
the private tree and to fix its own two violations (`examples/data/` is a generic bucket,
`examples/templates/` collides with the root `templates/`). `examples/data` is one of
`ci.yml`'s 16 executed path pins (`automation/store/validate_store.py examples/data
--check-fixture-size`) — same PR.

**The "8 of 12 `SKILL.md` files" count is stale.** Re-measured 2026-07-29: **all 11 public
`SKILL.md` files** name a path that phase 2 or phase 5 moves. The old count predates both the
`github-workflow` skill and phase 4's removal of the two private skill trees from `skills/`.
Split by which phase does the moving (phase-2 tokens: `automation/maintenance/`, `docs/handbook/`,
`docs/designs/`, `docs/roadmap/`, `tmp/` · phase-5 tokens: `0_profile`, `interviews/`,
`job-search-profiles/`, `data/`):

| Skill | phase 2 | phase 5 |
|---|---:|---:|
| search-recall-audit | 19 | 1 |
| job-search | 15 | 0 |
| gardener | 11 | 0 |
| github-workflow | 7 | 0 |
| behavioral-interview-prep | 2 | 9 |
| ask-me-anything | 3 | 4 |
| company-research | 3 | 1 |
| email-assistant | 3 | 0 |
| resume-writer | 1 | 3 |
| application-tracker | 2 | 0 |
| interview-calendar | 1 | 0 |

The two private skills (`private/skills/coding-interview{,-cleanup}/SKILL.md`) name one each.

**7 handbook docs name `private/`, not 5**: `private-overlay.md` (45 lines),
`public-private-split.md` (9), `repo-map.md` (6), `architecture.md` (4), `command-cookbook.md`
(3), `memory-map.md` (2), `configuration.md` (1).

**Hard blocker, re-measured 2026-07-29 and unchanged:** `skills/company-research/SKILL.md` is at
**595 lines against the hard 600-line budget** in `automation/metrics/instruction_budget.py`,
which `automation/hooks/pre-commit` runs with `--strict`. Five lines of headroom, and this phase
adds path references. The slimming task (`2026-07-28-slim-company-research-skill`) must land
first or this phase cannot commit. `AGENTS.md` itself is at 307 of 500, so there is room there.

This is a "large" edit under the risk-based eval gate — canaries run for **every touched
skill**, recorded in `evals/results/`. Nine of the 11 public skills have a canary set;
`gardener` and `search-recall-audit` have none, so edits to those two are covered by
[`evals/README.md`](../../../evals/README.md)'s recorded-rationale rule, not by a run.

Rule 4 of the execution plan applies: a review-ledger row per commit, plus a closing ledger-only
commit.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phases 2, 4 and 5 merged, and `2026-07-28-slim-company-research-skill` merged. **Partly met as
of 2026-07-29**: phase 4 is merged (PR #86), phases 2 and 5 are not started, and the slimming
task is still in `tasks/0_backlog/`. Three of four preconditions outstanding.

## Definition of done

- [ ] `AGENTS.md` describes the private tree and routes into it
- [ ] All 11 public `SKILL.md` files and 7 handbook docs updated
- [ ] `examples/` mirrors the private tree; `data/` and `templates/` violations fixed;
      `ci.yml`'s `examples/data` pin updated in the same PR
- [ ] ADRs recorded for the layout and any remaining reversals
- [ ] Per-skill canaries pass and are recorded for the 9 skills that have a set; a one-line
      rationale recorded for `gardener` and `search-recall-audit`
- [ ] `instruction_budget.py --strict` clean
- [ ] Review-ledger rows for every commit; branch ends with a ledger-only commit
- [ ] Gate command + export dry-run clean
