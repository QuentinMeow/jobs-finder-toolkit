# Store: make the incremental build O(new), not O(store)

- **Priority**: P1 (next store round)
- **Area**: harness
- **Source**: stage-3 integration probe 2026-07-21; filed by the implementing session

## Goal

Make routine incremental builds scale with newly captured manifests rather
than the total historical store, while preserving byte-identical rebuild
equivalence.

## Context

`build_postings.py` incremental mode uses the ledger set-difference to *account*
for new manifests, but the reduce pass still folds the **entire raw zone** every
run (all observations, all entities), and the index zone is rewritten wholesale.
At 15.2k entities that is ~3-4 minutes appended to every search run (the stage-3
post-fetch build), and it grows linearly with the store. The design intent
("an incremental build amortizes parsing once per fetch",
docs/design/raw-data-layer/02-job-postings-pipeline.md, alternatives table) is
O(new-manifests) work per run.

## Definition of done

- [ ] Incremental builds fold ONLY pending manifests into persisted prior state
      (derived entities update in place for touched keys; untouched entities are
      not re-reduced, not re-written, not re-serialized).
- [ ] The incremental==rebuild byte-identical equivalence test STILL passes —
      equivalence is the non-negotiable contract; the optimization must not
      introduce order dependence (the ledger-ordered fold semantics stay).
- [ ] Index update strategy documented (in-place row patch vs partitioned files
      vs accept full index rewrite while derived goes O(new) — measured choice).
- [ ] Post-fetch build time on a 15k-entity store drops from minutes to seconds;
      number recorded in the PR.
- [ ] The pre-sanctioned SQLite-cache escape hatch (design 01, alternatives) is
      explicitly evaluated and either adopted or deferred with a reason.
