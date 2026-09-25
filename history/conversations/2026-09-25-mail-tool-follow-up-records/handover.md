# Handover — Mail tool follow-up records

- **Date**: 2026-09-25
- **Task(s)**: 2026-09-03-support-git-worktree-list-without-z; 2026-09-17-full-sync-leaves-inbox-watermark-stale

## What happened

- Two observed tool problems now have reviewable backlog records. No runtime code changed.
- The workspace dashboard works with supported Git; an older binary earlier on PATH caused the observed failure.

## Where things stand

- The public branch contains only generic task records and this handover. The full-sync watermark cause remains unproven.

## Decisions made for you

- Retain both follow-ups as backlog work. Describe reproduction behavior without mailbox-specific values; preserve the freshness gate.

## If X then Y

- If the dashboard rejects `-z`, inspect the selected Git version before changing parsing.
- If a full sync reports stale data, reproduce serially and compare both watermarks.

## Dead ends

- The legacy Git cannot perform the required merge-tree cleanup proof; selecting the supported Git restores the read-only sweep.

## Needs your attention

- Nothing required to publish these records. Both proposed fixes remain unimplemented.
