# tasks/ — work items; the folder a task sits in IS its status

One folder per task. A task's **status is its location** — there is no
status field to drift out of sync. Move a task between status folders with
`git mv`; nothing inside the folder changes.

```
0_backlog/      filed, not started
1_in-progress/  claimed and being worked
2_blocked/      waiting on a Blocking: yes decision in message-queue/needs-human/
3_in-review/    work done, awaiting review/merge
4_done/         merged/verified; pruned after ~90 days (learnings promoted to memory/ first)
```

## Naming and identity

- Task id = folder name = `YYYY-MM-DD-<kebab-slug>` (the date it was
  **filed** — it never changes; status changes are folder moves).
- Reference tasks by **id**, never by full path (paths change with status).
  Find one with `ls tasks/*/<task-id>`.

## Folder contents

- `task.md` — always: goal, context, definition of done (format below).
- `plan.md` — from `1_in-progress`: small verifiable steps, checked off.
- `design.md` — when the task involved real design choices.
- `worklog.md` — append-only, newest at bottom, one entry per session.
- `verification.md` — required for `3_in-review`/`4_done`: commands
  actually run and their real output. Never fabricated.

## Rules

- **Claim before working**: set `**Claimed-by:**` in `task.md` and commit
  before starting. One agent per task.
- **Public tree ⇒ leak-guard rules apply**: no real names, employers,
  applied-to companies, or dated personal facts. A task tied to the owner's
  real pipeline goes in `private/tasks/` instead (same layout).
- A task dropped or superseded leaves a one-line trace first — in the doc
  that spawned it or in `memory/known-issues/` — so a later session reading
  that doc doesn't re-file it.
- A task too big to plan in ~10 steps is split; child tasks link the parent
  via `**Parent:**`.

## task.md format

```markdown
# <Title>

- **Priority**: P0 (blocks work) | P1 (this round) | P2 (someday)
- **Area**: job-search | resume-writer | tracker | email | harness | benchmarks | repo
- **Source**: where this came from (design doc, result file, PR, session date)
- **Claimed-by**: (set when work starts)

## Goal
What outcome finishes this task, in one or two sentences.

## Context
Everything needed to start: relevant files, prior decisions, constraints.
Write it as if the reader has read AGENTS.md and nothing else.

## Definition of done
Checkable bullet(s) — a verification command or observable artifact.
```
