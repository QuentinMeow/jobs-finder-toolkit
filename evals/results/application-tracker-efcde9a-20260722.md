# Eval result — application-tracker

| Field | Value |
|-------|-------|
| Skill | `application-tracker` |
| Canary set | `evals/application-tracker/canaries.yaml` (v5 set, updated in this branch) |
| Run kind | regression pre-merge (gates the schema-v5 SKILL.md edit on `email/stage-2-progress-calendar`) |
| Git SHA | `efcde9a` head (4 canaries executed at `8118eea`; delta to head = LESSONS v4→v5 text fix, known-issue records, and the regression-tested `metadata_editor` clamp — see Notes) |
| Model version | `claude-fable-5` (runner + judged sessions + judge) |
| Config mode | examples fallback (config.yaml unset — fresh clones of the branch; no private overlay) |
| Date | 2026-07-22 |
| Judge | manual per `evals/rubrics/judging.md` (session parent as judge; every bullet pass/fail, failure-mode = auto-fail) |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `at-pipeline-health` | 1 | 78,590* | 111 | 13 | Folder-derived rollup; new v5 "Action needed" surfacing used; zero mutations |
| `at-validate-drafted-metadata` | 1 | 74,591* | 88 | 11 | v5-only schema + required `progress` + closed-coupling verified; deliberate `--statuses drafted` narrowing; also flagged the stale LESSONS v4 line (fixed in `e2ebe38`) |
| `at-enrich-insert-only` | 1 | 80,535* | 99 | 14 | Insert-only; sentinel comment + `progress` block byte-identical; salary stayed null; JD-wins provenance. Cosmetic: trailing space after replaced inline placeholders (pre-existing v4 behavior) |
| `at-status-move-on-request` | 1 | 94,207* | 103 | 12 | Final run at `efcde9a` on the unmodified previously-failing fixture shape: `--update` succeeds first-try, zero hand edits. (First valid-tree attempt exposed the editor bug below → judged as the bug's discovery, not a pass) |
| `at-update-one-role-multi-app` | 1 | 108,877 | 434 | 42 | Exactly one role transitioned; sibling untouched; honest `state: unknown` + clarifying question (never `scheduled` without time+timezone); rollup moved the folder. Includes fixture scaffolding + bug diagnosis time |

Pass rate: **5/5**.

\* Resumed-context runs (see Notes) — token totals include the voided first
attempt's context, so they are NOT baseline-comparable; `tool_calls` and
`wall_clock_s` are per final attempt and roughly indicative. No efficiency
blow-up is suspected: the acted requests themselves used 5–12 commands each.

## Verdict

- **Regression: PASS.** All five canaries pass at head; the behavioral v5
  SKILL.md edit (schema section + new commands) is cleared for merge. This
  gated run also covers the accumulated mechanical skips ahead of it
  (restructure path renames in all SKILL.md files, the email-assistant
  skill rename, the LESSONS v4→v5 correction).
- **Two real defects found and resolved during the run** (canaries working
  as designed):
  1. `metadata_editor` block-mapping end-mark overshoot — every
     `--update`/`--update-job` crashed (fail-closed) on a job whose mapping
     ends with the block `progress` and lacks `status_date` (the exact
     shape `migrate_to_v5.py` produces), and field insertions bled into the
     next block-style jobs entry. Fixed in `44d26fa`
     (`_reliable_end_index` clamp + 3 regression tests); record:
     `memory/known-issues/metadata-editor-block-mapping-field-insertion.md`.
  2. Tracker `LESSONS.md` still asserted schema v4 — corrected in `e2ebe38`.

## Notes — run-environment incident (for future canary runs)

The first execution wave ran in agent worktrees that were checked out at
`main` (`0545b1f`, v4 state), not the branch under test — those runs were
voided and repeated in fresh `git clone --branch <branch>` copies under the
session scratchpad (one canary self-corrected with `git reset --hard`).
Lesson for the next runner: **verify the checkout SHA and the fixture's
`job_metadata_schema_version` before acting** (both re-runs did this), and
prefer explicit clones of the branch under test over assuming a worktree's
ref. Re-runs happened in resumed agent contexts (subagent-budget reuse), so
their token totals are not clean-context numbers; rubric verdicts judge
concrete behaviors and are unaffected.
