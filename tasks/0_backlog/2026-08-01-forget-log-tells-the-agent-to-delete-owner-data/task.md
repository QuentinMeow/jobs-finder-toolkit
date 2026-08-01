# `--forget-log`'s only remedy tells the agent to delete an application folder

- **Priority**: P1 (this round)
- **Area**: tracker
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**:

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

The guardrail should win, so the fix is a remedy the agent can actually perform — e.g. `--forget-log`
accepting the live-folder case behind an explicit flag, or the message routing the agent to
`message-queue/needs-human/` for an owner deletion the way `AGENTS.md` prescribes. Picking between
those is a behaviour change in `status.py`, which is why this is filed rather than reworded.

## Definition of done

- [ ] The `forget_log` refusal no longer instructs deletion of an application folder; it names an
      action an agent may take under `AGENTS.md:232-235`.
- [ ] The duplicate chain (`handoff.py` explicit-`--select` refusal → `--forget-log`) terminates in
      that action, verified by running it against a scratch applications tree.
- [ ] `grep -rn 'delete the application folder' skills/ automation/` returns nothing addressed to an
      agent.
