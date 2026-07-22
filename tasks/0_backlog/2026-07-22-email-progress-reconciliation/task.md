# Categorize email and reconcile application progress plus interview schedules

- **Priority**: P1 (after progress/calendar and email sync)
- **Area**: email
- **Source**: `design/application-progress-calendar/execution-plan.md` Stages 4–5

## Goal

Turn new job-related messages into guarded progress and calendar proposals,
then prove store-first review before replacing repeated live mailbox reads.

## Context

Implement deterministic categories, the company→application→role
association ladder, by-application reverse indexes, and unresolved /
needs-reply / deadline queues. Add the scheduling evidence mapping for:

- booking required;
- availability or booking submitted, awaiting a schedule;
- confirmed interview date/time/timezone;
- employer- or owner-initiated rescheduling;
- replacement confirmation with the old time preserved;
- cancellation without an inferred rejection;
- interview complete, awaiting result.

Email is evidence, not authority. Every write re-opens the exact stored
message, requires one unambiguous role, respects evidence scope and link
derivation, and commits `meta.yaml` plus `calendar.md` transactionally.
Attachment-only or weak thread evidence routes to triage.

## Definition of done

- Wrong-role, shared-ATS-domain, bare-number, drifting-thread, and ambiguous
  multi-role fixtures cannot change progress or calendar state.
- Sent availability maps to `awaiting_schedule`; an explicit confirmation
  maps to `scheduled`; a confirmed replacement preserves the superseded
  occurrence.
- A scheduling cancellation never changes coarse status unless the same
  exact message explicitly and unambiguously closes the role.
- Metadata and calendar either both commit or neither does; all transitions
  name their neutral message evidence.
- Store-first and live review run on the same intersection until five
  consecutive zero-mismatch runs and at least 300 job-related messages;
  the measured token/latency result is recorded before cutover.
- Draft-only, pre-draft Sent/Drafts checks, store staleness, and leak guards
  remain green after cutover.
