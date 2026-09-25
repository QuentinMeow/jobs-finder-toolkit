# `sync-store --full` can leave the Inbox watermark behind and the store hard-stale

- **Priority**: P1 (this round)
- **Area**: email
- **Source**: Full-sync freshness diagnostic

## Goal

Make an email-store sync leave every folder's stored watermark at the live watermark, so a
completed sync never leaves `store-staleness` reporting `STORE STALE — sync broken` and blocking
`store-search` / `store-review` with exit 2.

## Context

Observed behavior, with mailbox-specific values omitted:

1. A delta sync completed successfully, but a subsequent store search reported that the provider watermark was newer than the stored Inbox watermark.
2. A full sync also completed successfully while the Inbox watermark remained behind.
3. A later delta sync imported additional messages and restored freshness.

This does not establish the cause. The watermark may be captured before a long-running scan finishes, or a concurrent read/token-refresh interaction may be involved. Reproduce first without concurrent mailbox commands and compare folder watermarks captured before and after each scan. Preserve the fail-closed freshness check.

Canonical code is `automation/shared/mail/` (vendored into `skills/email-assistant/scripts/_vendor/mail/`).
The user-visible cost is that the skill's own store-first workflow fails closed and the session has
to fall back to the bounded live read, which is slower and covers a narrower window.

## Definition of done

- [ ] A regression test reproduces a completed sync leaving a folder watermark behind the provider
      watermark, and fails before the fix.
- [ ] After `sync-store --full` on a mailbox with mail newer than the stored watermark,
      `store-staleness` reports no stale folder and `store-search` exits 0.
- [ ] Either concurrency is proven not to be the cause, or concurrent read-only commands during a
      sync are shown safe (or made safe).
- [ ] Draft-only route safety holds: `automation/shared/mail/check_mail_safety.py --consumer skills/email-assistant/scripts` and the email-assistant unit suite pass.
