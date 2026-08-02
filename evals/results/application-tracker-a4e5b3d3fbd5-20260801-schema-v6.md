# Eval result — application-tracker

| Field | Value |
|-------|-------|
| Skill | `application-tracker` |
| Canary set | `evals/canaries/application-tracker.yaml` |
| Run kind | regression pre-merge |
| Run commit | `a4e5b3d3fbd5` plus uncommitted working tree |
| Anchor commit | `none` |
| Model version | `gpt-5.6-sol` (high reasoning) |
| Config mode | examples fallback (config.yaml unset) |
| Date | `2026-08-01` |
| Judge | manual Sol-high agent + rubric |

```eval-pin v1
skill application-tracker
pin sha256=57a04ba76f00be18 bytes=30851 path=skills/application-tracker/SKILL.md
pin sha256=fcad03eefa7ed01a bytes=3766 path=skills/application-tracker/LESSONS.md
pin sha256=01a605265ef979f8 bytes=11235 path=evals/canaries/application-tracker.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `at-pipeline-health` | 1 | n/a | n/a | n/a | Folder-derived rollup and action reporting; no mutation. |
| `at-validate-drafted-metadata` | 1 | n/a | n/a | n/a | Schema v6 accepted; scalar links and invalid structures rejected. |
| `at-enrich-insert-only` | 1 | n/a | n/a | n/a | Insert-only, formatting-preserving, checksum-guarded behavior verified. |
| `at-status-move-on-request` | 1 | n/a | n/a | n/a | Explicit whole-application move and log reminder preserved. |
| `at-update-one-role-multi-app` | 1 | n/a | n/a | n/a | Exact role only; no invented scheduled time. |
| `at-refresh-in-progress-company-view` | 1 | n/a | n/a | n/a | All roles, ambiguous company evidence, stable duplicate-free refresh. |
| `at-multiple-interview-occurrences` | 1 | n/a | n/a | n/a | Three ordered IDs/entries; scheduled until final completion, then awaiting_result. |

Pass rate: `7/7`.

## Verdict

- **Regression:** PASS. Every rubric check passed after the new multi-occurrence prompt was made
  self-contained with its three exact Pacific-time blocks.
- **Efficiency vs baseline:** not measured. No isolated metrics rows were available; unit-test
  runtime was not substituted for comparable canary metrics.
