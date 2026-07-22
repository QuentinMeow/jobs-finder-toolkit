# Handover — calendar UX revision

- **Date**: 2026-07-22
- **Task(s)**: `2026-07-22-application-progress-calendar`

## What happened

- Rebuilt the calendar presentation around scannable event times, verb-led
  todos, deadlines/follow-ups, role-detail links, and one-line hidden markers.
- Expanded the interview workflow model for assessments, offer decisions,
  follow-ups, pauses, references, and work authorization; refreshed the real
  five-entry calendar without changing application statuses.
- Recorded UX/ATS research and the full transition map in the design family.

## Where things stand

- Implementation and deterministic regression tests are green; the task stays
  in progress only because the behavioral application-tracker canary rerun is a
  mandatory pre-merge gate. Resume-writer also hit its documented unrelated
  LibreOffice PDF flake after 85 other tests passed.

## Needs your attention

- Parked, non-blocking decision: `message-queue/needs-human/decisions/logs-as-store-projections.md`
  remains deferred until the store integration has run for a few weeks.
