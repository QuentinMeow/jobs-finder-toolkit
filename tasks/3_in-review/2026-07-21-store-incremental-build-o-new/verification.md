# Verification — 2026-07-21-store-incremental-build-o-new

**Corrected 2026-07-31 on the stack tip `40871e6`.** As first written, every line of
the "whole store test surface" block below was false for the commit it claims to
describe (`eb9c32f`): the block was captured on the isolated `main`-based worktree the
change was authored in, and was never re-run after the branch was rebased into its stack
position. All five figures are replaced below with re-measured output, at `eb9c32f`
itself and at the tip. The synthetic 15,000-entity benchmarks are labelled as
authoring-branch measurements and were **not** reproduced — see § Provenance.

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
Ran 34 tests in 63.9s            # at eb9c32f, re-measured 2026-07-31

OK
```

Both figures below hold at `eb9c32f` and were re-measured there; at the stack tip
`40871e6` the same two runs give **42** and **21**, the later commits in this stack
having added five more fold tests:

```
$ python -m unittest discover … -p 'test_build_postings.py'                 # at 40871e6
Ran 42 tests in 35.9s   OK
$ python -m unittest discover … -p 'test_build_postings.py' -k IncrementalFoldTests
Ran 21 tests in 27.9s   OK
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

**This block was entirely wrong as first published.** Every figure in it was `main`'s,
not this branch's. Re-measured 2026-07-31 in a config-less clone pinned to this change's
own commit `eb9c32f`, and again on the stack tip `40871e6`:

| command | originally claimed | actual at `eb9c32f` | at tip `40871e6` |
|---|---|---|---|
| `discover -s skills/job-search/scripts/tests` | 356 | **406** | 473 |
| `discover automation/shared/tests` | 455 | **489** | 559 |
| `discover automation/publish/tests` | 157 | **188** | 188 |
| `discover automation/gardener/tests` | 98 | **165** | 165 |
| `reconcile.py --check` | 8 checks | **9 checks** | 9 checks |

The reconciler line is the categorical one: `public-registry-blacklist`, the ninth
check, was added by `8a1321a` — which sits **below** `eb9c32f` in the stack. A tree
without that check is a different base commit, not an early snapshot.

Re-run at the tip, verbatim:

```
$ python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
Ran 473 tests in 54.903s      OK

$ python -m unittest discover automation/shared/tests
Ran 559 tests in 68.400s      OK

$ python -m unittest discover automation/publish/tests      # no JOBHUNT_CONFIG
Ran 188 tests in 130.898s     OK (skipped=1)

$ python -m unittest discover automation/gardener/tests
Ran 165 tests in 83.029s      OK (expected failures=1)

$ python automation/reconcile/reconcile.py --check
reconcile: OK (9 checks clean)

$ python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ python automation/store/validate_store.py examples/data --check-fixture-size
OK: store is valid.
fixture size OK: 13.5 KB / 100 KB soft threshold (default constant)
```

The vendoring and store lines were the two that were already right: identical at
`eb9c32f` and at the tip, including the 13.5 KB fixture figure.

Nothing under `automation/shared/` changed, so the vendoring check is a
confirmation rather than a re-sync (`git show eb9c32f --stat | grep automation/shared`
→ no output; re-checked 2026-07-31). The tracked example fixture was regenerated
with `automation/store/generate_fixture_store.py` because the builder's content
stamp (`provenance.built_by`) changed; that regeneration also corrected drift
already present on `main` (the fixture still carried `normalizer_version: 1`
against the current `NORMALIZER_VERSION = 2`, and a stale `job_metadata.py`
stamp).

**Fixture drift, re-checked at the tip.** Later commits in this stack (`c4628b0`,
`#154`, `#156`, `#157`) edited modules the fixture stamps and re-staled it, so for part
of this stack's life the claim above was true at `eb9c32f` and false at head. It has
since been repaired. At `40871e6`:

```
$ python automation/store/generate_fixture_store.py --root <tmpdir>
$ diff -rq examples/data/jobs/derived <tmpdir>/jobs/derived   # 0 differing
$ diff -rq examples/data/jobs/index   <tmpdir>/jobs/index     # 0 differing
```

No gate enforces this — `validate_store.py --check-fixture-size` exits 0 either way and
no test diffs the tracked fixture against fresh generator output, so the next module
edit can re-break it silently.

## Provenance of the synthetic-store measurements below

**The three sections that follow — byte-identity at 15,000 entities, the timings table,
and the phase breakdown — were measured on the authoring branch
`wip/05-store-incremental-build` at `eb9c32f`, and were NOT reproduced by the 2026-07-31
correction pass.** They need a multi-minute purpose-built store generator that is not in
the tree, so nothing in this repository re-runs them. They are recorded as what that run
printed, not as a claim about the current tree.

They are not uncorroborated. An independent verification pass rebuilt synthetic stores at
200 / 2,000 / 15,000 entities with the same three-manifest delta, using `git archive
eb9c32f^` as "before" and `git archive eb9c32f` as "after", and measured **12.4×–25.6×,
median-to-median 18.9×** at 15,000 entities against the ~17–25× this record implies — plus
an exact match on the fold-cache size (8.58 MB vs 8.6 MB), `postings.jsonl`
(6.20 MiB vs 6.2 MB), and the 45,000 derived files. That is a second source, not a re-run.

The one thing in this section that IS reproducible from the tree — the unit equivalence
test — was re-run at the tip: `Ran 1 test in 1.628s OK`.

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

`check_pr_body.py` validates the body's *shape*, not its numbers — which is exactly why
it passed over the five false figures corrected above. A follow-up is filed as
`tasks/0_backlog/2026-07-31-pr-verification-blocks-are-measured-off-the-stack/`.
