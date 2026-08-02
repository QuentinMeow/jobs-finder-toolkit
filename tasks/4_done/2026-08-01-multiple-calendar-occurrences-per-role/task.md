# Support multiple concurrent calendar occurrences per role

- **Priority**: P1 (this round)
- **Area**: tracker
- **Source**: 2026-08-01 email/application/calendar reconciliation
- **Claimed-by**: Codex `/root`

## Goal

Represent several confirmed interview blocks for one role without overwriting an earlier block or
misclassifying a parallel occurrence as a reschedule.

## Context

Schema v5 stores one scalar `jobs[].progress.calendar_item`, and the local calendar validator assumes
a strict one-role-to-one-entry relationship. A role can legitimately have several confirmed future
blocks. The current safe guard refuses a second different start time, which prevents silent data
loss but cannot represent the valid schedule.

The durable design should separate per-occurrence lifecycle from aggregate role progress. A likely
direction is a schema migration to ordered `calendar_items`, explicit add/reschedule/cancel occurrence
commands, and a deterministic reducer that leaves the role scheduled while any expected future
occurrence remains.

## Definition of done

- Add a schema migration that preserves every existing scalar calendar link.
- Add explicit entry-targeted commands for parallel occurrence creation, reschedule, cancellation,
  completion, and Outlook-event linkage.
- Define and test the reducer from occurrence lifecycle to role `progress.state`.
- Validate duplicate-free, idempotent local and Outlook reconciliation for multiple future blocks.
