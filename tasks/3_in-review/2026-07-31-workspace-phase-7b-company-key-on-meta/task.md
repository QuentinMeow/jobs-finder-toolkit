# Workspace phase 7b — put `company_key` on the application meta.yaml files

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace phase 7](../../4_done/2026-07-28-workspace-phase-7-company-key/task.md) · [execution plan](../../../docs/designs/workspace-restructure/execution-plan.md)
- **Claimed-by**: agent (workspace phase 7b), 2026-07-30

## Goal

Add one `company_key:` line to each application `meta.yaml`, pointing at the index phase 7 built,
so the reconciler check has something to verify and `companies/<key>/` becomes reachable from an
application.

## Context

Phase 7 landed the index (222 keys) and the public contract: the schema accepts the field, the
loader resolves it, and the reconciler check verifies every key that is present. **No `meta.yaml`
carries the field yet**, which is why the check currently passes vacuously.

> **Correction, 2026-07-31 — the paragraph above is no longer true, and the sentence in bold is
> now the inverse of reality.** The work shipped in the overlay on 2026-07-30. **All 243
> application `meta.yaml` files carry a resolving `company_key`**, and the reconciler check is no
> longer vacuous — it verifies 243 keys. Re-measured before this line was written:
> `status.py --company-keys --strict` reports 243 keyed / 0 unkeyed / 0 unresolved and exits 0.
> The original text is left standing rather than rewritten, because a task file is a dated record
> of what was believed when it was filed; `verification.md` beside this file carries the numbers.

### Precondition — MET as of 2026-07-30

The owner's seven judgement calls are **answered**, so this task is unblocked. Six took the
recorded default; one was overruled, and it changed the key set — a regional joint venture that
had been given its own key with a `parent` edge is now the *same company* as its brand, so that
key is gone and the entity's name is an alias. 223 keys → 222. The ruling and its reasoning are in
the overlay's decision log; the general rule it sets is that a separate legal entity is not
automatically a separate key.

**Consequence you must not skip: regenerate the mapping, do not reuse it.** The
`meta_updates.tsv` produced alongside the original proposal still points one application at the
retired key. Re-derive `company_key` for every folder from the index as committed, and diff the
result against the stale file — that diff should contain exactly the rows the ruling moved, and
anything else in it is a bug in your regeneration.

> **Correction, 2026-07-31 — this instruction was unfollowable as written.** `meta_updates.tsv`
> exists in **neither repository**, in the working tree or in any commit of either history
> (`git log --all --name-only | grep -c meta_updates.tsv` -> 0 in both). It was scratch that never
> left one session's machine. The property it was meant to establish is instead established
> directly and is recorded in `verification.md`: all 243 keys resolve against the committed
> 222-key index, which a mapping still pointing at the retired key could not do.

### What makes this more than a loop

1. **The private repo has no review gate.** The ledger is public, so nothing catches a bad write
   on this side. The safety net is per-file and must not be skipped: after each write, re-parse and
   assert `yaml.safe_load(new) == yaml.safe_load(old) | {"company_key": k}`. Any file failing that
   is reverted and reported, never written. This matters because `handoff._posting_keys` parses
   every live `meta.yaml` and reads `company` plus `jobs[].url`/`jobs[].role` from it — a new
   sibling scalar is inert *provided the file still parses*, which is exactly what the assertion
   proves.
2. **Insert, do not re-serialise.** These files are hand-edited and hand-read. A
   `yaml.safe_load` → `safe_dump` round trip would reflow all 243 of them, destroying comments,
   quoting and key order and burying the one real change in noise. Insert the line after the
   top-level `company:` line, the way `metadata_editor.py` splices bytes.
3. **The mapping already exists** — `meta_updates.tsv`, one row per folder, generated with the
   index. Regenerate it rather than trusting a stale copy, and diff the two.

### Guardrails

- The key is **additive only**. It must not enter any skip, dedup, filter or coverage comparison —
  the invariant phase 7 enforces at source level. Adding the field to every application must change
  no skip set; there is a test that asserts exactly that.
- `handoff.py` builds a new folder's `meta.yaml` from a scaffold dict, so a NEW application will
  not get the field unless that dict lists it. Decide whether that belongs here or in its own task,
  and note that handoff runs against a possibly-absent overlay so it cannot depend on the index.

  **Decided (2026-07-30):** the scaffold change is **not** in 7b. `handoff.py` is public code that
  runs against a possibly-absent overlay, so it cannot resolve a key at scaffold time; a new
  application stays unkeyed until one is assigned, and `status.py --company-keys` is the surface
  that shows it. Filed as its own public task,
  [`2026-07-31-handoff-scaffold-omits-company-key`](../../0_backlog/2026-07-31-handoff-scaffold-omits-company-key/task.md).

## Definition of done

Evidence for every box is in [`verification.md`](verification.md) beside this file — commands
re-run on 2026-07-31 by the agent that ticked them, not copied from the implementing session.

- [x] Every application `meta.yaml` carries a `company_key` that resolves in the index —
      243 of 243, 0 unresolved
- [x] The per-file round-trip assertion ran on every write, with zero reverts (or the reverts
      named) — **ticked on outcome evidence, with the limitation recorded**: the run left no
      artifact, so what is provable now is that every file still parses (`--check-metadata`
      243/243 valid) and that the diff is +1/−0 on all 243 files
- [x] `reconcile.py --check --require-roots` clean with the overlay mounted — `OK (9 checks clean)`
- [x] `status.py --company-keys --strict` reports full coverage and exits 0
- [x] The skip-set-identity test still passes — adding the field changed no skip decision;
      re-measured on the real tree too (367 urls / 369 pairs, identical both ways)
- [x] No file was reflowed: the diff is one added line per file — all 243 files are exactly +1/−0
