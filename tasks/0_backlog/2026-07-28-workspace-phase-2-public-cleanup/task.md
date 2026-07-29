# Workspace phase 2 — split the generic bucket, consolidate docs and evals

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Merge the public tree's duplicate concepts and split its one generic bucket, updating
every path literal in the same PR.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 2". `automation/maintenance/` splits
three ways, `docs/` absorbs `handbook`+`design`+`roadmap`, `evals/` absorbs the measurement
protocols and flattens 8 single-file canary folders, `tmp/` becomes `local/`.

**The trap:** 8 `parents[N]` depth constants under `automation/maintenance/` resolve
`REPO_ROOT` by counting levels and will point at the *parent of the repo* after the move. Fix
them in the same commit; prefer an upward walk for a `.git` marker.

`.github/workflows/ci.yml` pins 12 paths and `pull_request_template.md` pins the gardener
path — same PR.

Consolidating `docs/` reverses a decision recorded in `handbook/file-organization.md`; write
the superseding ADR into `memory/decisions/` as part of this task.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phase 0 merged. Q4 answered (docs consolidation confirmed 2026-07-28).

## Definition of done

- [ ] `automation/{gardener,search-recall-audit,company-levels}/` exist; 8 `parents[N]`
      constants fixed; every gardener routine and the recall audit run
- [ ] `docs/{handbook,designs,roadmap}/` with the `CLAUDE.md → AGENTS.md` shim re-created
- [ ] `evals/{protocols,canaries,rubrics,results}/`; `evals/canaries/<skill>.yaml`
- [ ] `tmp/` → `local/`, `.gitignore` and the scratch rule updated
- [ ] `ci.yml`, `pull_request_template.md`, `ALLOWLIST_DIRS`, `marketplace.json` updated
- [ ] Superseding ADR recorded
- [ ] Gate command + export dry-run + `instruction_budget.py --strict` clean
