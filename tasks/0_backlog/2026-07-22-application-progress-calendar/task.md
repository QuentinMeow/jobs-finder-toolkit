# Add structured application progress and one calendar todo file

- **Priority**: P1 (next email round)
- **Area**: tracker
- **Source**: `docs/design/application-progress-calendar/execution-plan.md` Stage 2

## Goal

Make hiring phase, booking/waiting/scheduled/reschedule state, and exact
interview schedules first-class without changing the coarse status-folder
pipeline.

## Context

Implement schema v5 from
`docs/design/application-progress-calendar/README.md`: keep
`jobs[].status`, replace free-text-only `stage` with structured
`jobs[].progress`, and add the single private `calendar.md` resolved by
`config.calendar_path()`. The tracker is the only writer that updates
metadata and calendar together.

The calendar must preserve unmarked human notes, stable entry IDs,
checkboxes, exact time/timezone, follow-up dates, and append-only
reschedule history. A past wall-clock time never implies completion.

## Definition of done

- Preview-first, formatting-preserving v4→v5 migration passes fleet and
  synthetic tests; v5 becomes the only accepted schema after cutover.
- `status.py --update-progress`, `--check-calendar`, and preview-first
  `--sync-calendar` implement the designed states and preserve manual text.
- Progress-only changes never move application folders; existing status
  rollup tests remain green.
- Scheduled entries require explicit time + timezone; malformed markers,
  duplicate IDs, checksum races, and one-sided writes fail closed.
- A reschedule fixture keeps the old occurrence as `superseded` and appends
  the confirmed replacement.
- `filter_jobs.py` can filter phase and progress state; pipeline health
  surfaces action-needed and overdue-waiting items.
