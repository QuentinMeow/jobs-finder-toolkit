# Handover — git-ws-fresh-clone-followup

- **Date**: 2026-08-25
- **Task(s)**: 2026-08-25-install-git-ws-alias

## What happened

- Nothing is broken in the installer; the missing piece was fresh-clone onboarding.
- A clone from public `main` reproduced the reported failure before bootstrap and ran `git ws` successfully immediately after bootstrap.
- The fresh-clone and contributor setup now require the one-time checkout bootstrap and explain why clone or pull cannot install a repository-local Git alias.

## Where things stand

- The follow-up documentation and fresh-clone evidence are in review on `codex/fix-git-ws-onboarding`.

## Decisions made for you

- Kept the alias repository-local rather than changing every user's global Git configuration; this isolates behavior to this toolkit, and undoing it is a documentation-only change.
- Required one setup command per clone because Git does not run repository code during clone or pull; automatic installation would require user-global setup outside the repository.

## If X then Y

- If `git ws` still fails after bootstrap, run `python3 automation/bootstrap_overlay.py --check`; a conflicting user-owned alias is preserved and reported instead of overwritten.

## Dead ends

- A zero-step tracked alias is not possible: clone does not copy `.git/config`, and the repository root is not a standard executable search path.

## Needs your attention

- 43 public items pending · top: [retire-copied-private-companies-root](../../../message-queue/needs-human/decisions/retire-copied-private-companies-root.md) — why this matters: it is the only pending item whose wrong choice risks owner data; if you do nothing, the redundant recovery copy remains and nothing is deleted.
