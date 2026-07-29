# Workspace phase 1 — retire orphaned folders and files

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Refile the two orphaned items in the private overlay and sweep scratch.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 1". Three items:
`private/todo/tasks/…` (retired by the 2026-07-22 process-folders decision),
`private/email-assistant/reviews/…` (a review living outside the review queue), and the
`tmp/` sweep. Both orphans were still present on 2026-07-29; `tmp/` holds 102 untracked files
across 20 purpose folders.

**Never delete owner data** (`AGENTS.md` guardrail). Anything in `tmp/` that looks like a
captured artifact rather than scratch gets surfaced to the owner, not removed.

**This phase's public half is empty.** Both refiles happen inside the private overlay, so there
is nothing for the public review gate to acknowledge — do not manufacture a public commit just
to add a ledger row. If a public file does change, rule 4 of the execution plan applies in full:
one row in `automation/publish/review_ledger.yaml` per commit, plus a closing ledger-only commit
so the branch lands green. `automation/publish/review_gate.py` prints the row for you.

**Coming after you:** phase 2 renames `tmp/` → `local/`. Sweeping `tmp/` now is not wasted work,
but do not build anything that hardcodes the `tmp/` name.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

None outstanding — phase 0 merged 2026-07-29 (PRs #81–#84, commits `72d45e2`…`eb345e7`). This
phase is ready to start.

## Definition of done

- [ ] `private/todo/` refiled into `private/tasks/0_backlog/` and the empty tree removed
- [ ] The stray email review reformatted to `templates/queue/review.md` and moved into
      `private/message-queue/needs-human/reviews/`
- [ ] `tmp/` swept; anything ambiguous surfaced to the owner rather than deleted
- [ ] Gate command clean
