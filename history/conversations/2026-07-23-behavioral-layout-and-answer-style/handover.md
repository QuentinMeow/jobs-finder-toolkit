# Handover — behavioral layout and answer style

- **Date**: 2026-07-23
- **Task(s)**: none

## What happened

- Consolidated real behavioral products under
  `private/interviews/behavioral/{story-bank,question-bank/}` with `sources/` and `tests/`.
- Replaced the question-answer harness with schema v2: multiple titled project answers, timed
  quick and self-contained combined answers, compact connected STAR paragraphs, impact and
  ownership gates, additive deep dives, and two general-story reference views.
- Made story-bank content read-only unless the user explicitly requests a content change.
- Rewrote and regenerated the Amazon Deliver Results example with the user correction that this
  was on-call ownership, not volunteered work; story-bank text was not changed.
- Updated downstream story-bank callers, rebuilt the tailoring card, and migrated existing
  company-specific behavioral files without changing their content.

## Where things stand

- Deterministic tests, generated-output checks, path tests, reconciliation, vendoring, lints,
  Python compilation, and the public leak guard pass.
- Behavioral canaries pass `4/4` on the public example profile; the result is recorded under
  `evals/results/`.

## Needs your attention

- [Store-projection decision](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  remains parked until its existing stage-3 usage condition is met; no action is needed now.
