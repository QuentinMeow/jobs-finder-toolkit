# Handover — install-git-ws-alias

- **Date**: 2026-08-25
- **Task(s)**: 2026-08-25-install-git-ws-alias

## What happened

- The dashboard was already on public `main`, but its `git ws` shorthand existed only in one laptop's untracked `.git/config`; the fix now teaches the tracked bootstrap to install that repository-local alias on every device.
- The bootstrap leaves a conflicting user-owned alias untouched and its health check reports the conflict instead of claiming the checkout is ready.
- Focused tests pass. Final CI-style verification, commit, push, PR creation, and CI confirmation remain in flight.

## Where things stand

- Implementation is on `codex/install-git-ws-alias`; the task remains in progress until the published commit passes the clean-checkout gate run and the PR is open.

## Decisions made for you

- Kept `automation/workspace/status.py` as the portable command and made the existing bootstrap own only the missing local alias. Undoing this is a small bootstrap/docs revert; no user data is migrated.
- Preserved any pre-existing `alias.ws` value because overwriting a user-owned Git command would be surprising. A conflict requires manual resolution and is visible in `--check`.

## If X then Y

- On the other laptop, pull the PR after merge and run `.venv/bin/python automation/bootstrap_overlay.py` once; Git cannot acquire `.git/config` entries from a pull alone.

## Dead ends

- No repository prompt fragment was identified as the Codex filter trigger. Local logs show a server-side rejection on the follow-up request after long instruction and memory reads, so the task continued with smaller prompts instead of changing an unproven source.

## Needs your attention

- [May the retired private company root be deleted after its ignored files were copied?](../../../message-queue/needs-human/decisions/retire-copied-private-companies-root.md) — **Why this matters:** the retired root keeps a duplicate recovery copy and can confuse manual browsing. **If you do nothing:** nothing is deleted and the current person-first location remains the only path tooling uses.
- 43 pending · top: `retire-copied-private-companies-root` — silence keeps the duplicate recovery copy and loses no data.
