# Eval result — interview-calendar

| Field | Value |
|-------|-------|
| Skill | `interview-calendar` |
| Canary set | `evals/canaries/interview-calendar.yaml` |
| Run kind | regression pre-merge |
| Run commit | `d975a530ee61` plus the uncommitted availability-projection working tree |
| Anchor commit | `none` |
| Model version | `gpt-5.6-sol` |
| Config mode | examples fallback; fictional fixtures only, with no private-overlay or live connector access |
| Date | `2026-08-07` |
| Judge | manual, against every `expected_behavior` bullet in the canary set |

```eval-pin v1
skill interview-calendar
pin sha256=270ea7ab8b1d3ec9 bytes=16921 path=skills/interview-calendar/SKILL.md
pin sha256=6133ac7a5ede00da bytes=8339 path=evals/canaries/interview-calendar.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `ic-proposed-availability-is-not-confirmed` | 1 | not measured | not measured | not measured | Kept the booking request at `booking_required`; created no event or hold. |
| `ic-existing-invitation-wins` | 1 | not measured | not measured | not measured | Reused the organizer invitation and proposed no personal mirror. |
| `ic-confirmed-reschedule-converges` | 1 | not measured | not measured | not measured | Moved one personal event and retained superseded local history. |
| `ic-all-mail-company-view-with-ambiguous-role` | 0 | not measured | not measured | not measured | The first run assigned the title-only receipt to one role. After tightening the skill, three fresh reruns kept it company-level, but still omitted the required `store-coverage --in-progress-applications` plus recruiter-domain/thread-alias audit and did not demonstrate the complete time-captured, byte-stable Markdown/HTML view. |
| `ic-split-day-onsite-preserves-every-occurrence` | 1 | not measured | not measured | not measured | Preserved three organizer events and three ordered local occurrences, including two on one day. |
| `ic-sent-availability-holds-and-conflicts` | 1 | not measured | not measured | not measured | Kept submitted windows pending, preserved priority, and surfaced both conflicts in both views. |

Pass rate: **5/6**.

## Verdict

- **Regression: FAIL.** `ic-all-mail-company-view-with-ambiguous-role` did not pass every rubric
  check. This result blocks merge until a fresh run demonstrates both the complete full-store
  coverage audit and the time-captured, human-first, byte-stable calendar verification path.
- **Efficiency vs baseline:** not measured. Fresh subject contexts did not expose comparable token,
  wall-clock, or tool-call counters.
