# Handover — agentfold-restructure

- **Date**: 2026-07-22
- **Task(s)**: 2026-07-22-agentfold-restructure

## What happened

- The owner approved a full AgentFold-pattern restructure (scope Q&A in
  session; ADR: `memory/decisions/agentfold-restructure.md`), shipped as a
  stacked PR train: #56 (queues/tasks/memory — merged), #57 (handbook +
  design), #58 (skills/ + automation/), and the harness-components PR
  (templates/, roadmap/, history/, reconciler — this one).
- The private overlay was mirrored in two commits of its own.

## Where things stand

- #56 merged; #57/#58/harness PR in review, each verified locally (full
  test battery + leak guard + verify-links + reconciler green).
- Next: email execution plan Stage 1 (provider contract,
  `tasks/0_backlog/2026-07-22-email-provider-contract`) then Stage 2
  (tracker schema v5 + calendar).

## Needs your attention

- [private decision: benchmark drafts promote-or-delete](../../../private/message-queue/needs-human/decisions/benchmark-drafts-promote-or-delete.md)
  — still awaiting your answer ("leave parked" chosen this session, so the
  7 drafts stay frozen as the quality baseline).
- Merge order: #57 → #58 → harness PR (each stacked on the previous).

## Update (later the same session)

- Email Stage 1 shipped as PR #60; Stage 2 (schema v5 + calendar) is PR'd
  stacked on it, gated by a full 5/5 application-tracker canary run that
  also caught and fixed a real metadata-editor bug (44d26fa) — details in
  `evals/results/application-tracker-efcde9a-20260722.md`.
- Owner to-dos after merging the stack: run `migrate_to_v5.py` (preview
  then `--write`) on the private applications; one read-only `--live`
  provider conformance run; optionally set `paths.calendar_md` in
  `config.yaml`.
