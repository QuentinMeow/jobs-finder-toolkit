# Build application email timelines and reconcile interview calendars

- **Priority**: P1 (this round)
- **Area**: email
- **Source**: User request, 2026-07-23
- **Claimed-by**: Codex /root

## Goal

Teach the email assistant to maintain action-first application notes with named contacts and one
concise timeline entry per matched email, then apply that workflow to the last 90 days of Outlook
mail and reconcile confirmed interview events to Outlook Calendar.

## Context

The public skill remains permanently draft-only for email. Mailbox bodies and personal details stay
in the private overlay; public skill and eval changes must use fictional examples. Calendar writes
must be backed by explicit date/time evidence, deduplicated against existing events, and performed
through the Outlook Calendar connector rather than by widening the email provider's Graph routes.

## Definition of done

- The email-assistant skill documents the canonical action/events, people, and email-timeline note
  format plus evidence and calendar-deduplication rules.
- The skill's tests, mail safety check, canaries, public leak check, and repository reconciler pass.
- Matched applications from the 90-day mailbox window have updated private notes and evidence-backed
  statuses; exact upcoming interview events are created or updated without duplicates.
