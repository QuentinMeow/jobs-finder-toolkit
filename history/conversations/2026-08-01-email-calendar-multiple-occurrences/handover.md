# Handover — email-calendar-multiple-occurrences

- **Date**: 2026-08-01
- **Task(s)**: `2026-08-01-multiple-calendar-occurrences-per-role`

## What happened

- Replaced the one-calendar-link role model with schema v6's ordered `calendar_items` list, added a
  transactional v5-to-v6 migration, and updated public fixtures and writers.
- Added occurrence-targeted create, reschedule, cancel, complete, and remote-event-link operations,
  plus a deterministic reducer from occurrence state to aggregate role progress.
- Added regressions and Sol-high canaries for several independent interview blocks, including two
  occurrences on the same day.

## Where things stand

- The implementation is ready for public review after the rebased regression suites and repository
  gates pass.
- Application-tracker and interview-calendar canary results are recorded with content pins in
  `evals/results/`.

## Needs your attention

- Nothing.
