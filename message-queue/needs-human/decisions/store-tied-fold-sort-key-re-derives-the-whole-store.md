# Should breaking the fold's tied sort key re-derive the whole store once?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [tied-sort-key task](../../../tasks/0_backlog/2026-07-31-store-spot-equivalence-fails-on-a-tied-sort-key/task.md)
- **Blocking**: nothing. The store builds and serves normally today; only
  `--rebuild` refuses, and only on a store that actually contains a tie.
- **Default path**: leave the tie unfixed. The task stays in `tasks/0_backlog/`
  and no agent changes the canonical fold order without an answer here.

## Background

The builder folds each entity's observations in the canonical order
`(fetched_at, fetch_id, native_id)`. Two rows **in the same manifest** with no
`native_id` that hash to the same weak content key tie on all three fields, so the
reduce genuinely is order-dependent for that entity. `_spot_equivalence` — the
rebuild's determinism check, which re-reduces a sample forwards and reversed and
demands byte-identical output — correctly notices and refuses:

```
incremental: rc=0  mode=incremental, fold=full, entities=1, changed=1
rebuild    : rc=2  build_postings: VERIFY FAILED — non-deterministic reduce
                   (order-dependent) for ck-e6748d201da5
```

The realistic shape is one aggregator sweep that lists the same role twice with a
slightly different description and no stable id. The result is that a store builds
and serves happily on every routine run and then refuses the **verifying** path —
which is also the repair path for content drift. The owner hits it at the worst
possible moment.

Why this is your call rather than an obvious fix: the natural repair is to extend the
sort key with a stable per-row discriminator. That changes the canonical fold order,
which moves the builder's module fingerprint, which **re-derives every entity in the
store once** — the designed mechanism for exactly this, and the same cost a
classifier fix already pays. On the measured 15,000-entity store a full fold is
150–219 s. It is a one-time cost, it is safe, and it is visible, but it is a real
cost incurred on a store you own, so a session should not simply spend it.

## Options

### Option A — break the tie deterministically (extend the sort key)

Add a stable per-row discriminator (the row's index within its manifest, or a hash of
the row's own bytes) as a final sort component, so the fold has a total order and both
paths agree. `_spot_equivalence` then passes honestly rather than by being told to
look away.

- Pro: the smallest change that makes the invariant true instead of merely unchecked.
  Incremental and `--rebuild` agree; the refusal disappears because the cause does.
- Con: the fingerprint moves, so **the whole store is re-derived once** on the next
  build — one full fold (150–219 s at 15,000 entities), and every `posting.yaml`'s
  `built_by` stamp changes in that build's diff.

### Option B — refuse on both paths

Run the same order-independence check on the incremental path, so the store never
accepts what a rebuild will reject.

- Pro: consistent; no re-derivation; the problem surfaces at capture time rather than
  at repair time.
- Con: converts a live no-op into a hard failure. A store that already contains a tie
  stops building at all until the offending manifest is dealt with — a worse day than
  the one this is meant to prevent, and there is no repair tool for it.

### Option C — suppress the duplicate row at collect time

Treat two indistinguishable rows in one manifest as one observation.

- Pro: no fingerprint change, no re-derivation, no new failure mode.
- Con: it silently discards a real captured row. The two rows differ in JD body, so
  "indistinguishable" is only true of the sort key, not of the data — this throws away
  information the raw zone deliberately kept, which is the one thing the store's
  raw-is-truth contract exists to prevent.

## Recommendation

**Option A**, accepting the one-time full re-derive. It is the only option that makes
the fold's order-independence actually true rather than unchecked or worked around;
the cost is a single slow build, which is the failure mode this design already accepts
everywhere else (every refusal in the fast-path admission table costs exactly that);
and Option C's cost — dropping a captured row — is the kind of silent data loss this
whole review round has been about. Option B is the one to avoid: it trades a rare
refusal on the repair path for a guaranteed hard stop on the routine path.

If you want it, the right time is a session where a full fold is going to happen
anyway (any classifier or parser change already forces one), so the re-derive rides
along for free.

**Your answer:** ______
