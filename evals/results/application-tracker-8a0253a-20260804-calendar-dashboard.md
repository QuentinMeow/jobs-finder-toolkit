# Eval result — application-tracker

| Field | Value |
|-------|-------|
| Skill | `application-tracker` |
| Canary set | `evals/canaries/application-tracker.yaml` |
| Run kind | regression pre-merge |
| Run commit | `8a0253ab3c34` plus uncommitted working tree |
| Anchor commit | `none` |
| Model version | `GPT-5.6 Terra` |
| Config mode | examples fallback (config.yaml unset) |
| Date | `2026-08-04` |
| Judge | GPT-5.6 Terra rubric audit with deterministic public-fixture checks |

```eval-pin v1
skill application-tracker
pin sha256=6e52abe6c7a326d5 bytes=31632 path=skills/application-tracker/SKILL.md
pin sha256=fcad03eefa7ed01a bytes=3766 path=skills/application-tracker/LESSONS.md
pin sha256=f2ba7456e9512d35 bytes=11436 path=evals/canaries/application-tracker.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `at-pipeline-health` | 1 | not measured | not measured | not measured | Folder/rollup status, action/staleness review, and read-only boundary passed. |
| `at-validate-drafted-metadata` | 1 | not measured | not measured | not measured | All-status v6 structures, JD mapping, and rollup validation passed. |
| `at-enrich-insert-only` | 1 | not measured | not measured | not measured | Atomic insert-only enrichment and unknown-fact handling passed. |
| `at-status-move-on-request` | 1 | not measured | not measured | not measured | Explicit whole-application transition and log reminder passed. |
| `at-update-one-role-multi-app` | 1 | not measured | not measured | not measured | Exact posting transition, conservative progress, and rollup move passed. |
| `at-refresh-in-progress-company-view` | 1 | not measured | not measured | not measured | Unified agenda, folded detail, preservation, and idempotence passed. |
| `at-multiple-interview-occurrences` | 1 | not measured | not measured | not measured | Parallel occurrence IDs, final-block reduction, and calendar check passed. |

Pass rate: `7/7`.

## Verdict

- **Regression:** PASS. Every rubric bullet passed; no failure mode was observed.
- **Efficiency vs baseline:** not measured. No per-run metrics hook was available.

## Follow-up rerun — Do now first

- **Run commit:** `76e57052d4e6`
- **Model:** `GPT-5.6 Terra`
- **Verdict:** PASS, `7/7`. The company-view canary explicitly verified that **Do now** precedes **Upcoming interviews** while preserving one occurrence per row, folded detail, unresolved-posting visibility, and idempotence.
- **Deterministic evidence:** calendar core `30/30`; progress/calendar `30/30`; full tracker discovery and example metadata validation exited 0.
- **Efficiency:** not measured.

```eval-pin v1
skill application-tracker
pin sha256=3e71757aca5d813a bytes=31631 path=skills/application-tracker/SKILL.md
pin sha256=fcad03eefa7ed01a bytes=3766 path=skills/application-tracker/LESSONS.md
pin sha256=f2ba7456e9512d35 bytes=11436 path=evals/canaries/application-tracker.yaml
```
