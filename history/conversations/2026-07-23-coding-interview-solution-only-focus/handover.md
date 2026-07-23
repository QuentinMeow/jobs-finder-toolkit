# Handover — coding-interview solution-only focus

- **Date**: 2026-07-23
- **Task(s)**: none

The private coding-interview skill now makes fast, high-quality solution
generation its exclusive operational focus.

## What happened

- Added a solution-only priority and six-step fast path near the top of the skill.
- Directed agents to ignore unrelated skills, workflows, queues, application
  pipelines, and maintenance unless a higher-priority instruction requires them.
- Kept every existing language, explanation, debugging, follow-up, testing, and
  verification requirement mandatory.

## Where things stand

- Complete and published in private PR #26. The diff is whitespace-clean, the
  file is below 500 lines, and the skill-creator validator passes on a
  compatibility copy that omits the repository-required `visibility: private`
  field.
- No coding-interview canaries exist: `evals/README.md` deliberately excludes
  the private skill from the public-only eval harness.

## Needs your attention

- [Benchmark-draft disposition](../../../private/message-queue/needs-human/decisions/benchmark-drafts-promote-or-delete.md)
  still awaits a keep/promote/delete choice; the default keeps all seven frozen.
- [Benchmark search zero-result policy](../../../private/message-queue/needs-human/decisions/benchmark-search-leg-20260721-zero-eligible.md)
  remains parked until another comparable live search is needed.
- [Outlook 30-day review](../../../private/message-queue/needs-human/reviews/2026-07-22-outlook-30-day-review.md)
  remains available for optional review.
- [Skip-log projection decision](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  remains parked until raw-data-layer stage 3 has run for a few weeks.
