# Workspace phase 0 — make the four fail-open gates fail closed

- **Priority**: P0 (blocks work)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**: agent (session 2026-07-29)

## Goal

Repair the checks that currently report success while inspecting nothing, and add the
config accessors every later phase depends on. Independently valuable: ship it even if the
rest of the restructure is abandoned.

## Context

Twelve items, each verified against the code and specified with file/line references in
[the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 0". The headline defect: the publish leak guard
prints `OK … Safe to publish` with `active tokens: 0` over a file containing the owner's real
name, and `pre-push` warns then pushes anyway.

Two traps called out in the plan:
- **Do NOT** close the reconciler's missing-root no-op — it is documented behaviour and
  closing it turns the *published* repo's CI red. Add `--require-roots` instead.
- Gating the guard on an empty *union* of tokens does not fire; gate on the config-derived
  identity set.

Every `automation/shared/config.py` edit is a 5-file change: re-vendor with
`automation/vendoring/sync_vendored.py` and re-run its `--check`.

## Definition of done

- [ ] Plant a file containing a personal token → the guard **fails**
- [ ] Run the guard with no config → it **fails**; `--allow-unarmed` still passes
- [ ] Plant a real blacklist row → the job-search preflight honours it
- [ ] Delete a process root → `--require-roots` fails while plain `--check` passes
- [ ] `git add -f private/` is rejected by pre-commit
- [ ] All four public-skill lists derive from `SKILL.md` frontmatter and agree (10 skills)
- [ ] Export dry-run ships `automation/store/` and its own CI script list passes
- [ ] `sync_vendored.py --check` clean
