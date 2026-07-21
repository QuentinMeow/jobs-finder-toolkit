# tasks/

One file per task. Each file is **self-contained**: a reader (human or agent)
should be able to pick up the task from the file alone, without hunting
through other docs, chat history, or issues.

## Rules

- Filename: `<kebab-slug>.md` (no numbering — slugs don't churn on insert/delete).
- **Public tree ⇒ leak-guard rules apply**: no real names, employers,
  applied-to companies, or dated personal facts. A task tied to the owner's
  real pipeline goes in `private/tasks/` instead (same format).
- When a task is finished, set `Status: done` and keep the file for one PR
  cycle, then delete it in the PR that closes it (no archive folder — git
  history is the archive).

## File format

```markdown
# <Title>

- **Status**: todo | in-progress | done | dropped
- **Priority**: P0 (blocks work) | P1 (this round) | P2 (someday)
- **Area**: job-search | resume-writer | tracker | harness | benchmarks | repo
- **Source**: where this came from (result file, PR, session date, GH issue #)

## Goal
What outcome finishes this task, in one or two sentences.

## Context
Everything needed to start: relevant files, prior decisions, constraints.
Write it as if the reader has read AGENTS.md and nothing else.

## Definition of done
Checkable bullet(s) — a verification command or observable artifact.
```
