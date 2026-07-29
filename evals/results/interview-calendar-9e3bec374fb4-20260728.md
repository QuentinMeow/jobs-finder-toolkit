# Eval result — interview-calendar

| Field | Value |
|-------|-------|
| Skill | `interview-calendar` |
| Canary set | `evals/interview-calendar/canaries.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `9e3bec374fb4` plus the uncommitted skill diff |
| Model version | `gpt-5` (Codex runtime, 2026-07-28) |
| Config mode | examples fallback / fictional fixtures; no live writes |
| Date | `2026-07-28` |
| Judge | manual against each canary rubric |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `ic-proposed-availability-is-not-confirmed` | 1 | not captured | not captured | 0 live writes | Kept the request as `booking_required`; created no Outlook event and invented no selected time. |
| `ic-existing-invitation-wins` | 1 | not captured | not captured | 0 live writes | Used exact time plus link/role evidence; kept the organizer invitation and created no duplicate. |
| `ic-confirmed-reschedule-converges` | 1 | not captured | not captured | 0 live writes | Updated the one personal event, preserved local superseded history, and required a post-write duplicate search. |
| `ic-all-mail-company-view-with-ambiguous-role` | 1 | not captured | not captured | 0 live writes | Required one complete four-folder coverage pass across company, roles, explicit/URL job IDs, domains, aliases, bodies, and participants; retained ambiguous evidence at company scope, rendered both roles once, and created no event from an availability receipt. |

Pass rate: `4/4`.

## Verdict

- **Regression:** PASS. All behavioral and safety checks passed; the public email suite passed
  `67/67`, the tracker/calendar suite passed `26/26`, and mail-safety plus vendored-parity checks
  passed.
- **Efficiency vs baseline:** No prior baseline exists for this new skill; token and wall-clock
  metrics were not exposed by the fresh-context subagent runs. Coverage hydrates the store once and
  evaluates independent families in memory, followed only by exact-message reads.
