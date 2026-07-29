# Workspace phase 3 — build the public-change review gate

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**: agent (session 2026-07-29)

## Goal

Add a test that fails whenever the public tree has commits not yet acknowledged, so
every public change is read for personal data before it ships.

## Context

Full spec in [review-gate.md](../../../design/workspace-restructure/review-gate.md);
phase notes in [the execution plan](../../../design/workspace-restructure/execution-plan.md).

Three files in the public repo: `automation/publish/review_gate.py`,
`automation/publish/review_ledger.yaml` (seeded with current HEAD), and a test. Wired into
`pre-commit` and CI.

**Load-bearing detail:** the ledger must exclude *itself* from the watched diff, or
acknowledging a change is itself a change and the gate never converges.

The advisory company detector is **hints only** — the naive form matches 51 of 177 private
company tokens against the current public tree, led by ordinary English words. Narrow it to
diff-only, baseline-subtracted, display-name matching.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phase 0 merged. Q1 and Q2 answered (watch every tracked public file except the ledger; one row may cover a commit range; an agent may sign its own review, human required only when the detector fires).

## Definition of done

- [ ] A public commit fails the gate with the file list and the instruction
- [ ] Appending a valid ledger row makes it pass
- [ ] A row with a wrong digest still fails
- [ ] The gate is silent when nothing changed
- [ ] Runs in `pre-commit` and in CI
- [ ] Gate command clean
