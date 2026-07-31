# Handover — runtime skill adapters

- **Date**: 2026-07-30
- **Task(s)**: `2026-07-30-runtime-skill-adapters`

## What happened

- Replaced Codex's broad public-skill pointer with the same per-skill adapter
  model used by Claude Code and Cursor.
- Bootstrap now discovers overlay-only skills dynamically, exposes them to all
  three runtimes, and stores their exact adapter paths only in local Git metadata.
- Removed overlay-only skill identifiers from the current tracked public tree and
  added mounted-overlay leak-token coverage.

## Where things stand

- Implementation and focused tests are complete; full gates and PR publication
  are being closed in this session.
- No private-overlay repository content changed, so this work needs one public
  toolkit PR rather than a second private-overlay PR.

## Needs your attention

- [Decide whether to rewrite published Git history](../../../message-queue/needs-human/decisions/public-history-privacy-rewrite.md):
  default is no destructive rewrite; current and future tracked snapshots are clean.
- [Choose the coding interview screenshot inbox home](../../../message-queue/needs-human/decisions/interview-screenshot-inbox-home.md):
  this older non-blocking workspace decision remains open.
