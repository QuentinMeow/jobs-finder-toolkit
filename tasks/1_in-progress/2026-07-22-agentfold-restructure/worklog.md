# Worklog — 2026-07-22-agentfold-restructure

## 2026-07-22 — session 1 (claude)

- Confirmed scope with owner live: full restructure, all four new
  components (reconciler, templates/, roadmap/, history/), no aliases;
  email stages follow in plan order afterwards.
- PR 1 (#56, merged): moved `todo/` → `message-queue/` (+ new
  `clarifications/`, `retries/` queues) and `tasks/` (status folders, dated
  task-folder ids recovered from git); `design-decisions/` +
  `known-issues/` → `memory/decisions/` + `memory/known-issues/`; added
  `memory/facts/`, `memory/lessons/`; rewrote all references (30 files
  mechanical + root `AGENTS.md` by hand); recorded the ADR
  `memory/decisions/agentfold-restructure.md`.
- PR 2 (#57): dissolved `docs/` — annex split into named `handbook/` docs
  (all "§N" pointers now named links), design families → `design/`,
  exporter allowlist updated.
- PR 3: hidden `.agents/skills/` → visible `skills/` (adapter symlinks
  retargeted; `.agents/skills` kept as a tracked symlink), `scripts/` →
  `automation/`, `hooks/` → `automation/hooks/`; fixed depth-shifted
  `parents[N]` repo-root constants and segmented path literals; full test
  battery green (shared, publish, job-search 210, resume-writer, tracker,
  outlook, example render, verify-links).
