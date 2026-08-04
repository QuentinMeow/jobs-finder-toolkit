# Eval result — application-tracker

| Field | Value |
|-------|-------|
| Skill | `application-tracker` |
| Canary set | `evals/canaries/application-tracker.yaml` |
| Run kind | regression pre-merge |
| Run commit | `e741f08ec1b8` plus uncommitted working tree |
| Anchor commit | `none` |
| Model version | `gpt-5.6-terra` |
| Config mode | isolated fictional fixture; private overlay not used |
| Date | `2026-08-03` |
| Judge | `gpt-5.6-terra` with `evals/rubrics/judging.md` |

```eval-pin v1
skill application-tracker
pin sha256=7d75f14f1209580f bytes=31300 path=skills/application-tracker/SKILL.md
pin sha256=fcad03eefa7ed01a bytes=3766 path=skills/application-tracker/LESSONS.md
pin sha256=f2ba7456e9512d35 bytes=11436 path=evals/canaries/application-tracker.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `at-pipeline-health` | 1 | not measured | not measured | not measured | Folder-derived status, totals, next action, and stale scan preserved without a write. |
| `at-validate-drafted-metadata` | 1 | not measured | not measured | not measured | Schema-v6, JD mapping, rollup, progress, and nullable salary checks passed. |
| `at-enrich-insert-only` | 1 | not measured | not measured | not measured | Empty fields were enriched without rewriting populated human content. |
| `at-status-move-on-request` | 1 | not measured | not measured | not measured | Explicit single-application transition and log follow-up behaved as required. |
| `at-update-one-role-multi-app` | 1 | not measured | not measured | not measured | Only the matched role changed; no schedule was invented. |
| `at-refresh-in-progress-company-view` | 1 | not measured | not measured | not measured | Upcoming interviews render one aligned row per occurrence; details stay folded and refresh is idempotent. |
| `at-multiple-interview-occurrences` | 1 | not measured | not measured | not measured | Three occurrences retained unique IDs and aggregate progress advanced only after the final block. |

Pass rate: `7/7`.

## Verdict

- **Regression: PASS.** Every expected-behavior check passed and no listed failure mode appeared.
- **Verification:** 121 tracker tests, 38 schema-contract tests, and 28 shared calendar-rendering tests passed.
- **Efficiency:** not measured because the opt-in metrics hooks were not available.
