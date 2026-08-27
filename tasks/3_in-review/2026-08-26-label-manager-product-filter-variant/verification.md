# Verification — 2026-08-26-label-manager-product-filter-variant

## Corpus and focused regression tests

```
$ ../../../.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 177 cases
exit 0

$ ../../../.venv/bin/python -m unittest skills.job-search.scripts.tests.test_filter_variants
...............
Ran 15 tests in 0.382s
OK
exit 0

$ ../../../.venv/bin/python -m unittest skills.job-search.scripts.tests.test_location_title
........................................
Ran 40 tests in 0.005s
OK
exit 0
```

## Impact-selected repository gates

```
$ ../../../.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
impact from 'origin/main' (merge-base a7924731c09c): focused; lanes: policy, job-search
coverage: 12 of 37 gates in the table executed (0 skipped, 25 not selected)
ALL GREEN (12 of 37 gates ran)
exit 0
```

## Independent-review wording correction

The post-review edit only qualifies the recorded boundary: the fixture-profile title assessor
returns `no_match`, while a configured full-pipeline word filter may separately rescue that row to
review. No corpus or runtime code changed. The same checks were rerun after the correction:

```
$ ../../../.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 177 cases
exit 0

$ ../../../.venv/bin/python -m unittest skills.job-search.scripts.tests.test_filter_variants
Ran 15 tests in 0.390s
OK
exit 0

$ ../../../.venv/bin/python -m unittest skills.job-search.scripts.tests.test_location_title
Ran 40 tests in 0.005s
OK
exit 0

$ ../../../.venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (10 checks clean)
exit 0

$ ../../../.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
impact from 'origin/main' (merge-base a7924731c09c): focused; lanes: policy, job-search
coverage: 12 of 37 gates in the table executed (0 skipped, 25 not selected)
ALL GREEN (12 of 37 gates ran)
exit 0
```
