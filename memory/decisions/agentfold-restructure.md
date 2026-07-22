# Restructure the repo's process layer on the AgentFold pattern

- **Status**: decided
- **Date**: 2026-07-22
- **Decided by**: owner (live session Q&A, 2026-07-22)
- **Supersedes**: extends `process-folders-v2-todo-queue.md` (the todo/ queue
  family) rather than reversing it — same philosophy, new layout

## Context

The owner asked for a refactor applying the organizational principles of the
AgentFold agent-native-repository pattern (folder-as-a-service, files as
messages routed by who acts next, status-as-location, single-source-of-truth
schemas, mechanical enforcement). This repo already shared much of that DNA
via the `todo/` queue family and root record folders; the gap was layout and
the missing enforcement/template layer.

## Decision

Full restructure, no compatibility aliases, owner-confirmed scope:

1. `todo/` splits into **`message-queue/`** (`needs-human/` `decisions/`,
   `clarifications/`, `reviews/`; `needs-agent/` `requests/`, `retries/` —
   routed by who acts next) and **`tasks/`** (one folder per task,
   `YYYY-MM-DD-<slug>` ids, status folders `0_backlog`…`4_done`).
2. `design-decisions/` + `known-issues/` consolidate under **`memory/`**
   (`decisions/`, `known-issues/`, plus new `facts/` and `lessons/` zones).
3. `docs/` dissolves into **`handbook/`** (operating docs) and top-level
   **`design/`** (design programs). *(separate PR)*
4. the hidden `.agents/skills/` → visible **`skills/`** with agent-adapter symlinks;
   `scripts/` → **`automation/`**. *(separate PR)*
5. New components: **`templates/`** (single source of truth for file
   schemas), **`roadmap/`** (desired vs current state), **`history/`**
   (session handovers), and a **reconciler** (`automation/reconcile/`) run
   from pre-commit, filing findings into `needs-agent/retries/`. *(separate
   PR)*
6. The `private/` overlay mirrors the same layout (`private/message-queue/`,
   `private/tasks/`, `private/memory/`).

## Alternatives considered

- Adopt principles without renames — rejected by owner (wanted full layout
  alignment).
- Queues-and-memory-only partial restructure — rejected by owner in favor of
  the full scope.

## Consequences

- Every doc reference to the old paths was rewritten in the restructure PRs;
  git history is the continuity record.
- The public exporter continues to omit the process folders
  (`message-queue/`, `tasks/`, `memory/`, `roadmap/`, `history/`) exactly as
  it omitted `todo/` and the root record folders.
- Existing open items kept their content; task files became
  `tasks/0_backlog/<id>/task.md` folders with filed dates recovered from git
  history.
