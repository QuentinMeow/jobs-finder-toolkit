# Worklog — 2026-08-07-calendar-identity-refresh

## 2026-08-07 — session 1 (Codex)

- Updated existing calendar occurrences to take application slug and role from current metadata during a progress change.
- Corrected generated-text detection to compare against the occurrence's prior role, preserving genuinely owner-authored text.
- Added a regression test and passed the full progress/calendar test module.
