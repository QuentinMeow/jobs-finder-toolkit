# Handoff records every folder it creates — because only the owner can delete one

- **Status**: decided
- **Date**: 2026-08-02
- **Decided by**: owner

## Context

`handoff.py` appends each posting it scaffolds to the append-only applications skip-log
(`config.applications_jsonl_path()`) as the last step of building the folder. Before that, only
status *transitions* were recorded, so a folder created and deleted before any `--sync-log` left no
trace and the next search re-surfaced the posting as fresh.

One edge is not the code's to decide. A scaffold run ends three ways: clean; a location outside
`config.location_policy()` (the folder is left on disk on purpose, with instructions to delete it
or rerun); or not draftable (a skipped or failed JD fetch, or `meta.yaml` gaps). **In both non-zero
cases the folder exists.** Is that posting "considered"?

The question is the owner's because the log is append-only and authoritative. Recording a posting
is permanent: if an abandoned scaffold is deleted five minutes later, the posting stays skipped
forever unless the owner appends a tombstone by hand. There is no self-healing path, by design —
that is the same property that makes the log worth having.

## Decision

**Every posting whose folder handoff actually created is recorded, whatever exit code the run
returned** — including the location-mismatch exit and the incomplete-scaffold exit. Nothing is
recorded when no folder was created. On a non-zero exit the tool prints the `--forget-log` un-skip
command with the URL already filled in.

The answer is **conditional, and the condition is the whole argument**. In the owner's words:
*"Option A — conditional on two things being true: if the code and agent behaviour never delete an
application folder, and if a deleted folder therefore means* I *deleted it, then Option A is right,
because my deleting a folder truly means I don't want to consider that posting any more."*

Both conditions were verified before this was folded:

- **No production code deletes an application folder.** Every `rmtree`/`unlink` under `automation/`
  and `skills/` that is not a test targets the postings cache, store debris, vendored copies,
  generated symlinks, temporary files, an export destination, or the reconciler's own queue file.
  No module that resolves `config.applications_root()` deletes anything beneath it; the only
  `rmtree` of an application folder is in tests, against temp fixtures.
- **Agents are forbidden from deleting one**, by the "Agents never delete owner data" guardrail in
  `AGENTS.md`: application folders "are removed by the **user only** — never by an agent, under any
  condition".

So a missing application folder is always an owner decision, and the skip-log is reading that
decision correctly rather than guessing at it.

## Alternatives considered

- **Record only a clean scaffold (exit 0)** — nothing is skipped that was never really worked on,
  but it reopens the reported bug for exactly the folders it was reported about: a folder the tool
  just told you not to draft is the one you delete. It also makes "is this posting skipped?" depend
  on an exit code nothing on disk records, and re-creates the disappearing-skip behaviour the
  append-only format was adopted to end.
- **Record it, then re-surface it with a `provisional` marker** — best of both in principle; costs a
  new field in an authoritative file, a new branch in every reader, and a "surface it anyway" path
  the skip-log exists in order not to have.

## Consequences

- An abandoned scaffold becomes a permanent skip. The cost is bounded by the printed,
  argument-filled `--forget-log` command; it is not otherwise recoverable.
- **The condition is load-bearing and must stay true.** If any code path ever deletes under
  `config.applications_root()`, or the never-delete guardrail is relaxed for agents, this decision's
  premise is gone and the rule must be revisited — a folder that disappeared without the owner's
  say-so would silently and permanently skip a posting the owner still wanted. Pinning the premise
  is filed as `tasks/0_backlog/2026-08-02-pin-the-never-delete-an-application-folder-premise/`.
- One live defect already pushes against the premise:
  `tasks/0_backlog/2026-08-01-forget-log-tells-the-agent-to-delete-owner-data` records that the
  skip-log's own remediation message tells an agent to delete an application folder. That is now
  more than an instruction conflict — it is a threat to the reasoning this decision rests on.
- **Revisit if** either condition stops holding. Nothing else about the rule needs re-deciding.
