# Grow folder-scoped instructions reactively

- **Status**: decided
- **Date**: 2026-07-22
- **Decided by**: owner

## Context

Folder-scoped `AGENTS.md` leaves reduce always-loaded context only when
they contain knowledge that genuinely belongs to one folder. Proactively
seeding leaves produced duplicated instructions, drift, and a net increase
in context during the design's first iteration.

## Decision

Create a new leaf only after the second folder-local correction or when the
owner explicitly asks for one. When uncertain, file a decision in
`message-queue/needs-human/decisions/`. Every leaf must satisfy the relocation-or-pointer rule:
it contains pure pointers or lines removed from always-loaded instructions
in the same change.

## Consequences

- The tree grows only from observed need.
- A folder may experience one local mistake before a leaf is justified.
- Leaves remain net-zero-or-negative additions to loaded context.
