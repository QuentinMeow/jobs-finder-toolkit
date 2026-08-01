# email-assistant and interview-calendar give different write orders for the same interview event

- **Priority**: P2 (someday)
- **Area**: email
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**:

## Goal

One confirmed interview email produces the same end state whichever skill the agent is holding: a
local tracker entry and a remote Outlook event that know about each other.

## Context

`skills/interview-calendar/SKILL.md:36` makes the local write a precondition:

> 5. Reconcile Outlook Calendar from that validated local/evidence state.

and `:178` — "Local tracker write failure: do not attempt the Outlook write."

`skills/email-assistant/SKILL.md:232-249` writes the remote event directly. The section covers the
Outlook capability, the search-first dedup, the no-external-attendees rule and marking `notes.md`
`calendar: confirmed` (`:241`) — but never mentions `calendar.md`, `config.calendar_path()`, or
`status.py --update-progress --state scheduled`.

That matters because the local entry and its `progress.calendar_item` id are created **only** by
`--update-progress` (`skills/application-tracker/SKILL.md:454`; `--state scheduled` requires
`--starts-at` and `--timezone`). Following email-assistant alone leaves a remote event with no local
record, which `status.py --check-calendar` then reports as drift — the exact condition
interview-calendar exists to prevent. `skills/ask-me-anything/SKILL.md:186-187` also routes Outlook
Calendar work to interview-calendar, so the email skill's section is the odd surface out.

Counter-argument considered: the two sections agree on the event itself — same title shape, same
search-first dedup, same attendee rule — so email-assistant looks like a compatible subset. It is
not, on ordering: one doc makes the local write blocking and the other omits it, and the same email
therefore lands two different end states.

The likely fix is the cheap one: `email-assistant`'s calendar section states the local-first order
and defers to `interview-calendar` for anything beyond a single confirmed event, rather than
duplicating the procedure. Both are `SKILL.md` routine-path edits, so
`evals/canaries/email-assistant.yaml` and `evals/canaries/interview-calendar.yaml` run and are
recorded per `evals/README.md`.

## Definition of done

- [ ] `skills/email-assistant/SKILL.md`'s calendar section names the local write
      (`status.py --update-progress --state scheduled`) as the step that precedes the Outlook write,
      or defers the whole flow to `interview-calendar`.
- [ ] A confirmed-interview email walked through either skill ends with a local entry, a remote
      event, and `status.py --check-calendar` reporting no drift.
- [ ] email-assistant + interview-calendar canaries run and recorded per `evals/README.md`.
