# Run the resume-writer canaries for the validation-gate honesty change

- **Priority**: P1 (this round)
- **Area**: resume-writer
- **Source**: the PR that made `check.py` report `PDF NOT INSPECTED` / `SKILL VOCABULARY NOT INSPECTED` (branch `wip/09-resume-validation-gates`)
- **Claimed-by**: records-match-the-tree pass, 2026-08-02 (retro-closure; see verification.md)

## Goal

Run `evals/canaries/resume-writer.yaml` at head and record the result in
`evals/results/`, closing the risk-based eval gate that the gate-honesty change
opened but could not close in its own workspace.

## Context

That PR strengthened two hard gates in the resume-writer:

- a render that inspected no PDF now FAILs (was: an unqualified
  `all checks passed`), unless `--no-pdf` declared a DOCX-only draft, which
  reports the six PDF gates as NOT RUN instead;
- a profile whose `## Skills` section does not parse now FAILs once with
  `SKILL VOCABULARY NOT INSPECTED` instead of cascading ~30 misleading
  "uncategorized skill" failures.

It edited `skills/resume-writer/SKILL.md` (a new Step 6 failure-menu entry for
each message) and `skills/resume-writer/LESSONS.md` (the converter-absent note).
Judged against `evals/README.md`, that is a **MUST run**: "adds, removes,
weakens, or reroutes any hard gate" — the instruction edits tell the drafting
agent how to react to a gate that did not exist before. The edits themselves are
small (~12 instruction lines across 2 files of one skill), so the risk is bounded,
but the honest reading of the criteria is a run, not a recorded skip.

The authoring agent had no canary harness in its workspace and did not run them,
so the PR body records the judgement rather than a result. Do not treat the
absence of a canary line in `evals/results/` as a skip: the gate is open.

**Accumulated since filing** (a gated run covers the state at head, not only its triggering diff —
`evals/README.md`, "Every skip must be recorded"): the recorded skip from
`2026-08-01-resume-writer-docs-misstate-what-check-py-enforces` (SKILL.md + reference.md threshold
corrections, 2026-08-02). Judge the rubric against head, not against the gate-honesty diff alone.

Run mechanics: `evals/README.md` -> "How to run a canary" (model-pinned; read
`total_tokens` / `wall_clock_s` / `tool_calls` for the head SHA and compare with
the last recorded resume-writer run — a large efficiency regression is a fail
even when the rubric passes).

## Definition of done

- [ ] `evals/canaries/resume-writer.yaml` run at head on the pinned model.
- [ ] Rubric passes, and `total_tokens` / `wall_clock_s` show no large regression
      against the most recent recorded resume-writer run.
- [ ] A result file exists in `evals/results/` from `evals/results/TEMPLATE.md`
      naming the head SHA.
- [ ] If a canary regresses, the finding is filed (task or
      `memory/known-issues/`) before this task is closed.
