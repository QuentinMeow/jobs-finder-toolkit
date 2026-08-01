# A frozen snapshot cannot prove the last observation's `url`, so one boundary diff is approximate

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: adversarial audit #4 finding 5; found while seeding the fold from a
  frozen snapshot so the freeze boundary emits its `changed` event
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

The `changed` event at a freeze boundary is exact for all eight `_TRACKED` fields,
including `url`.

## Context

`build_postings._resume_from_frozen` seeds the fold with the snapshot's state so
the first observation after a prune diffs against the pre-prune state instead of
against nothing. `_frozen_prior` reconstructs that state as the inverse of
`_finish`: `title`/`location` are last-observation-wins and the `facts` block is
the last row's tracked payload, so seven of the eight fields come back exactly.

`url` does not. The derived entity keeps `source_ids` — a first-appearance dedup of
every `(source, native_id, url)` ever seen — not the last observation's url, so
`_frozen_prior` takes the most recently ADDED source id. That is the true last url
except for an entity whose observations alternate between two urls across the
boundary (a cross-posted content-keyed `ck-` entity is the plausible shape), where
the boundary diff would report a `url` change that did not happen, or miss one that
did. It is deterministic either way, so incremental and `--rebuild` agree; the
event is just wrong about that one field.

Fixing it means the derived entity, or the snapshot, carrying the last
observation's url. `state/postings-fold-cache.jsonl` already holds exactly this
(entry `f.s.url` is the fold's `prior`), but `retention.snapshot_entity` reads only
`derived/`, and the cache may legitimately be absent. Adding the field to the
posting schema is the other option and is a schema version bump.

## Definition of done

- [ ] A frozen entity whose url alternated across the boundary produces the same
      `changed` events as a build that never pruned the blob
- [ ] Whatever carries the fact is deterministic and survives a `--rebuild`
- [ ] `automation/vendoring/sync_vendored.py --check` clean if
      `automation/shared/store/retention.py` changed
