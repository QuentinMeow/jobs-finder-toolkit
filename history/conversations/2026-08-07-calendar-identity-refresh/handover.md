# Handover — calendar identity refresh

- **Date**: 2026-08-07
- **Task(s)**: 2026-08-07-calendar-identity-refresh

## What happened

- Nothing is broken or half-done in the implementation: progress updates now repair stale application slugs and role titles in both calendar markers and tool-generated visible rows.
- A fictional end-to-end regression covers the corrected identity path and the complete calendar test module passes.

## Where things stand

- The public fix is ready for review on its feature branch; final repository gates and the pull request are handled in this session.

## Decisions made for you

- Existing calendar occurrence IDs remain stable while their application slug and role follow current metadata; changing that choice would break links and require a migration.
- Owner-authored visible wording remains untouched; only text proven to match the tool's previous default is regenerated.

## If X then Y

- If a future application correction changes company identity as well as role/slug, add explicit company provenance to the calendar marker before attempting automated visible-text replacement.

## Dead ends

- Updating only the hidden marker passed the machine identity check but left the visible row stale; the renderer also needed to recognize the old generated role text.

## Needs your attention

- Nothing.
