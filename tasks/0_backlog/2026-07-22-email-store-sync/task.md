# Download Outlook mail into the local store safely

- **Priority**: P1 (after the provider contract)
- **Area**: email
- **Source**: `design/application-progress-calendar/execution-plan.md` Stage 3

## Goal

Ship reliable, privacy-bounded Inbox + Sent + Drafts synchronization as the
substrate for local email review and progress reconciliation.

## Context

Implement the sync contract in
`design/raw-data-layer/04-email-download-categorization.md`: full
resync with inventory-diff tombstoning first, delta second, per-account and
per-folder opaque state, provider-immutable message IDs, explicit move and
delete semantics, and the live staleness tripwire. Capture attachment
metadata only; never content.

Apply the decided git policy from
`memory/decisions/email-git-policy.md`: track only content-free index
headers and safe annotations; ignore raw, derived, message rows, and the
quoted-evidence sidecar.

## Definition of done

- Synthetic full-resync, delta replay, expired-token, move, delete, and
  multi-account tests pass idempotently.
- An induced wedged sync causes the hard `STORE STALE` banner and prevents
  a review from presenting itself as complete.
- Attachment bytes never land in the store; metadata does.
- A planted subject/body cannot reach a tracked path, proven by a policy
  test plus the public leak guard.
- Existing live Outlook review/drafting behavior remains available during
  the side-by-side period.
