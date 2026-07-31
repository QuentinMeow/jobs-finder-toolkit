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
- PR 3 (#58): hidden `.agents/skills/` → visible `skills/` (adapter
  symlinks retargeted; `.agents/skills` kept as a tracked symlink),
  `scripts/` → `automation/`, `hooks/` → `automation/hooks/`; fixed
  depth-shifted `parents[N]` repo-root constants and segmented path
  literals; full test battery green (shared, publish, job-search 210,
  resume-writer, tracker, outlook, example render, verify-links).
- PR 4: added `templates/` (13 schemas; READMEs now link instead of
  restating), the reconciler (`automation/reconcile/reconcile.py` — 6
  checks, retry filing, generated `memory/index.md`) wired into pre-commit
  + CI + exporter, `roadmap/` (desired/current state), `history/` (+ this
  session's handover), `handbook/collaboration-modes.md`, and delta edits
  to `AGENTS.md` (mode line, boot additions, reconciler guardrail,
  templates router line).

## 2026-07-31 — session 2 (agent, bookkeeping)

- Closed. All four stack PRs (#56–#59) are merged, the process folders and the reconciler ship in
  both repositories, and `reconcile --check --require-roots` is clean. Evidence in
  `verification.md`; moved `1_in-progress` -> `4_done`.
- Recorded the one reversal rather than hiding it: item 3's top-level `handbook/` + `design/` was
  undone by workspace phase 2 under the superseding ADR
  `memory/decisions/docs-parent-for-the-human-read-trees.md`.
- The cost of leaving this open was not the folder — it was the false in-flight signal. Nine days
  after the work merged, `tasks/1_in-progress/` still claimed someone was on it.
