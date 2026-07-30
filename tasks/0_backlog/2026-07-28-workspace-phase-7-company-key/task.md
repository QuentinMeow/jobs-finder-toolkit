# Workspace phase 7 — one owner-owned company key

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Replace four competing alias registries with one index, and key every application to it.

## Context

Detail in [the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) under "Phase 7". 242 application folders carry 213
distinct free-text company strings; `registry.canonical()` resolves only 119, leaving 94
unresolvable — 44% (re-measured 2026-07-29, unchanged). Live split shapes already in the data
(real instances are in the private tree; naming them here would publish the owner's application
list): `<Name>`/`<Name> Ltd.`, `<Name>`/`<Name> (<LegalEntity>)`, `<Name>`/`<Name> AI`, and two
folders for one employer under different slug prefixes.

`kind` distinguishes an employer from an interview-running firm; `parent`
handles subsidiaries and JVs.

The new reconciler check (every `company_key` resolves; no two keys share an alias) belongs in
`CHECKS` **with an entry in `CHECK_ROOTS`** (`automation/reconcile/reconcile.py:265,281`), so it
no-ops in the published tree like every other process check. A check that hard-fails without the
private overlay turns the exported repo's CI red.

Also here: `skills/email-assistant` emits `durable: true|false` per `timeline.md` entry plus a
`promote` command. Without it the durable/disposable split degrades every time the assistant
runs, since it rewrites those files wholesale. There are 135 `notes.md` files to rename to
`timeline.md`.

**This is the highest-leak-risk phase in the plan.** Its subject matter is literally the owner's
application list, and the review gate caught exactly that leak once already (commit `ef2d0a3`
redacted it out of tracked planning docs). Every commit needs a review-ledger row (execution
plan, rule 4), the branch ends with a ledger-only commit, and the advisory company detector is
more likely to fire here than anywhere else — expect `reviewed_by: human` rows. Never let a real
company name reach a public file, a commit message, or a PR description.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phase 5 merged, and the key-assignment approach decided (filed non-blocking as
`2026-07-28-company-key-assignment-approach`; default is one proposal PR). **Not met as of
2026-07-29** — phase 5 is not started, and it is what creates `companies/<key>/`. Phases 0, 3
and 4 are merged; 1, 2 and 5 are not.

## Definition of done

- [ ] `companies/_index.yaml` exists and is the only alias registry
- [ ] `company_key` added to 242 `meta.yaml` files
- [ ] The other three alias registries generated from it or deleted
- [ ] Reconciler: every key resolves, no two keys share an alias; the check is in `CHECK_ROOTS`
      so it no-ops in the published tree
- [ ] The email assistant emits `durable:` and `promote` moves flagged entries
- [ ] Review-ledger rows for every commit; zero company names in public files, commit messages
      or PR descriptions
- [ ] Gate command clean
