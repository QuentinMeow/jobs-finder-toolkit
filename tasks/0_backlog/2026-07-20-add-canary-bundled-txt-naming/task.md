# Add an application-tracker canary that asserts the bundled `.txt` naming convention

- **Priority**: P2
- **Area**: tracker
- **Source**: `evals/results/instruction-clarity-gate-32fb3ef-20260720.md:70`

## Goal

Add an application-tracker canary that explicitly asserts the bundled
`<APPLICATION_STEM>_<job title>.txt` naming convention, so the clarification
that landed in `application-tracker/SKILL.md` has real behavioral coverage.

## Context

The `fix/instruction-clarity-adversarial-20260720` diff (`32fb3ef`) added a
clarification to `.agents/skills/application-tracker/SKILL.md` about the bundled
`.txt` file's naming (`_<job title>` suffix — confirmed present today at
`.agents/skills/application-tracker/SKILL.md:55`:
`` `<APPLICATION_STEM>_<job title>.txt` ``). The gate record's diff-coverage map
lists this as `(no canary asserts .txt naming) — UNGATED`. Checked directly
against `evals/application-tracker/canaries.yaml` as it stands today (93 lines,
5 canaries: `at-pipeline-health`, `at-validate-drafted-metadata`,
`at-enrich-insert-only`, `at-status-move-on-request`,
`at-update-one-role-multi-app`) — none references `.txt` or the bundled-file
naming; the gap is still open. (Note: resume-writer's `rw-bundled-txt-structure`
canary does check the `.txt` bundle's internal section structure and naming
during rendering, but that is a different skill/suite from the
application-tracker-side clarification this gap refers to — e.g. how
`status.py`/the tracker recognizes or reports on the bundled file by name.)

Relevant files:
- `evals/application-tracker/canaries.yaml` (where the new canary belongs)
- `.agents/skills/application-tracker/SKILL.md` (the naming-convention table,
  around the `<APPLICATION_STEM>_<job title>.txt` row)
- `examples/applications/6_drafted/example-corp-senior-software-engineer/` (the
  shipped fixture already contains a correctly-named bundled `.txt` file to
  assert against)

## Definition of done

- A new or extended application-tracker canary asserts that the tracker
  correctly identifies/reports the bundled `.txt` file by its
  `<APPLICATION_STEM>_<job title>.txt` naming (e.g. via a pipeline-health or
  metadata-validation flow that surfaces the deliverable), and fails if the
  naming convention is violated.
- The canary passes under a live run against the shipped example fixture.
