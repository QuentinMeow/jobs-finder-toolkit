# Workspace phase 7 — one owner-owned company key

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Replace four competing alias registries with one index, and key every application to it.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 7". 242 application folders carry 213
distinct free-text company strings; `registry.canonical()` resolves only 119 — 44%
unresolvable. Live splits already in the data: `Canonical`/`Canonical Ltd.`,
`Cursor`/`Cursor (Anysphere)`, `Arize`/`Arize AI`, `Palantir`/`Palantir Technologies`.

`kind` distinguishes an employer from an interview-running company like Karat; `parent`
handles subsidiaries and JVs.

Also here: `skills/email-assistant` emits `durable: true|false` per `timeline.md` entry plus a
`promote` command. Without it the durable/disposable split degrades every time the assistant
runs, since it rewrites those files wholesale.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phase 5 merged, and the key-assignment approach decided (filed non-blocking as `2026-07-28-company-key-assignment-approach`; default is one proposal PR).

## Definition of done

- [ ] `companies/_index.yaml` exists and is the only alias registry
- [ ] `company_key` added to 242 `meta.yaml` files
- [ ] The other three alias registries generated from it or deleted
- [ ] Reconciler: every key resolves, no two keys share an alias
- [ ] The email assistant emits `durable:` and `promote` moves flagged entries
- [ ] Gate command clean
