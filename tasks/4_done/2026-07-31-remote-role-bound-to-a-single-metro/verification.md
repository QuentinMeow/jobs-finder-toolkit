# Verification — 2026-07-31-remote-role-bound-to-a-single-metro

Commands run on `wip/30-canary-found-defects`, output trimmed to the relevant
lines. The "before" column comes from running the SAME new tests against
`HEAD`'s `automation/shared/location.py`.

## The reported shape, before and after

```
$ .venv/bin/python - <<'PY'   # policy metro: [springfield]
  ... assess_location(<location>, policy, description=<jd>) ...
PY

BEFORE (HEAD)
  remote grant + reside in non-pref metro  -> match    / us_remote
  remote grant + reside in PREFERRED metro -> match    / us_remote
AFTER  (this branch)
  remote grant + reside in non-pref metro  -> no_match / other_us   (jd_remote_bound_to_residency)
  remote grant + reside in PREFERRED metro -> match    / metro      (jd_residency_preferred_metro)
```

## New unit coverage fails against the pre-fix module

```
$ python -m unittest discover -s automation/shared/tests -p 'test_location.py'   # pre-fix location.py
FAIL: test_non_preferred_residency_metro_is_no_match (test_location.ResidencyRestrictedRemoteTests...)
FAIL: test_preferred_residency_metro_still_matches (test_location.ResidencyRestrictedRemoteTests...)
FAIL: test_foreign_residency_requirement_is_no_match (test_location.ResidencyRestrictedRemoteTests...)
FAIL: test_unreadable_residency_place_goes_to_review_not_us_remote (test_location.ResidencyRestrictedRemoteTests...)
FAIL: test_bare_remote_with_no_us_signal_anywhere_is_review (test_location.BareRemoteWithoutUsScopeTests...)
FAIL: test_bare_remote_alone_is_not_a_us_signal (test_location.RemoteRegressionTests...)
Ran 44 tests in 0.037s
FAILED (failures=6)
```

## Corpus regressions fail against the pre-fix module

```
$ python skills/job-search/scripts/validate_filter_variants.py --check   # pre-fix location.py
CHECK location-remote-grant-bound-to-a-non-preferred-metro: decision: expected 'no_match', got 'match'
CHECK location-remote-grant-bound-to-a-non-preferred-metro: category: expected 'other_us', got 'us_remote'
CHECK location-remote-grant-bound-to-a-non-preferred-metro: evidence missing ['jd_remote_bound_to_residency']
CHECK location-remote-grant-bound-to-a-preferred-metro: category: expected 'metro', got 'us_remote'
CHECK location-remote-grant-with-unreadable-residency-place: decision: expected 'review', got 'match'
CHECK location-remote-grant-with-unreadable-residency-place: review_reasons missing ['residency_restriction_unparsed']
CHECK location-bare-remote-word-without-any-us-signal: decision: expected 'review', got 'match'
CHECK location-bare-remote-word-without-any-us-signal: review_reasons missing ['remote_without_us_scope']
```

## Everything green on this branch

```
$ python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 77 cases

$ python -m unittest discover -s automation/shared/tests -t automation/shared/tests
Ran 587 tests in 21.778s
OK

$ JOBHUNT_CONFIG="$PWD/config.example.yaml" python -m unittest discover \
    -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
Ran 477 tests in 51.867s
OK

$ JOBHUNT_CONFIG="$PWD/config.example.yaml" python -m unittest discover \
    -s skills/application-tracker/scripts/tests
Ran 108 tests in 58.797s
OK

$ python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```
