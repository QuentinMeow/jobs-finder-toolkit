# Eval result — interview-calendar

| Field | Value |
|-------|-------|
| Skill | `interview-calendar` |
| Canary set | `evals/canaries/interview-calendar.yaml` |
| Run kind | regression pre-merge |
| Run commit | `a4e5b3d3fbd5` plus uncommitted working tree |
| Anchor commit | `none` |
| Model version | `gpt-5.6-sol` (high reasoning) |
| Config mode | examples fallback (config.yaml unset) |
| Date | `2026-08-01` |
| Judge | manual Sol-high agent + rubric |

```eval-pin v1
skill interview-calendar
pin sha256=f95dbaa0f09e43fd bytes=11974 path=skills/interview-calendar/SKILL.md
pin sha256=dbffedf0a30ec445 bytes=6343 path=evals/canaries/interview-calendar.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `ic-proposed-availability-is-not-confirmed` | 1 | n/a | n/a | n/a | Booking todo only; no inferred event. |
| `ic-existing-invitation-wins` | 1 | n/a | n/a | n/a | Organizer invitation remains canonical; no mirror. |
| `ic-confirmed-reschedule-converges` | 1 | n/a | n/a | n/a | One personal event moves; superseded local history retained. |
| `ic-all-mail-company-view-with-ambiguous-role` | 1 | n/a | n/a | n/a | Four-folder evidence and unresolved company-scope update preserved. |
| `ic-split-day-onsite-preserves-every-occurrence` | 1 | n/a | n/a | n/a | Three organizer/local blocks, including two same-day, remain independent. |

Pass rate: `5/5`.

## Verdict

- **Regression:** PASS. Search-first duplicate safety, organizer precedence, independent
  split-day occurrences, and final-occurrence aggregation all passed.
- **Efficiency vs baseline:** not measured; this was a read-only manual rubric run with no isolated
  metrics log.
