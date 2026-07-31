# Download Outlook mail into the local store safely

- **Priority**: P1 (after the provider contract)
- **Area**: email
- **Source**: `docs/designs/application-progress-calendar/execution-plan.md` Stage 3
- **Claimed-by**: codex root session 2026-07-22

## Goal

Ship reliable, privacy-bounded Inbox + Sent + Drafts synchronization as the
substrate for local email review and progress reconciliation.

## Context

Implement the sync contract in
`docs/designs/raw-data-layer/04-email-download-categorization.md`: full
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

## Held in `3_in-review`, 2026-07-31 — what is missing

A bookkeeping pass promoted six finished in-review folders to `4_done` and deliberately left this
one behind. PR #63 is merged and the store is in daily use; the gap is evidence:

- **Bullet 2 records the opposite of what it asserts.** It asks that an *induced wedged* sync
  produce the hard `STORE STALE` banner. The folder records only a healthy run
  (`store_stale: false`) — a green light where a red one was the assertion.
- **Bullet 4's planted-content policy test is not recorded** — only the public leak guard is, and
  the leak guard is the other half of that bullet, not this half.
- **Bullet 5 has no evidence of any kind.**
- The six named synthetic scenarios in bullet 1 are covered only by an aggregate
  `Ran 55 tests ... OK`, which does not show that those six ran.
- `verification.md` is the only one in the set with no branch/commit/date header, so none of the
  above can be pinned to a tree state.

Promoting this folder would assert evidence nobody gathered.
