# Restructure the repo on the AgentFold pattern

- **Priority**: P0 (blocks work)
- **Area**: repo
- **Source**: owner request, live session 2026-07-22; decision record
  `memory/decisions/agentfold-restructure.md`
- **Claimed-by**: claude (session 2026-07-22)

## Goal

Land the owner-approved AgentFold restructure as a stack of focused PRs,
leaving every reference, hook, exporter path, and private-overlay mirror
consistent with the new layout.

## Context

Scope and rationale live in `memory/decisions/agentfold-restructure.md`.
Planned stack:

1. `todo/` → `message-queue/` + `tasks/`; records → `memory/` (this PR).
2. `docs/` → `handbook/` + `design/` (annex split into named docs).
3. the hidden `.agents/skills/` dir → `skills/`; `scripts/` → `automation/`.
4. Root-contract rewrite + `templates/` + `roadmap/` + `history/` +
   reconciler wired into pre-commit.
5. Mirror the layout in the `private/` overlay repo.

## Definition of done

- No tracked file references a removed path (`todo/`, `design-decisions/`,
  `known-issues/` at root, `docs/`, the hidden skills dir, `scripts/`).
- `gardener.py verify-links` passes; CI (vendor drift, compile, tests, leak
  guard) passes on every PR in the stack.
- The reconciler's checks pass on the restructured tree.
- The private overlay mirrors the new layout in its own commit.
