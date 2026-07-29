# Handover — interview-calendar-email-reconciliation

- **Date**: 2026-07-28
- **Task(s)**: none

## What happened

- Added the public [`interview-calendar`](../../../skills/interview-calendar/SKILL.md) orchestration
  skill, its UI metadata, compatibility links, exporter/marketplace registration, documentation,
  and three canaries. It composes the audited email reader, the application tracker, and the
  Outlook Calendar connector without creating another data writer.
- Reconciled the requested 48-hour mailbox window into the private application overlay and Outlook
  Calendar. Exact-message, per-role, notes-deduplication, and search-before-create gates were used;
  ambiguous and generic mail stayed unchanged.
- Hardened the follow-up all-mail workflow to include retained Deleted Items, full bodies and
  participants, every in-progress company/role/job ID, explicit zero matches, folder provenance,
  and one safe mid-run authentication refresh for long read-only syncs.
- Added an idempotent local company view for every in-progress application and role, while keeping
  ambiguous evidence at company scope and never creating events from proposed availability.

## Where things stand

- Public skill changes and private application updates are uncommitted. The all-time live inventory
  and exact-message reconciliation are complete; no additional evidence-backed application or
  calendar changes were needed after the retained Deleted Items review.
- Tracker metadata/calendar checks, email and tracker suites, vendoring, reconciler, instruction
  budget, public export leak guard, and all affected skill canaries pass.

## Needs your attention

- The parked [logs-as-store-projections decision](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  remains unchanged; its revisit condition has not been reached.
- One private role-link clarification was filed and one unmatched-requisition clarification was
  refreshed. Their personal details are intentionally not duplicated into this public handover.
