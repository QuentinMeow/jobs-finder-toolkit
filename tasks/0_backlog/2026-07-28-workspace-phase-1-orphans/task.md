# Workspace phase 1 — retire orphaned folders and files

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Refile the three orphaned items in the private overlay and sweep scratch.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 1". Three items:
`private/todo/tasks/…` (retired by the 2026-07-22 process-folders decision),
`private/email-assistant/reviews/…` (a review living outside the review queue), and the
`tmp/` sweep (102 untracked files).

**Never delete owner data** (`AGENTS.md` guardrail). Anything in `tmp/` that looks like a
captured artifact rather than scratch gets surfaced to the owner, not removed.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phase 0 merged.

## Definition of done

- [ ] `private/todo/` refiled into `private/tasks/0_backlog/` and the empty tree removed
- [ ] The stray email review reformatted to `templates/queue/review.md` and moved into
      `private/message-queue/needs-human/reviews/`
- [ ] `tmp/` swept; anything ambiguous surfaced to the owner rather than deleted
- [ ] Gate command clean
