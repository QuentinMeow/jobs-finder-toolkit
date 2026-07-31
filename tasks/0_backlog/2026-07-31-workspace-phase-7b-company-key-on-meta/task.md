# Workspace phase 7b — put `company_key` on the application meta.yaml files

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace phase 7](../../4_done/2026-07-28-workspace-phase-7-company-key/task.md) · [execution plan](../../../docs/designs/workspace-restructure/execution-plan.md)
- **Claimed-by**:

## Goal

Add one `company_key:` line to each application `meta.yaml`, pointing at the index phase 7 built,
so the reconciler check has something to verify and `companies/<key>/` becomes reachable from an
application.

## Context

Phase 7 landed the index (223 keys) and the public contract: the schema accepts the field, the
loader resolves it, and the reconciler check verifies every key that is present. **No `meta.yaml`
carries the field yet**, which is why the check currently passes vacuously.

### Blocking precondition

**The owner's seven judgement calls must be answered first.** They are filed in the overlay at
`message-queue/needs-human/decisions/company-key-index-seven-calls.md`, each with the evidence and
a default, and every default is already applied to the committed index. This was split out of
phase 7 deliberately: settling the keys before 243 files point at them is far cheaper than
re-pointing 243 files afterwards. Check the decision file before starting; if it is still
unanswered, the defaults stand and you may proceed — but say so in the PR.

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

## Definition of done

- [ ] Every application `meta.yaml` carries a `company_key` that resolves in the index
- [ ] The per-file round-trip assertion ran on every write, with zero reverts (or the reverts named)
- [ ] `reconcile.py --check --require-roots` clean with the overlay mounted
- [ ] `status.py --company-keys --strict` reports full coverage and exits 0
- [ ] The skip-set-identity test still passes — adding the field changed no skip decision
- [ ] No file was reflowed: the diff is one added line per file
