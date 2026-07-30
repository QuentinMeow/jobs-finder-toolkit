# Re-measure phase 8's per-skill path counts before phase 8 starts

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: workspace phase 2, 2026-07-29 — [the phase-2 record](../../../docs/designs/workspace-restructure/execution-plan.md#merged-phase-2--public-side-cleanup)
- **Claimed-by**:

## Goal

Replace the obsolete phase-2 column in phase 8's per-skill table with a re-measurement, so the
phase-8 scope estimate describes files that exist.

## Context

[`tasks/0_backlog/2026-07-28-workspace-phase-8-instruction-surface/task.md`](../2026-07-28-workspace-phase-8-instruction-surface/task.md)
carries a table counting, per public `SKILL.md`, how many "phase-2 paths" and how many "phase-5
paths" it names. The same table is in
[the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md#phase-8--instruction-surface).
The phase-2 column counted occurrences of `automation/maintenance/`, `handbook/`, `design/`,
`roadmap/` and `tmp/` — headline rows `search-recall-audit` 19, `job-search` 15, `gardener` 11.

**Phase 2 has now run, so that whole column describes tokens that no longer exist.** It retired
`automation/maintenance/` from every skill and re-spelled `handbook|design|roadmap|tmp` as
`docs/handbook`, `docs/designs`, `docs/roadmap` and `local`. Phase 8's job was to update those
references; phase 2 already did. Whatever phase-8 work remains on the instruction surface is a
different, smaller set of edits than the table implies, and the estimate built on it is wrong in
the direction that matters — it over-states the work, so phase 8 could be scheduled as a large
phase when it is not.

The phase-5 column is untouched by this and still holds: `0_profile`, `interviews/`,
`job-search-profiles/` and `data/` all still move in phase 5.

Both surfaces carry the same table, so both get the same edit in the same commit — the plan and
the task file must not disagree about scope. The plan's copy is already flagged obsolete and
points here; that flag comes off when the numbers are replaced.

Do this **before** phase 8 is claimed, not during: the point is a scope estimate the phase can be
planned against, and a phase that re-measures its own scope after starting has already committed
to it.

## Definition of done

- [ ] The per-skill table is re-measured against the tree at the time of measurement, with the
      measuring command recorded beside it so the next person can repeat it
- [ ] The phase-2 column is either replaced by "paths still stale after phase 2" or removed with
      a one-line note saying phase 2 closed it — whichever the measurement supports
- [ ] The same table in
      [the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md#phase-8--instruction-surface)
      is updated in the same commit and its "obsolete" flag removed
- [ ] Phase 8's blocking-precondition paragraph reflects the re-measured scope
