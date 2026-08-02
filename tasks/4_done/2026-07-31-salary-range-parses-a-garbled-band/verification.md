# Verification — 2026-07-31-salary-range-parses-a-garbled-band

Every command below was run on branch `wip/35-pipeline-parse-defects`, in the
worktree that holds this change. The "before" runs are the same tree with only
`automation/shared/job_metadata.py` reverted to its committed state (`git
checkout -- automation/shared/job_metadata.py`), so before and after differ by
this task's change and nothing else. Scratch paths redacted to `<scratch>`.

## The defect reproduces from a fixture, by TWO routes

A throwaway probe over fictional JD text (`<scratch>/probe_salary.py`),
pre-fix module:

```
A: stipend range inside the comp paragraph
  rich: {'min': None, 'max': None, 'bands': [
          {'min': 140000, 'max': 175000, 'currency': 'USD', 'period': 'year', ...},
          {'min': 240, 'max': 300, 'currency': 'USD', 'period': 'year', ...}]}
  envelope: (240, 175000)
  bare: {'min': 240, 'max': 175000, 'confidence': 'high', 'source': 'job_description'}

B: 4-digit bare low then separator      ("The annual base salary is $3240 - $175,000 per year.")
  rich: {'min': 240, 'max': 175000, 'currency': 'USD', 'period': 'year', ...}
  bare: {'min': 240, 'max': 175000, 'confidence': 'high', 'source': 'job_description'}
```

Route A is the reported shape exactly — `$240 - $175,000`, a three-digit low
against a six-digit high — reached with **both matches well-formed**. Route B is
the anchoring gap the task asked to check first: the bare 2-3 digit alternative
had no digit boundary, so the scan slid past the `3` of `$3240`.

Same probe, post-fix:

```
A: rich: {'min': 140000, 'max': 175000, 'currency': 'USD', 'period': 'year', ...}
   bare: {'min': 140000, 'max': 175000, 'confidence': 'high', 'source': 'job_description'}
B: rich: None
   bare: None

D: ordinary band     $176,000 - $230,000  -> (176000, 230000)
E: k band            $176k - $230k        -> (176000, 230000)
F: hourly band       $48 - $62 per hour   -> (48, 62, 'hour')
G: part-time monthly $3,000 - $4,000/mo   -> (3000, 4000, 'month')
```

Route A keeps the REAL band instead of dropping the whole fact; route B reports
nothing. Ordinary, `k`-suffixed, hourly and part-time monthly bands are unchanged.

## The regression tests fail against the pre-fix module

```
$ git checkout -- automation/shared/job_metadata.py     # before
$ .venv/bin/python -m unittest discover -s automation/shared/tests \
      -p 'test_job_metadata.py' -k ImplausibleSalaryBand -v
test_a_digit_fragment_of_a_longer_figure_is_not_a_salary_bound ... FAIL
test_correct_but_unusual_bands_survive ... ok
test_ordinary_annual_bands_still_parse ... ok
test_stipend_range_beside_the_salary_range_does_not_garble_the_band ... FAIL
test_stitched_envelope_orders_of_magnitude_apart_reports_nothing ... FAIL
test_the_garbled_band_never_reaches_meta_yaml ... FAIL
Ran 6 tests in 0.077s
FAILED (failures=4)
```

Representative failure text (pre-fix), the field the defect is judged on:

```
FAIL: test_the_garbled_band_never_reaches_meta_yaml
AssertionError: Tuples differ: (240, 175000) != (140000, 175000)
```

The two that pass both ways are the deliberate regression guards — they exist to
prove the guards do not eat a band that is correct but unusual, so a test that
went red there would mean the fix was too wide.

After the fix:

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests \
      -p 'test_job_metadata.py' -k ImplausibleSalaryBand -v
test_a_digit_fragment_of_a_longer_figure_is_not_a_salary_bound ... ok
test_correct_but_unusual_bands_survive ... ok
test_ordinary_annual_bands_still_parse ... ok
test_stipend_range_beside_the_salary_range_does_not_garble_the_band ... ok
test_stitched_envelope_orders_of_magnitude_apart_reports_nothing ... ok
test_the_garbled_band_never_reaches_meta_yaml ... ok
Ran 6 tests in 0.081s
OK
```

## Suites, corpus and vendoring

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests
Ran 593 tests in 17.906s
OK

$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests
Ran 477 tests in 42.678s
OK

$ .venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 77 cases

$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## Blast radius on the tracked example store

`automation/store/generate_fixture_store.py` re-runs the analyzer over the
tracked fixture postings, so its diff is a direct read of what the change does to
already-derived data:

```
$ .venv/bin/python automation/store/generate_fixture_store.py
fixture store generated at <repo>/examples/data
$ git diff -- 'examples/data/**/posting.yaml'
-    by: job_metadata.py@6787bc6b
+    by: job_metadata.py@47c11e22        (x8, across 4 postings)
```

Only the module-content provenance stamp moved. **No opinion value changed** —
no fixture posting's level, workplace, visa or salary read differently after the
fix.
