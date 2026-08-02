# Pin the premise the skip-log rule rests on: nothing but the owner deletes an application folder

- **Priority**: P1 (this round)
- **Area**: tracker
- **Source**: owner decision 2026-08-02, recorded as `memory/decisions/handoff-records-every-folder-it-creates.md` (folded from the queue item handoff-records-non-clean-scaffolds, deleted in the folding commit — git history is the archive)
- **Claimed-by**: agent, session 2026-08-02 (branch `fix/never-delete-application-folder`)

## Goal

The claim "no code path deletes an application folder" is enforced by a check, not by a grep
somebody ran once. The skip-log's permanent-skip rule depends on that claim being true forever, so
it should fail loudly the day it stops being true.

## Definition of done

- [x] A test fails if any non-test module that resolves `config.applications_root()` removes a path
      beneath it (`shutil.rmtree`, `Path.unlink`, `os.remove`, `os.rmdir`, or an equivalent).
- [x] The check names `memory/decisions/handoff-records-every-folder-it-creates.md` in its failure
      message, so whoever trips it learns which decision they just invalidated rather than
      deleting the assertion.
- [x] `tasks/0_backlog/2026-08-01-forget-log-tells-the-agent-to-delete-owner-data` is resolved or
      explicitly sequenced against this one — its remediation message currently instructs an agent
      to do the thing this check exists to make impossible.

## Resolution (2026-08-02)

`automation/shared/tests/test_application_folder_never_deleted.py` — an AST guard, scoped to
the applications root rather than a tree-wide `rmtree` ban. Scope-aware taint from
`config.applications_root()` through assignments, `for` targets and module-level helpers that
return a tree path, plus a name backstop for a folder arriving as a function parameter (the
shape the taint pass cannot see). The failure message names the ADR and says not to delete the
assertion.

The premise was **re-verified** before the guard was written: the only non-test removal calls
under `automation/` and `skills/` target the postings cache, store debris, the export
destination and the reconciler's queue file. The one path-mutating call inside the tree is
`status.py:_move_application`'s `shutil.move` between two status folders — a documented
status transition, both endpoints inside the root, not a removal.

Sequencing held: the sibling task's message was fixed first, in the same branch, so the guard
never had to be merged over a live instruction telling an agent to do the forbidden thing.

## Context

The owner's answer to "should handoff record a posting whose scaffold came out incomplete?" was
yes — every folder handoff creates is recorded, whatever the exit code — **conditional** on code and
agents never deleting an application folder, so that a missing folder always means the owner
deleted it and does not want the posting reconsidered. Read the ADR for the full reasoning.

Both conditions were verified by hand on 2026-08-02 (a sweep of every `rmtree`/`unlink` under
`automation/` and `skills/`, plus the "Agents never delete owner data" guardrail in `AGENTS.md`).
A hand sweep is exactly as durable as the next refactor, and the failure it would miss is silent:
a posting the owner still wanted, permanently skipped, with no signal anywhere. The recorded rule
already says the premise is load-bearing; this task makes the repo say it too.

The scope is deliberately narrow. This is not a general "no deletes" rule — the toolkit legitimately
removes caches, store debris, vendored copies, generated symlinks and temporary files. The only
protected tree is the applications root.
