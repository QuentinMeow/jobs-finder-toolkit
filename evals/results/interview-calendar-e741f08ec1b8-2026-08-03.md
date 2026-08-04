# Eval result — interview-calendar

| Field | Value |
|-------|-------|
| Skill | `interview-calendar` |
| Canary set | `evals/canaries/interview-calendar.yaml` |
| Run kind | regression pre-merge |
| Run commit | `e741f08ec1b8` plus uncommitted working tree |
| Anchor commit | `none` |
| Model version | `gpt-5.6-terra` |
| Config mode | isolated fictional fixture; private overlay not used |
| Date | `2026-08-03` |
| Judge | `gpt-5.6-terra` with `evals/rubrics/judging.md` |

```eval-pin v1
skill interview-calendar
pin sha256=77bda07df5b16b98 bytes=12529 path=skills/interview-calendar/SKILL.md
pin sha256=9648b398690b603f bytes=6628 path=evals/canaries/interview-calendar.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `ic-proposed-availability-is-not-confirmed` | 1 | not measured | not measured | not measured | Proposed windows remained an action; no scheduled event was invented. |
| `ic-existing-invitation-wins` | 1 | not measured | not measured | not measured | The organizer event remained canonical and no mirror was created. |
| `ic-confirmed-reschedule-converges` | 1 | not measured | not measured | not measured | One replacement remained and the old occurrence was preserved as superseded. |
| `ic-all-mail-company-view-with-ambiguous-role` | 1 | not measured | not measured | not measured | Four-folder evidence stayed company-scoped; no event appeared without a confirmed occurrence. |
| `ic-split-day-onsite-preserves-every-occurrence` | 1 | not measured | not measured | not measured | Three blocks, including two on one day, render as three aligned rows and retain unique IDs. |

Pass rate: `5/5`.

## Verdict

- **Regression: PASS.** Every expected-behavior check passed and no listed failure mode appeared.
- **Verification:** 28 progress-calendar tests and 28 shared calendar-rendering tests passed.
- **Efficiency:** not measured because the opt-in metrics hooks were not available.
