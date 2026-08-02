# Discover reply drafts outside Outlook's standard Drafts folder

- **Priority**: P1 (this round)
- **Area**: email
- **Source**: 2026-08-01 full-mailbox reconciliation
- **Claimed-by**:

## Goal

Keep every agent-created Outlook reply draft discoverable and represented in the raw email evidence
store even when Microsoft Graph assigns it a parent folder other than the standard Drafts folder.

## Context

An exact message read can return `isDraft: true` for a reply draft whose `parentFolderId` is not the
standard Drafts folder. The approved four-folder full sync and `/mailFolders/drafts/messages` then
omit that draft. A mailbox-wide `isDraft eq true` fallback is not safe by itself because Outlook
Notes also appear as draft messages, producing large false-positive inventories.

The repair must preserve the draft-only policy: verify exact known IDs before mutation, never add a
send capability, and avoid treating Notes or unrelated mailbox artifacts as email drafts. A likely
safe direction is a durable registry of draft IDs created by this CLI plus exact-ID hydration into
the raw evidence layer.

## Definition of done

- Agent-created reply draft IDs survive across sessions and remain discoverable regardless of
  their Graph parent folder.
- Raw-store refresh hydrates those exact verified drafts without classifying Outlook Notes as mail.
- Moving or sending a formerly registered draft reconciles its lifecycle without stale draft state.
- Provider, CLI-policy, raw-store, and mail-safety regressions pass with a nonstandard-parent
  fixture and an Outlook Notes false-positive fixture.
