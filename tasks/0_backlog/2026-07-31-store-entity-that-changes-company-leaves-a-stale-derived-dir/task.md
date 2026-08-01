# An entity that changes company leaves a stale derived directory behind

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: adversarial review of the O(new) incremental store build, 2026-07-31 —
  **pre-existing** (confirmed present with the fast path disabled, so it belongs to the
  incremental path in general, not to that change); out of scope for that fix
- **Claimed-by**:

## Goal

An incremental build must not leave a derived entity directory at a partition the entity
no longer belongs to, so the incremental store stops holding a duplicate posting a
`--rebuild` does not have.

## Context

`derived/postings/<company>/<key>/` is partitioned by company. For an ATS board fetch the
company comes from the capture context and is stable, but an **aggregator scrape row
carries no context company slug**, so the partition is derived from the row's own
`companyName` — which the aggregator can and does change between sweeps ("UsCo" →
"UsCo Inc"). The entity key is unchanged (it is URL-derived), so it is the same entity at
a new partition.

`_write_entity` only ever writes. Nothing removes the directory at the old partition, so
the incremental store ends up with the same key materialized twice:

```
derived tree: ['usco/url-5319222995d8/posting.yaml',
               'usco-inc/url-5319222995d8/posting.yaml']

diff vs --rebuild: DIVERGENCE
  --- derived/postings/usco/url-5319222995d8/posting.yaml   incremental: <present>  rebuild: <absent>
  --- derived/postings/usco/url-5319222995d8/jd.md           incremental: <present>  rebuild: <absent>
  --- derived/postings/usco/url-5319222995d8/events.jsonl    incremental: <present>  rebuild: <absent>
```

Reproduced with the fold cache deleted (forcing the pre-optimization whole-raw-zone fold)
as well, which is what pins it as pre-existing rather than a fast-path defect.

Consequences beyond the byte diff: the stale copy is an orphan `posting.yaml`, so
`_derived_keys()` and `_carry_forward` both see it; a query walking derived can return the
old company; and the stale entity's `last_seen` freezes at the moment it moved, which reads
as a stale posting rather than a non-existent one.

Watch out for the interaction with the fold cache: the cache holds one partition per key
(`entry["p"]`), and `_derived_keys()` compares only key SETS, so a duplicated key does not
by itself refuse the fast path.

## Definition of done

- [ ] An entity whose partition moves leaves exactly one derived directory, at the new
      partition
- [ ] The removal is safe under the "agents never delete owner data" rule — it removes a
      *derived* (regenerable) directory only, never raw, annotations, or state
- [ ] A test captures the same aggregator row twice under two `companyName` values and
      asserts the incremental result is byte-identical to `--rebuild`
- [ ] `.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests` passes
