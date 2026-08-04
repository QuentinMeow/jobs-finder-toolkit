# Run the email-assistant and interview-calendar canaries for complete Outlook folder sync

- **Priority**: P1 (this round)
- **Area**: email
- **Source**: eval-gate debt from the `complete-outlook-folder-sync` PR, 2026-08-04
- **Claimed-by**:

## Goal

The behavioral canaries for `email-assistant` and `interview-calendar` run in fresh sessions
against the complete-folder-sync behaviour, and the runs are recorded under `evals/results/`.

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

Canary sets: `evals/canaries/email-assistant.yaml` (edited by the same change) and
`evals/canaries/interview-calendar.yaml`.

## Definition of done

- [ ] `email-assistant` canaries run in a fresh session against the merged behaviour.
- [ ] `interview-calendar` canaries run in a fresh session against the merged behaviour.
- [ ] Both runs recorded under `evals/results/` per `evals/README.md`, model-pinned, with no
      large efficiency regression.
- [ ] The unchecked canary line in
      `tasks/1_in-progress/2026-08-04-complete-outlook-folder-sync-by-default/task.md` is closed
      or that task is moved to `4_done`.
