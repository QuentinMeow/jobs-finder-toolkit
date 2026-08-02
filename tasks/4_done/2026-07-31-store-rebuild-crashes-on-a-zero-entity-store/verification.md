# Verification — 2026-07-31-store-rebuild-crashes-on-a-zero-entity-store

All commands run on branch `wip/33-store-p0-data-loss`, against throwaway temp
stores with `JOBHUNT_CONFIG` pinned to a scratch config.

## The crash, reproduced against the pre-fix builder

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -t skills/job-search/scripts/tests -k EmptyStoreRebuildTests

ERROR: test_rebuild_when_every_captured_row_is_suppressed
  File "skills/job-search/scripts/build_postings.py", line 1839, in build_rebuild
    _swap_dir(layout.derived, derived_new)
  File "skills/job-search/scripts/build_postings.py", line 1917, in _swap_dir
    new.rename(current)             # window closes (back-to-back)
FileNotFoundError: [Errno 2] No such file or directory:
  '.../jobs/derived.building' -> '.../jobs/derived'

ERROR: test_rebuild_of_an_empty_store_exits_cleanly          (same traceback)
ERROR: test_rebuild_of_an_index_only_checkout_keeps_the_floor (same traceback)
```

The third shape is the one that matters most and was not in the original report: a
checkout holding **only the committed index** — no raw, no derived — materializes
zero entities, so `--rebuild` cannot run at all on precisely the machine the durable
index floor exists to serve.

## Post-fix

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -t skills/job-search/scripts/tests -k EmptyStoreRebuildTests -v

test_rebuild_of_an_empty_store_exits_cleanly ... ok
test_rebuild_of_an_index_only_checkout_keeps_the_floor ... ok
test_rebuild_when_every_captured_row_is_suppressed ... ok

Ran 3 tests in 1.4s
OK
```

The scratch differential harness confirms the same on a store with real history:

```
$ .venv/bin/python equiv_check.py       # step 6: raw + derived deleted entirely
build_postings: mode=rebuild, entities=0, suppressed=0, events=0, carried_from_index=6
index-only checkout, --rebuild: ['ashby-ay-1', 'gh-111', 'gh-222', 'gh-333', 'gh-444', 'gh-900']

RESULT: ALL CHECKS PASS
```

Pre-fix, that same step raised `FileNotFoundError` out of `_swap_dir`.

## Definition of done

- [x] `--rebuild` on a store with zero materialized entities exits 0 with a sane
      summary (`mode=rebuild, entities=0, ...`), never a traceback.
- [x] `derived/` is not left renamed to `derived.old`: the test asserts, for both
      `derived` and `index`, that the zone is a live directory and that neither
      `.old` nor `.building` remains.
- [x] A test covers both filed shapes (no manifests at all; manifests whose every row
      is suppressed) plus the index-only checkout found while fixing it.
- [x] The job-search suite passes (482 tests, OK — see the P0's `verification.md` for
      the full-suite output, which covers both tasks in one run).

## Scope note

The filed task called this P2 and "just a crash". The rename ordering makes it a
data-availability bug: the first rename has already moved the live `derived/` to
`derived.old` when the second raises. That is why it shipped with the P0 rather than
waiting — the two are the same invariant (a build path must not leave data
unreachable), and the index-only-checkout shape is where they meet.
