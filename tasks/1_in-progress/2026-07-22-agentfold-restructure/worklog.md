# Worklog — 2026-07-22-agentfold-restructure

## 2026-07-22 — session 1 (claude)

- Confirmed scope with owner live: full restructure, all four new
  components (reconciler, templates/, roadmap/, history/), no aliases;
  email stages follow in plan order afterwards.
- PR 1: moved `todo/` → `message-queue/` (+ new `clarifications/`,
  `retries/` queues) and `tasks/` (status folders, dated task-folder ids
  recovered from git); `design-decisions/` + `known-issues/` →
  `memory/decisions/` + `memory/known-issues/`; added `memory/facts/`,
  `memory/lessons/`; rewrote all references (30 files mechanical + root
  `AGENTS.md` by hand); recorded the ADR
  `memory/decisions/agentfold-restructure.md`.
