# Workspace phase 5 — reorganise private/ by lifetime

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Give the private overlay its me/ · companies/ · applications/ split so durable
knowledge outlives any application.

## Context

Target tree in [the design](../../../design/workspace-restructure/README.md); the full move table is in
[the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 5".

**Three hazards, each verified:**
- Renaming `data/` → `store/` without simultaneously rewriting all **9** ignore patterns
  unignores 82,318 files / 432 MB, incl. 36,465 raw email files. Same commit, mechanical sed.
- `company-levels.yaml` uses 27 YAML anchors and **cannot** be sharded per company.
- `build_tailoring_card.py` derives the story bank from `applications_root().parent` and
  embeds a sha256 of it mirrored in 4 files — move both halves without the phase-0 accessor
  and the card rebuilds with no stories and a still-valid hash.

**~47 of the 518 `interviews/` files are judgment calls, not mechanical moves.** Route each
through the owner; do not guess. Karat is a company (`companies/karat/`), not a vendor —
there is no `vendors/` root.

~300 relative links inside `interviews/` are covered by no checker; fix them here and drop the
`SKIP_PREFIXES` entries that hid them.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phases 0 and 4 merged. Q5 and Q6 answered (rendered artifacts stay in the application folder and only the USER deletes one; handovers are local-only).

## Definition of done

- [ ] `private/{me,companies,applications,market,store,skills,memory,message-queue,tasks,evals,docs,local}/`
- [ ] `git -C private check-ignore` returns IGNORED for a canary list covering all 9 store patterns
- [ ] `config.yaml` `paths.*` re-pointed; every gardener routine runs
- [ ] `status.py` reports the same pipeline as before the move
- [ ] The tailoring card rebuilds **with its stories**; level enrichment exercised
- [ ] The ~47 judgment-call files placed with recorded owner answers
- [ ] Gate command clean
