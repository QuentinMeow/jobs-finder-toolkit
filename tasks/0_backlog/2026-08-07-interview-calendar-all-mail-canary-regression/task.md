# Clear the interview-calendar all-mail canary regression

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: `evals/results/interview-calendar-d975a530ee61-20260807-availability.md`
- **Claimed-by**:

## Goal

Make the all-mail interview-calendar workflow consistently retain company-level evidence when an
exact posting is unresolved, then pass the complete six-canary set in fresh contexts.

## Context

The 2026-08-07 pre-merge run passed five canaries. The all-mail scenario failed: one fresh runner
assigned a receipt that lacked an exact posting ID to one of two in-progress roles. An earlier run
kept it unresolved but did not demonstrate the full-store coverage command or the required
human-first Markdown/HTML layout checks. The availability-projection edit stays unmerged until this
is resolved; do not weaken the rubric or relabel the failed run as a skip.

## Definition of done

- A fresh run of `evals/canaries/interview-calendar.yaml` passes all six rubrics.
- The all-mail transcript runs one complete store-coverage pass, preserves the ambiguous update at
  company scope, creates no event, and verifies both calendar views and their stable second refresh.
- A new pinned result under `evals/results/` records the passing run and supersedes the failed
  pre-merge result without editing the old record.
