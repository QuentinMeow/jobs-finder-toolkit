# Handover — never-delete-application-folder

- **Date**: 2026-08-02
- **Task(s)**: `2026-08-01-forget-log-tells-the-agent-to-delete-owner-data`,
  `2026-08-02-pin-the-never-delete-an-application-folder-premise` (both now in `tasks/4_done/`)

## What happened

- Nothing in the toolkit tells an agent to delete an application folder any more, and a test
  now stops that from coming back.
- Two live messages were routing agents into the one act `AGENTS.md` forbids outright.
  `--forget-log`'s live-folder refusal said "Move or delete the application folder first" —
  and it was the *only* exit from handoff's explicit-`--select` duplicate chain, so an agent
  that followed the tool's own instructions ended up deleting owner data. A near-variant
  sweep turned up a second one: handoff's location-mismatch remedy opened with "delete the
  folder (<path>)" for a folder it deliberately leaves on disk for review.
- Both now refuse on the owner's behalf, name the application that already exists, and route
  a real removal to `message-queue/needs-human/`. The chain was run end to end against a
  scratch applications tree; evidence is in the first task's `verification.md`.
- The premise those messages were attacking — "a missing application folder always means the
  OWNER removed it", which is what makes
  `memory/decisions/handoff-records-every-folder-it-creates.md` correct — was enforced by a
  hand sweep. It is now enforced by
  `automation/shared/tests/test_application_folder_never_deleted.py`, whose failure message
  names that decision so whoever trips it learns what they just invalidated.

## Where things stand

- On branch `fix/never-delete-application-folder`, committed, **not pushed and no PR opened**.
- The premise was independently re-verified before pinning: it holds today. Every non-test
  removal under `automation/` and `skills/` targets caches, store debris, the export
  destination or the reconciler's queue file.
- The guard is deliberately narrow — the applications root only, not a tree-wide `rmtree`
  ban — and its own teeth are tested in-file, plus proven by planting two real violations and
  watching it go red.
- No `SKILL.md`, `LESSONS.md` or `reference.md` was touched, so the eval gate does not apply.
- The ADR got a dated, additive status note; the decision itself is unchanged.

## Needs your attention

- Nothing new was filed this session.
- Standing, and worth knowing this work sits on top of it:
  `message-queue/needs-human/decisions/is-never-delete-owner-data-scoped-to-repo-local-products.md`
  asks whether "agents never delete owner data" also binds a live Outlook event. It does not
  affect anything here — both of its options keep application folders absolutely off-limits
  to an agent — but it is the item this branch's reasoning leans on.
