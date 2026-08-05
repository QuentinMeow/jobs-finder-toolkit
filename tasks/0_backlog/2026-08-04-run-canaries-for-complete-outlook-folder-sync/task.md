# Run the interview, email, calendar, and tracker canaries for the publication stack

- **Priority**: P1 (this round)
- **Area**: email
- **Source**: eval-gate debt from the `complete-outlook-folder-sync` PR, 2026-08-04
- **Claimed-by**:

## Goal

The behavioral canaries for `behavioral-interview-prep`, `email-assistant`, `interview-calendar`,
and `application-tracker` run in fresh sessions against the publication stack, and the runs are
recorded under `evals/results/`.

## Context

The complete-Outlook-folder-sync change edits two skill instruction surfaces —
`skills/email-assistant/SKILL.md` and `skills/interview-calendar/SKILL.md` — so it is inside
the risk-based eval gate (`evals/README.md`). The edits are behavioral, not mechanical: an
unqualified `sync-store` now discovers every Outlook folder and captures all existing mail
instead of four hardcoded folders over a 30-day window, and both SKILL.md files were updated
to describe the new default and the explicit `--days` opt-in.

The change's own task folder
(`tasks/1_in-progress/2026-08-04-complete-outlook-folder-sync-by-default/`) carries this as the
one unchecked line in its definition of done. Its `verification.md` records the mechanical
evidence that *did* run — 93 email-assistant tests, 27 canonical mail tests, mail-safety and
vendoring checks, and a live 11-folder sync — but no behavioral canary.

The most recent recorded runs for both skills
(`evals/results/email-assistant-8a0253a-20260804-calendar-dashboard.md` and
`evals/results/interview-calendar-8a0253a-20260804-calendar-dashboard.md`) cover the
calendar-dashboard change at commit `8a0253a`, not this one.

Canary sets: `evals/canaries/behavioral-interview-prep.yaml`,
`evals/canaries/email-assistant.yaml` (edited by the same change), and
`evals/canaries/interview-calendar.yaml`.

On 2026-08-05 the calendar behavior also changed materially: Sent Items became authoritative for
retiring submitted scheduling actions; explicit sent availability may become personal pending busy
holds when the owner asks; every touch captures current time and reconciles live Outlook; Markdown
and HTML render week → day → event; organizer blocks with named subslots render once; and confirmed,
pending, and personal blocks participate in overlap alerts. The application-tracker instruction
surface and canary set now cover the renderer/tooling side of that behavior, so its canaries join
this one debt item rather than creating a duplicate.

The lower rung of the same publication stack adds a chat-first behavioral-interview fast path and
changes the global repository boot/reporting exceptions that support it. That is also behavioral,
so the tip run must cover `behavioral-interview-prep` rather than leaving the lower rung's combined
state untested.

## Definition of done

- [ ] `behavioral-interview-prep` canaries run in a fresh session against the merged behaviour.
- [ ] `email-assistant` canaries run in a fresh session against the merged behaviour.
- [ ] `interview-calendar` canaries run in a fresh session against the merged behaviour.
- [ ] `application-tracker` canaries run in a fresh session against the merged behaviour.
- [ ] All runs recorded under `evals/results/` per `evals/README.md`, model-pinned, with no
      large efficiency regression.
- [ ] The unchecked canary line in
      `tasks/1_in-progress/2026-08-04-complete-outlook-folder-sync-by-default/task.md` is closed
      or that task is moved to `4_done`.
