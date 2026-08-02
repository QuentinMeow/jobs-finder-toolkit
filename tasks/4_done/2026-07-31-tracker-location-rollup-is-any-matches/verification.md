# Verification — 2026-07-31-tracker-location-rollup-is-any-matches

Every command below was run on branch `wip/35-pipeline-parse-defects`. The
"before" runs are the same tree with only
`skills/application-tracker/scripts/status.py` reverted to its committed state.
The fixture tree is a throwaway under `<scratch>` with its own `JOBHUNT_CONFIG`;
every company, slug and location is fictional.

**The task's "before/after counts from a real run over
`config.applications_root()`" bullet is deliberately NOT satisfied, and cannot
be.** That root is under `private/`, which this branch must not read. Everything
below is measured against fixtures, and the PR body states in plain words what
the owner should expect the first time they run the command instead.

## Fixture

One `6_drafted` folder holding two postings — one in a preferred metro, one
foreign — plus a second folder where the foreign posting records **no**
`location` at all and only its own `jd_file` says where it is.

```
examplecorp-platform-engineer-20260715/meta.yaml
  jobs:
    - {role: Platform Engineer,       location: "Springfield, ST",       jd_file: JD-platform-engineer.md}
    - {role: Infrastructure Engineer, location: "London, United Kingdom", jd_file: JD-infrastructure-engineer.md}

examplecorp-data-engineer-20260716/meta.yaml
  jobs:
    - {role: Data Engineer, location: "Springfield, ST", jd_file: JD-data-engineer.md}
    - {role: ML Engineer,   location: "",                jd_file: JD-ml-engineer.md}   # JD says Berlin, Germany
```

Policy: `metro: [springfield, fairview]`, `allow_us_remote: true`, `us_only: true`.

## BEFORE — both folders report `ok / metro` and the command exits 0

```
$ JOBHUNT_CONFIG=<scratch>/loc/config.yaml .venv/bin/python \
      skills/application-tracker/scripts/status.py --check-locations
SLUG                                    MATCH  CATEGORY       LOCATIONS
examplecorp-data-engineer-20260716      ok     metro          Springfield, ST
examplecorp-platform-engineer-20260715  ok     metro          Springfield, ST | London, United Kingdom
Total: 2  |  match: 2  |  mismatch: 0  |  review: 0  |  unreadable: 0
RC=0
```

Two separate failures visible in one screen: the London posting is masked by its
Springfield sibling, and the blank-`location` posting is missing from the
LOCATIONS column entirely — the pooled fallback only consulted JD files when
meta.yaml recorded *no* location anywhere in the folder.

## AFTER — worst-wins, offending posting named, non-zero exit

```
$ JOBHUNT_CONFIG=<scratch>/loc/config.yaml .venv/bin/python \
      skills/application-tracker/scripts/status.py --check-locations
SLUG                                    MATCH  CATEGORY       LOCATIONS
examplecorp-data-engineer-20260716      NO     foreign        Springfield, ST | Berlin, Germany
examplecorp-platform-engineer-20260715  NO     foreign        Springfield, ST | London, United Kingdom
Total: 2  |  match: 0  |  mismatch: 2  |  review: 0  |  unreadable: 0

Mismatches (outside the configured location policy):
  - examplecorp-data-engineer-20260716  [foreign]  Springfield, ST | Berlin, Germany
      offending posting: ML Engineer: Berlin, Germany
  - examplecorp-platform-engineer-20260715  [foreign]  Springfield, ST | London, United Kingdom
      offending posting: Infrastructure Engineer: London, United Kingdom
RC=1
```

Berlin now appears in the column because the blank-`location` posting is read
from its own `jd_file`, mirroring `handoff.job_locations`.

## The regression tests fail against the pre-change code

```
$ git checkout -- skills/application-tracker/scripts/status.py     # before
$ .venv/bin/python -m unittest discover \
      -s skills/application-tracker/scripts/tests \
      -t skills/application-tracker/scripts/tests -p 'test_check_locations.py' -v
test_all_matching_exits_zero ... ok
test_mismatch_and_unknown_still_fails_on_mismatch_only ... ok
test_office_list_with_jd_remote_alternative_matches ... ok
test_real_mismatch_exits_nonzero ... ok
test_unknown_location_is_review_not_failure ... ok
test_a_blank_location_posting_is_read_from_its_own_jd ... FAIL
test_a_definite_mismatch_outranks_an_unknown_sibling ... FAIL
test_an_unlocatable_posting_is_review_and_does_not_block ... FAIL
test_every_posting_in_policy_still_passes ... ok
test_one_foreign_posting_fails_the_whole_folder ... FAIL
Ran 10 tests in 2.250s
FAILED (failures=4)
```

The five pre-existing single-posting cases pass both ways — the single-role
folder's verdict is unchanged, which is the point. `test_every_posting_in_policy_
still_passes` also passes both ways on purpose: it is the guard that worst-wins
does not start failing folders that are fine.

After the change:

```
$ .venv/bin/python -m unittest discover \
      -s skills/application-tracker/scripts/tests \
      -t skills/application-tracker/scripts/tests -p 'test_check_locations.py' -v
... all 10 ok
Ran 10 tests in 2.143s
OK
```

`review` still does not fail the command
(`test_an_unlocatable_posting_is_review_and_does_not_block`, rc 0), and
`no_match` still outranks `review` in the rollup
(`test_a_definite_mismatch_outranks_an_unknown_sibling`, rc 1).

## Suites

```
$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests
Ran 116 tests in 43.822s
OK

$ .venv/bin/python -m unittest discover -s automation/shared/tests
Ran 593 tests in 17.906s
OK
```
