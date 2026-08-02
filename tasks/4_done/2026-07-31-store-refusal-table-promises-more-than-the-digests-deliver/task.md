# The fast path's refusal table promises more than its digests deliver

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: adversarial review of the O(new) incremental store build, 2026-07-31 —
  findings 4 and 5 of that report; both are doc-vs-code gaps rather than live corruptions,
  so they were filed rather than folded into the three-defect fix
- **Claimed-by**: Claude, 2026-08-02, branch `fix/22-build-postings-correctness` (done)

## Goal

Close the gap between what `docs/designs/raw-data-layer/05-incremental-build.md` promises
the fast path detects and what `_fast_plan` actually checks — by tightening the checks, by
narrowing the sentences, or both, deliberately rather than by accident.

## Context

Three specific gaps, each verified against the shipped code:

**1. A manifest replaced in place is not detected.** The refusal table says *"The set of
manifests in `raw/` changed other than by the pending ones → a manifest was removed, or the
raw zone was not synced."* `_store_state` digests only **fetch ids**
(`digest_strings(ids)`), so a manifest rewritten with the same `fetch_id` and a different
`payload.blob` or `fetched_at` passes every check:

```
BREAK  a folded manifest REPLACED in place (same fetch_id, new blob) | fold=pending-only | no refusal
```

`max_manifest` is computed and stored but never compared in `compare_header` — it is used
only as the ordering cap. Raw is contractually append-only and immutable, so this is
out-of-contract mutation rather than a live bug, but the doc's claim is stronger than the
code's guarantee. Cheapest tightening: digest `(fetch_id, blob_sha, fetched_at)` triples
instead of bare fetch ids. Note that changing the digest invalidates every existing cache
once — one full fold, which is the designed mechanism, but say so in the change.

**2. `_derived_keys()` uses `posting.yaml` as the sole proxy for "this entity's derived is
intact"**, while `_resume_fold` also reads `events.jsonl` and `jd.md`. Deleting
`events.jsonl` under a surviving `posting.yaml` silently truncates that entity's event
history with no refusal. Cheap hardening: require `events.jsonl` alongside `posting.yaml`.

**3. The index floor is not covered by the design's honesty sentence at all.** The doc says
*"The one thing the cache cannot detect is content drift in an untouched entity — a
hand-edited `posting.yaml`, or bit-rot."* But `_patch_index_zone` reads
`index/postings.jsonl` as authoritative for every untouched row, so a row deleted from the
committed index stays lost across every subsequent fast build:

```
BREAK  index rows deleted under an otherwise-valid store | index keys now ['gh-111','gh-333'] | no refusal
```

That is the zone the design describes as committed, durable history. Cheap hardening: check
the persisted index row count against the cache entry count before trusting the patch path.

## Definition of done

- [ ] Each of the three gaps is either closed in code or narrowed in the design doc, with
      the reason stated
- [ ] Any tightened digest is called out as a one-time full fold for existing stores
- [ ] A test per gap that is closed
- [ ] `.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests` passes
