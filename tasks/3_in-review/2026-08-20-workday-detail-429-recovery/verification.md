# Verification — 2026-08-20-workday-detail-429-recovery

## Focused recovery behavior

```
$ ../../../.venv/bin/python -m unittest skills/job-search/scripts/tests/test_workday_recovery.py
..........
----------------------------------------------------------------------
Ran 10 tests in 0.514s

OK
```

```
$ ../../../.venv/bin/python -m unittest skills/job-search/scripts/tests/test_sources_intake.py
............................
----------------------------------------------------------------------
Ran 28 tests in 0.066s

OK
```

The suite uses a loopback-only HTTP server for the real 429 → 200 exchange; the
managed sandbox therefore required permission to bind `127.0.0.1`. The intake
suite includes the repaired response-read case: one sibling succeeds once while
the other raises `IncompleteRead` on all three finite attempts; the warning records
one of two misses, four total attempts, and `coverage=incomplete`.

## Complete job-search test suite

```
$ ../../../.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
----------------------------------------------------------------------
Ran 829 tests in 12.561s

OK
```

## Required impact-selected repository gates

```
$ ../../../.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
impact from 'origin/main' (merge-base a7924731c09c): focused; lanes: policy, job-search
PASS   review-gate-verify-all  exit 0    12.6s
PASS   tests-job-search       exit 0    13.8s
PASS   instruction-budget     exit 0     0.1s
PASS   vendor-drift           exit 0     0.1s
PASS   reconciler             exit 0     0.1s
PASS   mail-send-less         exit 0     0.1s
PASS   skill-prompt-audit     exit 0     0.1s
PASS   compileall             exit 0     0.1s
PASS   filter-variants        exit 0     0.1s
PASS   verify-links           exit 0     0.7s
PASS   tests-recall-audit     exit 0     0.8s
PASS   leak-guard-tree        exit 0     1.2s
ALL GREEN (12 of 37 gates ran)
```

Lanes not selected because issue #235 does not touch them: maintenance, render,
resume, shared, applications, and publish.
