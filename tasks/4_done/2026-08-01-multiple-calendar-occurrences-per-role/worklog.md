# Worklog — 2026-08-01-multiple-calendar-occurrences-per-role

## 2026-08-01 — session 1 (Codex)

- Found the scalar-link limitation during a mailbox/calendar reconciliation. Added a fail-closed
  guard that prevents a later confirmed start from overwriting an existing occurrence, plus focused
  regression coverage. The schema migration and aggregate occurrence model remain.

## 2026-08-01 — session 2 (Codex `/root`)

- Implemented schema v6 with an ordered, unique `progress.calendar_items` list and a
  formatting-preserving, transactional v5→v6 migration, then refreshed every public fixture and
  writer.
- Added parallel occurrence creation (`--add-occurrence`), explicit occurrence targeting
  (`--calendar-item`), occurrence-local reschedule/cancellation/completion handling, and an
  aggregate reducer that stays scheduled while any future block remains.
- Fixed last-write-wins behavior in email/calendar proposal grouping and added the three-block,
  two-day end-to-end regression. Shared (621), tracker (119), and email (90) suites pass; the sole
  job-search failure was a stale schema-v5 fixture assertion and its corrected regression passes.
- Recorded fresh Sol-high canary runs: application-tracker passed 7/7 and interview-calendar
  passed 5/5. The repaired full job-search suite also passed, and the canary records were adapted
  to the content-pin format introduced on the latest `main`.
- Rebased the stack onto the latest `main`, refreshed the stale generated company-view block in the
  public example calendar, and reran the affected regression suites and repository gates.
