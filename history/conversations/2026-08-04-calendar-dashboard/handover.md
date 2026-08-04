# Handover — calendar dashboard

- **Date**: 2026-08-04
- **Task(s)**: none

## What happened

- Nothing is half-implemented: the calendar renderer now produces one chronological preparation agenda and one action table in both Markdown and an optional offline HTML companion.
- Explicit interviews and actions whose posting match is unresolved stay visible without receiving a fabricated application link.
- Past interviews, pipeline detail, and raw tracker material remain available in collapsed sections; mobile HTML changes tables into labeled cards.

## Where things stand

- The public branch `codex/calendar-dashboard-20260804` is prepared for review alongside a separate private product-data branch.
- Unit, calendar-consistency, repeated-refresh, readability, canary, and repository gate evidence belongs in the public pull request; the private pull request carries only the generated calendar products.

## Decisions made for you

- Markdown remains canonical and HTML is a generated sibling projection; reversing this would require a new synchronization authority rather than a display-only rollback.
- Unresolved evidence uses validated supplemental agenda records and an explicit `posting link unresolved` label; omitting it or guessing a link would make one surface incomplete or inaccurate.
- Named rounds sharing an organizer block render on separate rows with the shared window and an explicit unknown-subslot note; no unavailable time was inferred.
- Immediate `Now` actions sort before future dated work because the primary view is an execution queue, not a deadline ledger.

## If X then Y

- If an unresolved item later gains an exact posting match, migrate it to canonical application progress and remove its supplemental agenda record in the same refresh.
- If the HTML companion is hand-authored, refresh refuses to overwrite it; keep a separate filename or restore the generated marker before using `--html`.

## Dead ends

- A tracker-only HTML projection was rejected after readability review because it omitted important unresolved interviews and actions.
- A wide horizontally scrolling mobile table was rejected in favor of labeled card rows.

## Needs your attention

- No new public queue item was filed. Existing public decisions remain open; their default paths are unchanged.
- 28 pending · top: [job-search-us-only-default-asymmetry](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md) — inconsistent search and draft defaults can repeatedly admit roles that later cannot be drafted.
