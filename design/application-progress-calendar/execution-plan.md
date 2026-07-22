# Execution plan — application progress, interview scheduling, and calendar todos

**Status:** planned on 2026-07-22; no implementation has started. The data
model and safety rules live in [README.md](README.md). Delivery stays in
small, independently green changes; the first two stages are prerequisites
that may be built in either order, while reconciliation waits for both.

## Stage 1 — email provider contract and conformance

Implement the provider boundary already specified in
[the raw-data-layer provider design](../raw-data-layer/03-provider-interfaces.md):
relocate Outlook behavior without changing it, add the audited transport
and per-provider route allowlist, replace fixed-file safety checks with a
folder-walking checker, update pre-commit paths, and rename the skill to
`email-assistant` with no alias.

**Acceptance:** every existing Outlook draft-only test passes; synthetic
provider conformance passes; a planted send-capable provider fixture fails
the checker; one explicitly requested read-only live run passes. This stage
does not download a mailbox or change application metadata.

Task: `tasks/0_backlog/2026-07-22-email-provider-contract/task.md`.

## Stage 2 — tracker schema v5 and the single calendar file

Add the structured `jobs[].progress` summary, migrate v4 metadata with a
dry-run-first formatter-preserving tool, add `config.calendar_path()`, and
implement the stable-marker `calendar.md` writer. The application tracker
is the only transactional writer to metadata plus calendar.

Commands planned for this stage:

```text
status.py --update-progress <slug> <role-match> --phase <phase> --state <state> [--label TEXT]
status.py --check-calendar
status.py --sync-calendar [--write]
filter_jobs.py --phase <values> --progress-state <values>
```

**Acceptance:** schema-v5 validation and migration tests pass; progress-only
updates never move status folders; malformed/duplicate calendar markers and
checksum races fail without partial writes; manual unmarked content is
preserved byte-for-byte; reschedule tests retain superseded times.

Task: `tasks/0_backlog/2026-07-22-application-progress-calendar/task.md`.

## Stage 3 — email download sync

Build the store's email sync after Stage 1: full resync and inventory-diff
tombstoning first, delta second, Inbox + Sent + Drafts, per-account state,
provider-immutable message IDs, the staleness tripwire, and attachment
metadata only. Apply the resolved git policy: track index headers and safe
annotations; ignore raw, derived, and the evidence sidecar.

**Acceptance:** full-resync and token-expiry paths pass against a synthetic
mailbox; induced staleness produces the hard stale banner; moves and
deletions have the documented semantics; attachment bytes never land in
the store; no tracked fixture contains third-party content.

Task: `tasks/0_backlog/2026-07-22-email-store-sync/task.md`.

## Stage 4 — categorization, progress proposals, and reconciliation

Implement deterministic categories and guarded
company→application→role links, then add the scheduling evidence map from
[the design](README.md#4-email-evidence-mapping). The store may propose
progress/calendar changes, but the application tracker applies them only
after transition-time exact-message verification.

This stage includes booking, awaiting schedule, confirmed interviews,
both reschedule directions, cancellation without rejection, and
post-interview awaiting-result behavior. It also adds one-read
by-application indexes and the unresolved/needs-reply/deadline queues.

**Acceptance:** adversarial wrong-role and drifting-thread fixtures cannot
change progress; weak or attachment-only time evidence routes to triage;
Sent availability produces `awaiting_schedule`; confirmed replacement
times preserve the old occurrence; metadata and calendar either both
commit or neither does.

Task: `tasks/0_backlog/2026-07-22-email-progress-reconciliation/task.md`.

## Stage 5 — store-first review cutover

Run the old live review and new store-first review on the same message
intersection. Cut over only after five consecutive zero-mismatch runs and
at least 300 job-related messages have passed through both flows, as
already decided in the raw-data-layer design. Measure token and latency
changes, retain the live staleness probe, and keep the pre-draft
Sent/Drafts check against every account.

**Acceptance:** the dual cutover criterion is recorded; the new progress
and calendar views produce no unexplained differences from exact-message
review; all draft-only and leak guards pass. Gmail remains read-only and
is additive after the Outlook path stabilizes.

## Verification shared by every stage

Every stage runs its focused unit tests plus vendoring, instruction-budget,
link, public leak, and draft-only checks when the changed surface applies.
Any behavioral edit to an application-tracker or email skill instruction
file runs that skill's canaries and records the result. No stage modifies a
real application or mailbox as part of CI.

## Human questions / additional tasks

*Owner space — anything written here is picked up by the next agent session
(see the async-collaboration contract in `AGENTS.md`). Questions get
answered in place; tasks get filed into `message-queue/` and linked back here.*

- (none right now)
