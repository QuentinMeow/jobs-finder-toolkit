# Eval result — interview-calendar

| Field | Value |
|-------|-------|
| Skill | `interview-calendar` |
| Canary set | `evals/canaries/interview-calendar.yaml` |
| Run kind | regression pre-merge |
| Run commit | `8a0253ab3c34` plus uncommitted working tree |
| Anchor commit | `none` |
| Model version | `GPT-5.6 Terra` |
| Config mode | examples fallback (config.yaml unset) |
| Date | `2026-08-04` |
| Judge | GPT-5.6 Terra rubric audit with deterministic public-fixture checks |

```eval-pin v1
skill interview-calendar
pin sha256=d718c1569df8afbc bytes=13159 path=skills/interview-calendar/SKILL.md
pin sha256=9648b398690b603f bytes=6628 path=evals/canaries/interview-calendar.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `ic-proposed-availability-is-not-confirmed` | 1 | not measured | not measured | not measured | Booking action recorded without choosing a time or creating an event. |
| `ic-existing-invitation-wins` | 1 | not measured | not measured | not measured | Organizer invitation identity and no-duplicate behavior passed. |
| `ic-confirmed-reschedule-converges` | 1 | not measured | not measured | not measured | Personal-event update, one-event verification, and superseded history passed. |
| `ic-all-mail-company-view-with-ambiguous-role` | 1 | not measured | not measured | not measured | Four-folder coverage, unresolved scope, unified view, and no-event boundary passed. |
| `ic-split-day-onsite-preserves-every-occurrence` | 1 | not measured | not measured | not measured | Three organizer blocks, three local IDs, separate rows, and lifecycle reduction passed. |

Pass rate: `5/5`.

## Verdict

- **Regression:** PASS. Every rubric bullet passed; no failure mode was observed.
- **Efficiency vs baseline:** not measured. No per-run metrics hook was available.

## Follow-up rerun — Do now first

- **Run commit:** `76e57052d4e6`
- **Model:** `GPT-5.6 Terra`
- **Verdict:** PASS, `5/5`. The agenda checks verified **Do now** before **Upcoming interviews**, separate occurrence rows, complete unresolved evidence, and no Outlook event from proposed availability.
- **Deterministic evidence:** calendar core `30/30`; progress/calendar `30/30`; full tracker discovery exited 0.
- **Efficiency:** not measured.

```eval-pin v1
skill interview-calendar
pin sha256=71e6ae46afc8e2fa bytes=13078 path=skills/interview-calendar/SKILL.md
pin sha256=9648b398690b603f bytes=6628 path=evals/canaries/interview-calendar.yaml
```
