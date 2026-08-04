# Make complete Outlook folder sync the default

- **Priority**: P1 (this round)
- **Area**: email
- **Source**: owner session 2026-08-04
- **Claimed-by**: Codex (2026-08-04 session)

## Goal

Make an unqualified email-store sync discover every Outlook mail folder and capture all existing
mail, while keeping an explicit bounded-window option and the permanent draft-only safety boundary.

## Context

The prior implementation hardcoded Inbox, Sent Items, Drafts, and Deleted Items and defaulted to a
30-day window. That silently excluded Archive, Junk, nested folders, and other folders Graph exposes.
Canonical code lives under `automation/shared/mail/` and is vendored into the email-assistant.

## Definition of done

- [x] The Outlook provider recursively discovers the live folder tree and uses stable opaque keys.
- [x] `sync-store` defaults to all existing mail; `--days` is an explicit opt-in bound.
- [x] Store sync, freshness, search, and coverage operate over every discovered folder.
- [x] Draft-only route safety, vendoring, and the relevant automated suites pass.
- [ ] The behavioral email-assistant and interview-calendar canaries run in fresh sessions and are recorded.
