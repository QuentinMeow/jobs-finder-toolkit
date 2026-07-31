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
`2026-07-28-company-key-assignment-approach`; default is one proposal PR). **Met as of
2026-07-30, pending merge** — phase 5 is done and in review, and `companies/<key>/` exists
with 497 tracked files across 25 folders.

**Phase 5 hands this task a starting point it did not have.** The 25 company folder names are
now the de-facto key set: every one of them already holds that company's research, coding and
product-sense material, and the 19 company-prefixed behavioural files were routed by matching
their prefix against those same names. So `_index.yaml` is not being derived from scratch —
it is being written down for 25 keys that already exist on disk, and then reconciled against
the 213 free-text company strings in `meta.yaml`. Re-measure that 213/119 pair before quoting
it: the folder count has drifted and the ratio was not re-derived with it.

## Definition of done

Evidence for every box is in `verification.md` beside this file. Three boxes changed meaning once
the code was read; each says why.

- [x] `companies/_index.yaml` exists and is the only **owner-owned** alias registry — 222 keys,
      265 distinct names, no two keys sharing one. It resolves **214/214** of the company strings
      the applications carry, against the public resolver's 119/214.
- [ ] ~~`company_key` added to 242 `meta.yaml` files~~ → **split out as 7b** (and the count was
      243, not 242). Held until the owner answers seven judgement calls: settling the keys before
      243 files point at them is cheaper than re-pointing 243 files afterwards.
- [x] ~~The other three alias registries generated from it or deleted~~ → **not implementable, and
      none were.** The public one cannot be generated from a private source (the exporter ships
      tracked files, CI has no overlay, and a public file derived from private data is the exact
      leak this design prevents); the second feeds a **skip** path and the third an **enrichment**
      path, so retiring either changes behaviour for no privacy gain. Each is kept for a recorded
      reason; the plan section carries the full argument.
- [x] Reconciler: every `company_key` resolves, no two keys share an alias. **The check is NOT
      made to no-op by its `CHECK_ROOTS` entry** — that map gates nothing at runtime, and because
      pre-commit runs `--require-roots` whenever `private/` is mounted, declaring a private root
      without an exemption would have made the overlay's shape a gate on public commits. The
      no-op is a hand-written guard, and `check_required_roots()` skips private roots.
- [ ] ~~The email assistant emits `durable:` and `promote`~~ → **split out as 7c.** No Python
      writes `notes.md` at all today, so this is greenfield, and its first consumer *moves files* —
      which should not run on 44%-hand-judged data in the same change that creates it.
- [x] Review-ledger rows for every commit; zero company names in public files, commit messages or
      PR descriptions. A leak vector not in the plan was found and closed on the way:
      `--file-retries` writes **tracked** files whose bodies repeat a finding's subject, and this
      check's subjects are application paths and company keys.
- [x] Gate command clean — full CI-equivalent gate ALL GREEN, and the reconciler proved to no-op
      in a detached worktree with neither `private/` nor `config.yaml`.
