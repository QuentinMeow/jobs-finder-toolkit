# `--forget-log`'s only remedy tells the agent to delete an application folder

- **Priority**: P1 (this round)
- **Area**: tracker
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**: agent, session 2026-08-02 (branch `fix/never-delete-application-folder`)

## Goal

The duplicate-handoff chain has an escape hatch an agent is allowed to take, so the tool never
instructs the one action `AGENTS.md` forbids outright.

## Context

`AGENTS.md:232-235`:

> **Agents never delete owner data**: application folders, interview prep, company dossiers, and
> store payloads are removed by the **user only** — never by an agent, under any condition,
> including cleanup, migration, or a rejected application. Propose a deletion in
> `message-queue/needs-human/` and stop; never perform one.

`skills/application-tracker/scripts/status.py:2647` prints, as the sole remediation:

```
folder.
  Move or delete the application folder first, then re-run …
```

The path is reachable from a documented workflow, not hypothetical. `handoff.py:1435-1437` refuses
an explicit `--select` duplicate; `_report_explicit_duplicate` (`handoff.py:386`) prints
`status.py --forget-log <target>`; `_duplicate_reason` (`handoff.py:321-356`) fires on live
application folders as well as on skip-log rows; and `forget_log` (`status.py:2640-2650`) refuses
exactly that case with the message above. "Move" is not an out either — `LIVE_STATUS_DIRS`
(`handoff.py:156-158`) covers all five status folders, so only removing the folder from the
applications tree clears the duplicate.

`skills/job-search/SKILL.md:218-219` states the intended rule correctly: "the undo for a skip-log
row is a tombstone, never deleting a folder."

**2026-08-02 — this is now load-bearing beyond the instruction conflict.** The owner's answer on
whether handoff records a non-clean scaffold (`memory/decisions/handoff-records-every-folder-it-creates.md`)
is conditional on nothing but the owner ever deleting an application folder. A message that routes
an agent into deleting one attacks that premise directly, so fixing it protects a decision as well
as a guardrail.

The guardrail should win, so the fix is a remedy the agent can actually perform — e.g. `--forget-log`
accepting the live-folder case behind an explicit flag, or the message routing the agent to
`message-queue/needs-human/` for an owner deletion the way `AGENTS.md` prescribes. Picking between
those is a behaviour change in `status.py`, which is why this is filed rather than reworded.

## Definition of done

- [x] The `forget_log` refusal no longer instructs deletion of an application folder; it names an
      action an agent may take under `AGENTS.md:232-235`.
- [x] The duplicate chain (`handoff.py` explicit-`--select` refusal → `--forget-log`) terminates in
      that action, verified by running it against a scratch applications tree.
- [x] `grep -rn 'delete the application folder' skills/ automation/` returns nothing addressed to an
      agent.

## Resolution (2026-08-02)

Message rewritten in place; the chain now terminates in "use the application that already
exists, and propose a removal in `message-queue/needs-human/` if it truly should go". The
opt-in-flag option was **rejected in code, with the reason recorded beside the branch**: a
tombstone appended over a live folder is rebuilt by the very next `--sync-log`, so the flag
would have bought exactly the silent no-op un-skip that branch exists to refuse.

A **second offender** turned up on the same sweep and is fixed here too:
`handoff.py`'s location-mismatch remedy opened with "delete the folder (<path>)" — the folder
is deliberately left on disk for review, not as a deletion cue. Both messages now name the
guardrail explicitly, and both are pinned by a test. Evidence in `verification.md`.
