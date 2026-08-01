# Verification — 2026-07-30-handoff-does-not-record-created-postings

Every command below was run from the worktree root with the repo venv. Output is real,
trimmed to the lines that carry the result.

## The gap itself: scaffold -> delete the folder -> `--sync-log` -> still skipped

`CreationTimeSkipLogTests.test_a_deleted_folder_no_longer_un_skips_its_posting` reproduces
the reported sequence end to end (handoff scaffolds against a temp tree, the folder is
removed, the tracker's `--sync-log` runs as a subprocess, then a second handoff over the
same row must report it as a duplicate).

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests -p test_handoff.py -v 2>&1 | grep CreationTime
test_a_bulk_rerun_is_stopped_by_the_row_the_first_run_wrote ... ok
test_a_clean_scaffold_does_not_print_the_un_skip_command ... ok
test_a_deleted_folder_no_longer_un_skips_its_posting ... ok
test_a_group_dropped_entirely_by_the_location_gate_records_nothing ... ok
test_a_grouped_folder_records_every_posting_not_just_the_lead ... ok
test_a_location_mismatch_folder_is_recorded_with_the_un_skip_command ... ok
test_a_row_with_no_company_records_nothing ... ok
test_a_scaffold_with_no_fresh_jd_is_recorded_with_the_un_skip_command ... ok
test_a_second_run_on_the_same_posting_adds_no_second_line ... ok
test_sync_log_finds_nothing_to_add_after_a_handoff ... ok
test_the_append_honours_applications_root ... ok
```

## Anti-drift: the other writer finds nothing to add

`test_sync_log_finds_nothing_to_add_after_a_handoff` asserts `--sync-log` prints
"No posting changes" over the untouched folder handoff just created. Any disagreement in
any of the six stored fields would make it append a second line.

## Full suites

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests
Ran 351 tests in 29.537s
OK

$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests \
      -t skills/application-tracker/scripts/tests
Ran 88 tests in 41.184s
OK

$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 469 tests in 11.725s
OK
```

Baselines before the change: job-search 340, application-tracker 88, shared 455.
All three suite figures and all three baselines re-measured 2026-07-31 at this change's
own commit `a816a53` and its parent `a003c1c` — every one holds. This block is one of
the few in the stack that was accurate as published.

New: 11 handoff tests, **14** shared tests (`PostingRowsTests`, `RecordPostingsTests`).
The "16" first written here is wrong, and the suite deltas prove it: 455 → 469 is +14,
and `git show a816a53 -- automation/shared/tests/test_skip_log.py | grep -cE '^\+ *def test'`
returns **14**. No tests were removed, so the delta and the count agree.

At the stack tip `40871e6` the same three suites give job-search **473**,
application-tracker **108**, shared **559**.

## Vendoring

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## Reconciler

This block originally read `<see the PR body — run at staging time>` — a placeholder that
records nothing, deferring to a PR body whose own gate figures were later found stale.
Run 2026-07-31, at this change's own commit and at the stack tip:

```
$ git checkout a816a53 && .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (8 checks clean)                                              exit 0

$ git checkout 40871e6 && .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (9 checks clean)                                              exit 0
```

Eight at `a816a53` is correct, not stale: `public-registry-blacklist` is added by
`8a1321a`, two commits **above** this one in the stack.

## Definition of done

- [x] The per-posting flattening lives once in `automation/shared/`
      (`skip_log.posting_row` / `posting_rows` / `record_postings`), vendored into both
      job-search and application-tracker, `sync_vendored.py --check` clean. It went into
      `skip_log.py` rather than a new module because that file already declares
      `POSTING_KEYS` — the shape the flattening produces — and is already vendored into
      exactly those two skills, so no new vendoring target was needed.
- [x] `handoff.py` appends the creation event through that shared shape, honouring
      `--applications-root` (via the existing `_applications_jsonl`;
      `test_the_append_honours_applications_root`).
- [x] The exit-3 / exit-1 recording question is filed as
      `message-queue/needs-human/decisions/handoff-records-non-clean-scaffolds.md` with
      three options and an implemented default path.
- [x] A test scaffolds via handoff against a temp tree, deletes the folder, runs
      `--sync-log`, and asserts the posting is still skipped.
