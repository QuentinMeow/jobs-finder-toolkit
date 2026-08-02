# Store: make the incremental build O(new), not O(store)

- **Priority**: P1 (next store round)
- **Area**: harness
- **Source**: stage-3 integration probe 2026-07-21; filed by the implementing session
- **Claimed-by**: agent session 2026-07-31 (branch `wip/05-store-incremental-build`)

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
docs/designs/raw-data-layer/02-job-postings-pipeline.md, alternatives table) is
O(new-manifests) work per run.

## Definition of done

- [x] Incremental builds fold ONLY pending manifests into persisted prior state
      (derived entities update in place for touched keys; untouched entities are
      not re-reduced, not re-written, not re-serialized).
- [x] The incremental==rebuild byte-identical equivalence test STILL passes —
      equivalence is the non-negotiable contract; the optimization must not
      introduce order dependence (the ledger-ordered fold semantics stay).
- [x] Index update strategy documented (in-place row patch vs partitioned files
      vs accept full index rewrite while derived goes O(new) — measured choice).
- [x] Post-fetch build time on a 15k-entity store drops from minutes to seconds;
      number recorded in the PR.
- [x] The pre-sanctioned SQLite-cache escape hatch (design 01, alternatives) is
      explicitly evaluated and either adopted or deferred with a reason.

Design record: [docs/designs/raw-data-layer/05-incremental-build.md](../../../docs/designs/raw-data-layer/05-incremental-build.md).
Evidence: `verification.md` in this folder.
