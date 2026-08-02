# Worklog — 2026-07-31-store-refusal-table-promises-more-than-the-digests-deliver

## 2026-08-02 — session 1 (Claude, branch `fix/22-build-postings-correctness`)

- All three gaps CLOSED IN CODE rather than narrowed in the doc. The task offered either; the
  code side won each time because each gap is a store the incremental build accepts and a
  `--rebuild` contradicts, and the design's own framing is that a refusal "can only make a build
  slow, never wrong" — so tightening is always the cheap direction.
  1. `_store_state` digests `(fetch_id, payload blob)` pairs, not bare fetch ids.
  2. `_derived_keys` requires `events.jsonl` alongside `posting.yaml`.
  3. `_fast_plan` refuses when the persisted index is a proper subset of the cache entries.
- `_carry_forward` deliberately keeps `posting.yaml` as ITS predicate. The two functions answer
  different questions: `_derived_keys` asks "is this entity's derived intact enough to resume
  its fold from?" (and `_resume_fold` reads the events), while `_carry_forward` asks "is there
  an entity here to keep?", where a missing event list is not a reason to drop a posting. The
  `_derived_keys` docstring now says so, because it used to claim they shared a predicate.
- Cache-version bump, as the task required be called out: `CACHE_SCHEMA` 1 -> 2, because
  `manifest_digest` now MEANS something different and a cache computed under the old rule cannot
  be compared against the new one. Every existing store takes exactly one full fold on its next
  build. In practice this is invisible: `_module_fingerprint` already includes a content hash of
  `build_postings.py` itself, so any edit to the builder forces that same one-time fold anyway.
- The design doc's three rows are reworded to the checks that now exist, and its honesty
  paragraph is extended with the index floor — content drift inside a surviving row is still
  only repaired by `--rebuild`, but a row that DISAPPEARS is not, because a rebuild cannot
  restore what it has nothing to rebuild from.
- `examples/data/**` carries four one-line `built_by` stamp changes, regenerated with
  `automation/store/generate_fixture_store.py`. That stamp is a content hash of
  `build_postings.py`, so ANY edit to the builder drifts the tracked fixture and
  `automation/shared/tests` fails until it is regenerated — worth knowing before the next
  builder change. The regen is folded into this commit, so the two earlier commits on this
  branch are intermediate states whose fixture stamp lags by one hop; the branch tip is green.
- Shipped as commit `54a5c69` with three regressions.
