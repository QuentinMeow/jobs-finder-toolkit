# Worklog — 2026-07-21-store-incremental-build-o-new

## 2026-07-31 — session 1 (agent, branch `wip/05-store-incremental-build`)

- Profiled the existing incremental build on a synthetic 15,000-entity store:
  the cost is ~65% YAML serialization and ~24% opinion classifiers, both
  strictly per-entity, so both vanish for an entity no fetch touched. Parsing
  the raw zone was only ~7%.
- Analysed the fold for order dependence before writing code. Only two
  accumulated quantities are genuinely order-sensitive (the `changed` event
  stream and the prior-JD snapshot), and both resume from one carried
  observation snapshot. Recorded the full per-quantity table in the design doc.
- Found the one reduction that is NOT a per-key partition: `_post_pass`, the
  duplicate/ATS-migration hint pass, which groups entities across keys. Handled
  explicitly by persisting each entity's bucket triple and pulling whole
  affected buckets into the working set; two tests pin it (a hint that must be
  added to an unobserved entity, and one that must be removed from one).
- Implemented the fold state in `skills/job-search/scripts/postings_fold_state.py`
  plus a fast path in `build_postings.py`, with a conservative admission test:
  nine refusal signals, each falling back to the unchanged whole-raw-zone fold.
- Measured before/after and the index-zone share; chose "full index rewrite fed
  by persisted rows" because every index file's header carries `built_at`, so
  any ingesting run rewrites every file regardless of strategy.
- Evaluated the pre-sanctioned SQLite cache and deferred it: neither trigger has
  fired (index is 6.2 MB against a ~10 MB threshold, single writer) and it would
  not have touched the measured bottleneck.
- Verified byte-identity twice: the unit equivalence test, and a 15,000-entity
  store cloned, built incrementally on one copy and rebuilt on the other —
  45,000 derived files and 4 index files, zero differences.
- Next: nothing outstanding for this task. The follow-up worth watching is the
  index size crossing ~10 MB (roughly 25,000 entities), which is when the SQLite
  escape hatch becomes worth re-evaluating.
