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
clarification to `skills/application-tracker/SKILL.md` about the bundled
`.txt` file's naming (`_<job title>` suffix — confirmed present today at
`skills/application-tracker/SKILL.md:55`:
`` `<APPLICATION_STEM>_<job title>.txt` ``). The gate record's diff-coverage map
lists this as `(no canary asserts .txt naming) — UNGATED`. Checked directly
against `evals/canaries/application-tracker.yaml` as it stands today (93 lines,
5 canaries: `at-pipeline-health`, `at-validate-drafted-metadata`,
`at-enrich-insert-only`, `at-status-move-on-request`,
`at-update-one-role-multi-app`) — none references `.txt` or the bundled-file
naming; the gap is still open. (Note: resume-writer's `rw-bundled-txt-structure`
canary does check the `.txt` bundle's internal section structure and naming
during rendering, but that is a different skill/suite from the
application-tracker-side clarification this gap refers to — e.g. how
`status.py`/the tracker recognizes or reports on the bundled file by name.)

Relevant files:
- `evals/canaries/application-tracker.yaml` (where the new canary belongs)
- `skills/application-tracker/SKILL.md` (the naming-convention table,
  around the `<APPLICATION_STEM>_<job title>.txt` row)
- `examples/me/applications/6_drafted/example-corp-senior-software-engineer/` (the
  shipped fixture already contains a correctly-named bundled `.txt` file to
  assert against)

## Definition of done

- A new or extended application-tracker canary asserts that the tracker
  correctly identifies/reports the bundled `.txt` file by its
  `<APPLICATION_STEM>_<job title>.txt` naming (e.g. via a pipeline-health or
  metadata-validation flow that surfaces the deliverable), and fails if the
  naming convention is violated.
- The canary passes under a live run against the shipped example fixture.

## 2026-07-31 — one count corrected, and a defect routed here rather than filed separately

**The canary-file count in Context is stale.** `evals/canaries/application-tracker.yaml` is
**112 lines with 6 canaries**, not 93 with 5 — a sixth, `at-refresh-in-progress-company-view`, was
added. All five named ids still exist and are correct, and the substantive claim holds: none of
the six references `.txt` or the bundled-file naming, so the gap is still open.

**Verify-with**: `grep -n '  - id:' evals/canaries/application-tracker.yaml`

**And this task is bigger than it looks, because the code it would gate is wrong.** A triage found
a live defect with no task of its own; rather than file a second task for it, it is recorded here,
because a canary written to the definition of done below would **fail against current code** and
whoever picks this up needs to know that before they start:

```
$ grep -n 'APPLICATION_STEM}\*\.txt' skills/application-tracker/scripts/status.py
206:        "has_app_txt": bool(list(app_dir.glob(f"{APPLICATION_STEM}*.txt"))),
```

The glob is **prefix-only**. It never checks the `_<job title>` suffix and it never checks the
one-`.txt`-per-JD rule, so a two-role folder carrying a single `.txt` reports healthy and
pipeline-health quietly overstates bundle completeness. So this is a bug ticket wearing a canary
ticket's clothes: **tighten the glob first, then write the canary against the tightened
behaviour.** Doing it the other way round lands a red canary against correct-looking code.
