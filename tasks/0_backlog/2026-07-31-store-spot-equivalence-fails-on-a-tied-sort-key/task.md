# `--rebuild` refuses a store where two rows in one manifest tie on the whole sort key

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: adversarial review of the O(new) incremental store build, 2026-07-31 —
  **pre-existing** (`_spot_equivalence` predates that change); out of scope for that fix
- **Claimed-by**:

## Goal

Decide and implement what the builder should do when two observations of one entity are
genuinely indistinguishable under the canonical fold order, instead of leaving the store in
a state where the incremental path accepts it and `--rebuild` refuses it.

## Context

The fold sorts observations by `(fetched_at, fetch_id, native_id)`. Two rows in the *same*
manifest with no `native_id` that hash to the same weak content key tie on all three, so the
reduce genuinely is order-dependent for that entity — and `_spot_equivalence` (which
re-reduces a sample forwards and reversed and demands byte-identical output) correctly
notices.

The result is an asymmetry, reproduced with two aggregator rows differing only in JD body:

```
incremental: rc=0  mode=incremental, fold=full, entities=1, changed=1
rebuild    : rc=2  build_postings: VERIFY FAILED — non-deterministic reduce
                   (order-dependent) for ck-e6748d201da5
```

So a store can be built and served happily by every routine run, and then refuse the
verifying path — which is also the repair path for content drift. The user hits it at the
worst moment.

Realistic shape: an aggregator sweep that lists the same role twice with a slightly
different description and no stable id.

The decision to make is which of these is right, and it is a design call rather than an
obvious bug fix:

1. **Break the tie deterministically** — extend the sort key with a stable per-row
   discriminator (the row's position within the manifest, or a content hash) so the fold has
   a total order and both paths agree. Cheapest, and it makes `_spot_equivalence` pass
   honestly rather than by being told to look away.
2. **Refuse on both paths** — make the incremental path run the same check, so the store
   never accepts what a rebuild will reject. Consistent, but converts a live no-op into a
   hard failure for existing stores.
3. **Suppress the duplicate row** at collect time, treating two indistinguishable rows in
   one manifest as one observation.

Option 1 looks right, but it changes the canonical order, so it re-derives the whole store
once (the fingerprint moves) — which is the designed mechanism for exactly this and worth
saying out loud in the change.

## Definition of done

- [ ] A decision is recorded (a `memory/decisions/` ADR, or a
      `message-queue/needs-human/decisions/` item if it is the owner's call)
- [ ] Incremental and `--rebuild` agree on any store containing a tie — both accept, or both
      refuse with the same message
- [ ] A test builds the tie shape (two aggregator rows, no ids, same weak key) and asserts
      the agreement
- [ ] `.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests` passes

## Status

**2026-07-31** — the `wip/33-store-p0-data-loss` session considered this alongside the
`--opinions-only` P0 and did NOT implement it. Option 1 changes the canonical fold
order, which moves the builder fingerprint and re-derives the whole store once; that
is a real cost on the owner's store and not a session's call to make unilaterally.
The options + a recommendation are filed at
[`message-queue/needs-human/decisions/store-tied-fold-sort-key-re-derives-the-whole-store.md`](../../../message-queue/needs-human/decisions/store-tied-fold-sort-key-re-derives-the-whole-store.md),
which satisfies the first checkbox. The remaining checkboxes wait on the answer.
