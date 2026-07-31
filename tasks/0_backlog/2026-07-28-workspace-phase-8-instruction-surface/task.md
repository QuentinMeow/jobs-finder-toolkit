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
`docs/designs/`, `docs/roadmap/`, `local/` · phase-5 tokens: `0_profile`, `interviews/`,
`job-search-profiles/`, `data/`):

**The phase-2 column below is obsolete as of 2026-07-29.** Phase 2 ran: it retired the
`automation/maintenance/` token from every skill and re-spelled `handbook|design|roadmap|tmp`, so
those counts describe tokens that no longer exist and the phase-8 estimate built on them
over-states the work. Re-measure before starting — filed as
[`2026-07-29-refresh-phase-8-instruction-surface-counts`](../2026-07-29-refresh-phase-8-instruction-surface-counts/task.md).
The phase-5 column still holds.

| Skill | phase 2 — **obsolete** | phase 5 |
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

The two overlay-only `private/skills/<name>/SKILL.md` files name one each.

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

Phases 2, 4 and 5 merged, and `2026-07-28-slim-company-research-skill` merged. **All four met
as of 2026-07-30, pending merge**: phase 4 is merged (PR #86); phases 2 and 5 are done and in
review; and the slimming landed — `skills/company-research/SKILL.md` is **469 lines against the
600 budget**, 131 of headroom where it had five.

**Phase 5 already absorbed most of the phase-5 column below.** Its rule 2 (the PR that moves a
path updates every literal naming it) meant the migration had to repair every reference the
link checker could see — 126 of them, across `AGENTS.md`, seven handbook docs, five skills, the
eval protocols and both trees' notes — plus the prose and canary YAML the checker cannot see.
**Re-measure before scoping this phase**: what remains is `examples/` and whatever the sweep
missed, not the table's original estimate. The link checker is now the instrument for the part
it can see, and it reports `references: all resolve` today.

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
