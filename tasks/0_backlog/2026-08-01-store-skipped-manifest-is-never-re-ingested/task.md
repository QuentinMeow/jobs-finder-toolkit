# A manifest a build could not use is still marked processed, so only `--rebuild` recovers it

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: adversarial audit #4 finding 1, while fixing the `BlobCorrupt` crash
  in `build_postings._collect`; the skip now degrades and is counted, but the
  re-ingest half was left
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

After the condition that made a manifest unusable goes away — the blob finishes
syncing, a parser learns the source's new envelope — the store picks that manifest
back up on an ordinary incremental build, without the owner having to know to run
`--rebuild`.

## Context

`build_incremental` records every pending manifest in the ledger (`_record_pending`)
BEFORE the fold runs, because `_reduce` needs each fetch's materialization sequence
number and that number is assigned at record time. So a manifest whose blob turns
out to be corrupt, or whose payload the parser reads as zero rows, is marked
processed anyway. Two consequences:

- the corrupt blob is still `present` by name, so `_store_state`'s `absent_digest`
  does not move when the bytes are later repaired — nothing invalidates the fold
  cache, and the fast path never revisits the manifest;
- `--rebuild` re-reads every manifest regardless of the ledger, so the recovery
  path exists; it is just undiscoverable. The stderr line
  `_report_collect_notes` now prints says so explicitly, which is the stopgap.

Options considered and rejected for the fix that shipped: pre-checking each pending
blob before `_record_pending` doubles the decompression of exactly the new work the
O(new) fast path exists to keep cheap; un-recording a ledger line is not possible
(append-only). A workable shape is a small `state/` set of "read but unusable"
fetch ids that `_fast_plan` folds into its refusal digests, so the run after the
repair falls back to a full fold once and then continues.

Related but distinct: `2026-07-31-store-has-no-explicit-repair-path` covers
repairing the blob itself; this covers re-ingesting the manifest afterwards.

## Definition of done

- [ ] A store whose corrupt blob is replaced with correct bytes materializes the
      posting on the next ordinary `build_postings.py` run, with no `--rebuild`
- [ ] The same holds for a manifest that produced no rows under an old parser and
      does produce rows under a new one
- [ ] The O(new) fast path still costs one decompression per pending blob
      (benchmark before/after, as in the PR that filed this)
- [ ] Tests cover both re-ingest paths and the byte-equality of the run that
      re-ingests against a `--rebuild` of the same input
