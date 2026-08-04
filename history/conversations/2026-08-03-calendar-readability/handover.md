# Handover — calendar readability

- **Date**: 2026-08-03
- **Task(s)**: none

## What happened

- Nothing is broken or half-written; publishing is the only remaining step.
- The application-linked calendar now leads with one aligned interview row per occurrence and folds past events, status-heavy company detail, and the raw tracker schedule.
- Transactional calendar generation now reads the prospective calendar rows, so a newly scheduled occurrence appears in the generated view in the same write.
- Behavioral canaries passed for both edited skills, and a second independent readability pass found no blocking issue.

## Where things stand

- Public changes are complete on `codex/calendar-readable-email-refresh`; the matching private-overlay reconciliation is recorded in its own private handover.

## Decisions made for you

- Kept date, time, company, role, and round in separate columns because scanability mattered more than preserving the older company-by-company prose; undoing this is one revert.
- Preserved the complete tracker mechanics behind collapsed details because the owner still needs an auditable machine view; undoing this is one template/render change.
- Kept ambiguous personal evidence out of tracked roles; the private overlay carries the reversible manual fallbacks and owner questions.

## If X then Y

- If an occurrence has the same aggregate round label as sibling blocks, its specific action text distinguishes the preparation row.
- If an event has no confirmed duration, the table shows the start only rather than inventing an end.

## Dead ends

- The generic skill validator rejects this repository's required `visibility` frontmatter; repository-native canaries and gates were used instead.

## Needs your attention

- [Decide whether job-search and draft-time US-only defaults should agree](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md) — **Why this matters:** it is the highest-cost carried-over public question and can repeatedly lose or admit jobs at different pipeline stages. **If you do nothing:** the current asymmetric defaults remain.
- The other carried-over public questions and optional reviews remain in [`message-queue/needs-human/`](../../../message-queue/needs-human/); this session filed no new public ask.
