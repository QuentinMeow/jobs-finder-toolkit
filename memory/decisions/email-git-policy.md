# Track only safe email index headers and annotations

- **Status**: decided
- **Date**: 2026-07-22
- **Decided by**: owner
- **Extends**: [raw-data-layer-decisions.md](raw-data-layer-decisions.md)

## Context

Email subjects, snippets, sender identities, scheduling details, and
compensation discussions contain sensitive third-party information. The
email `raw/` and `derived/` zones are rebuildable local data; pushing them
to a private git repository would make that content difficult to remove
from history without adding recovery value.

## Decision

Track only content-free index headers plus safe `annotations/` in the
private overlay. Do not track `raw/`, `derived/`, message index rows, or the
quoted-evidence sidecar.

## Consequences

- Human judgments and the store's index shape have private git history.
- Message bodies, subjects, snippets, and third-party identities never
  enter git history.
- A damaged derived email store is rebuilt from local raw rather than
  restored from git.
- The email sync implementation must test the tracked-file allowlist and
  prove that a planted subject or body cannot enter a tracked path.
