# Verification — 2026-07-21-store-incremental-build-o-new

Every command below was run on branch `wip/05-store-incremental-build` in a
config-less worktree (no `config.yaml`, no `private/` overlay — the CI shape).
Suites that read config pin `JOBHUNT_CONFIG=$PWD/config.example.yaml`, exactly as
CI does; the publish suite deliberately does not, because pinning the fictional
persona's config arms the leak guard against its own example content.
All store measurements use a synthetic store in a temp directory; nothing read
or wrote the owner's real store.

## The incremental == rebuild byte-identical equivalence test

```
$ python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests -p 'test_build_postings.py' \
      -k test_staged_incremental_equals_rebuild -v
test_staged_incremental_equals_rebuild (test_build_postings.DeterminismTests.test_staged_incremental_equals_rebuild) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.961s

OK
```

Its second build takes the new path (`fold=pending-only` in the run summary),
so the test exercises the optimization rather than bypassing it.

## The builder suite, including 16 new fold tests

```
$ python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests -p 'test_build_postings.py'
Ran 34 tests in 16.9s

OK
```

The 16 additions are `IncrementalFoldTests`. Each snapshots the incremental
result and byte-compares it against a full `--rebuild` of the same raw zone.
Three are the "would fail if the optimization skipped an entity it should have
touched" tests the task asked for:

- `test_new_manifest_stamps_duplicate_hint_on_an_untouched_entity` — a duplicate
  hint that must be added to an entity the new manifest never mentions.
- `test_departing_entity_clears_a_stale_duplicate_hint` — a hint that must be
  removed from an entity the new manifest never mentions.
- `test_reached_entity_keeps_its_continuable_fold` — an entity reached that way
  must not lose its ability to be folded incrementally afterwards.

The third earned its place: it caught a real defect during development, where an
entity reached by the duplicate pass had its cache entry rebuilt from the
disk-loaded posting and so lost its fold state. Reverting the fix and running
that test alone reproduces the failure:

```
$ # with the defect reintroduced
AssertionError: 'fold=pending-only' not found in 'build_postings: mode=incremental,
fold=full, pending=1, entities=2, changed=1, suppressed=0, carried_from_index=0'
```

## The whole store test surface

```
$ python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests
Ran 356 tests in 28.456s
OK

$ python -m unittest discover automation/shared/tests
Ran 455 tests in 8.565s
OK

$ python -m unittest discover automation/publish/tests      # no JOBHUNT_CONFIG
Ran 157 tests in 92.884s
OK (skipped=1)

$ python -m unittest discover automation/gardener/tests
Ran 98 tests in 65.552s
OK (expected failures=1)

$ python automation/reconcile/reconcile.py --check
reconcile: OK (8 checks clean)

$ python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ python automation/store/validate_store.py examples/data --check-fixture-size
OK: store is valid.
fixture size OK: 13.5 KB / 100 KB soft threshold (default constant)
```

Nothing under `automation/shared/` changed, so the vendoring check is a
confirmation rather than a re-sync. The tracked example fixture was regenerated
with `automation/store/generate_fixture_store.py` because the builder's content
stamp (`provenance.built_by`) changed; that regeneration also corrected drift
already present on `main` (the fixture still carried `normalizer_version: 1`
against the current `NORMALIZER_VERSION = 2`, and a stale `job_metadata.py`
stamp).

## Byte-identity at 15,000 entities, not just in unit tests

A synthetic store (150 companies x 100 postings x 2 capture days, ~3 KB of JD
text each) was built, three new board manifests were added, then the store was
cloned: one copy built incrementally, the other with `--rebuild`. Run twice, at
different points in the store's history.

```
$ python tree_cmp.py <incremental-copy> <rebuilt-copy>       # first check
derived: 45000 vs 45000 files; only-A=0 only-B=0 differing=0
index: 4 vs 4 files; only-A=0 only-B=0 differing=0
IDENTICAL

$ python tree_cmp.py <incremental-copy> <rebuilt-copy>       # after more history
derived: 45000 vs 45000 files; only-A=0 only-B=0 differing=0
index: 9 vs 9 files; only-A=0 only-B=0 differing=0
IDENTICAL
```

## Timings on the 15,000-entity store

Same store shape, same three-new-manifest delta, same machine. "Before" runs the
builder as it exists on `main`; "after" runs this branch.

```
== ORIGINAL builder, 3 new manifests on a 15,000-entity store ==
build_postings: mode=incremental, pending=3, entities=15000, changed=300, ...
real 143.95
real 167.37
real 192.81

== THIS BRANCH, same delta ==
build_postings: mode=incremental, fold=pending-only, pending=3, entities=15000, folded=300, changed=300, ...
real 6.43   real 6.61   real 6.63   real 7.74
real 8.49   real 8.65   real 10.05  real 10.66

== THIS BRANCH, full fold (every fallback path) ==
store: full fold this run (fold cache stale (fingerprint changed))
build_postings: mode=incremental, fold=full, pending=0, entities=15000, changed=15000, ...
real 150.16     (also measured at 177.4 and 219.1 on other runs)
```

Wall-clock on this machine varies with page-cache state, which is why several
runs of each are reported rather than one number. The fast path also creeps
slightly as the store accumulates capture days, because every
`index/by-day/<date>.jsonl` header carries a timestamp that moves on any run
that ingests a fetch, so all of them are rewritten every time.

Phase breakdown of one fast build (in-process instrumentation, 7.69 s total):

```
   1.909s   24.8%  _write_entity          (300 re-folded entities, YAML out)
   1.620s   21.1%  _resume_fold           (300 entities, YAML in)
   1.363s   17.7%  _finish                (opinions for 300 entities)
   1.284s   16.7%  _patch_index_zone      (6.2 MB postings.jsonl + 5.1 MB by-day)
   0.240s    3.1%  cache_save             (8.6 MB fold cache)
   0.210s    2.7%  cache_load
   0.184s    2.4%  _derived_keys          (15,000-entity stat walk)
   0.166s    2.2%  iter_manifests
   0.042s    0.5%  _collect               (parse the 3 pending manifests)
```

The first three scale with the delta, not the store — which is the point of the
change. The index zone, the cache, and the derived stat walk are the remaining
whole-store costs, and together they are under 2 seconds.

For reference, the profile that motivated the work: on the old path the same
build spent ~65% of its CPU in `dumps_yaml` inside `_write_entity` and ~24% in
the opinion classifiers, both strictly per-entity. Parsing the raw zone was only
about 7%.

## PR body format check

```
$ python skills/github-workflow/scripts/check_pr_body.py <pr-body>
check_pr_body.py: OK — follows the human-facing PR format
```
