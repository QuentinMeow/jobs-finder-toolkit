# Verification — 2026-07-28-slim-company-research-skill

The work merged as PR #108 (the slimming) and PR #110 (the canary record). The task folder
was left in `0_backlog`, so this file records the evidence gathered on **2026-07-30** from
the merged trunk (`main` at `562655f`) rather than from the branch — the boxes were ticked
against what is actually shipped, not against what the PR claimed.

## Box 1 — headroom against the instruction budget

```
$ .venv/bin/python automation/metrics/instruction_budget.py
FILE                                              LINES  BYTES  ~TOKENS  BUDGET  STATUS
skills/company-research/SKILL.md                    469  30825     7706     600      ok
skills/company-research/LESSONS.md                   52   3512      878     160      ok
skills/company-research/reference.md                206  13220     3305       -     n/a
```

469 lines against the hard 600-line budget, and against this task's own ≤ 550 target — **81
lines of headroom**. The `--strict` form (the one `automation/hooks/pre-commit` runs) exits 0:

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.
```

This was the point of the task. The execution plan records that
`skills/company-research/SKILL.md` sat at **595/600** — five lines of headroom — and that
[workspace phase 8](../../0_backlog/2026-07-28-workspace-phase-8-instruction-surface/task.md)
**adds path references to it**, so phase 8 could not have committed at all until this landed.

## Box 2 — no domain edge case lost

`reference.md` exists and carries 206 lines, which is where the five moved blocks went. The
repo rule this box exists to protect is in `AGENTS.md`: *"consolidation never deletes a
domain edge case"* — the content had to become reachable, not disappear.

## Box 3 — canaries recorded

```
$ ls evals/results/ | grep company-research
company-research-046a1f17e5f5-20260730-reference-retier.md
company-research-dfa808b8e0cc-2026-07-22.md
```

`company-research-046a1f17e5f5-20260730-reference-retier.md` is this change's run, recorded
by PR #110. The `2026-07-22` file is the earlier baseline.

Running the canaries was mandatory rather than optional here: under the risk-based eval gate
in `evals/README.md`, moving five blocks out of a `SKILL.md` is a **large** edit, so the
written-rationale escape hatch did not apply.

## Why this folder was still in `0_backlog`

Nothing failed. The work merged and the folder was not moved with it. It is recorded because
the same drift is currently true of five folders in `tasks/3_in-review/` whose PRs have also
merged — those are **not** swept here, because at least one of them
(`2026-07-28-workspace-phase-5-lifetime-taxonomy`) still has every DoD box unticked, and
moving it would assert evidence nobody has gathered.
