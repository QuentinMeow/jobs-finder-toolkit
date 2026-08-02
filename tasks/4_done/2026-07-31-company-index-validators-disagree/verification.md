# Verification — 2026-07-31-company-index-validators-disagree

Every command below was run from the repo root on `fix/07-company-key-validators-agree`
(based on `fix/06-company-key-guard-transitive`). "BEFORE" runs use a detached worktree
at the base tip with only the NEW TEST FILES copied in, so the old source is under test.
Every fixture is fictional (`acme-*`); no real employer appears anywhere below.

## 0. The agreement table — the whole point of the task

Driver: all five input classes through all three validators, one temp tree each.

```
| company_key   | validate_meta | reconciler | --company-keys --strict |
|---------------|---------------|------------|-------------------------|
| absent        | OK            | clean      | unkeyed, exit 0         |
| 'acme-labs\n' | ERROR         | FINDING    | malformed, exit 1       |
| ''            | ERROR         | FINDING    | malformed, exit 1       |
| false         | ERROR         | FINDING    | malformed, exit 1       |
| 0             | ERROR         | FINDING    | malformed, exit 1       |
```

Before, the same driver produced (from the task's reproductions): `'acme-labs\n'` →
accepted / FINDING / **counted keyed AND resolved, exit 0**; `''`/`false`/`0` → ERROR /
FINDING / **counted unkeyed, exit 0**.

## 1. Box 1 — trailing whitespace

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_company_index.py'
BEFORE  FAIL: test_a_trailing_newline_is_not_a_valid_key (KeyShapeTests)
AFTER   OK

$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_job_metadata.py'
BEFORE  FAIL: test_the_five_input_classes_all_three_validators_must_agree_on (key='acme-labs\n')
AFTER   OK  (98 tests)
```

`test_no_surrounding_whitespace_is_tolerated_in_a_company_key` pins the answer to
"none of the three strips": leading/trailing blank, tab, `\r\n` and an embedded newline
are all rejected.

## 2. Box 2 — `--company-keys` tells unkeyed from malformed

```
$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests \
      -t skills/application-tracker/scripts/tests -p 'test_company_keys_report.py'
BEFORE
  FAIL  test_a_malformed_company_key_is_not_counted_as_unkeyed  (empty-string, false, zero)
  ERROR test_a_malformed_company_key_is_not_counted_as_unkeyed  (trailing-newline)
  FAIL  test_a_malformed_company_key_fails_under_strict         (all four shapes)
  ERROR test_absent_is_the_one_class_that_stays_clean_everywhere
  ERROR test_an_empty_index_file_is_named_rather_than_counted_as_zero_keys
  FAIL  test_a_directory_at_the_index_path_is_reported_not_treated_as_absent
  Ran 12 tests — FAILED (failures=8, errors=3)
AFTER
  Ran 12 tests — OK
```

The `ERROR`s are `KeyError` on JSON fields the old report did not emit (`malformed`,
`index_empty`) — the report literally could not express the distinction.

## 3. Box 3 — duplicate top-level keys

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_company_index.py'
BEFORE  ERROR: test_a_duplicate_top_level_key_is_a_finding      (AttributeError: 'dict' has no 'duplicates')
        ERROR: test_a_clean_file_reports_no_duplicates
AFTER   OK

$ .venv/bin/python -m unittest automation.reconcile.tests.test_reconcile
BEFORE  FAIL: test_a_duplicate_top_level_key_is_a_finding
AFTER   OK  (40 tests)
```

Live check of the finding text:

```
$ (temp file with `acme-labs:` written twice)
raw.duplicates -> ('acme-labs',)
lint -> [('acme-labs', 'this top-level key is defined more than once — YAML keeps the
          LAST one silently, so one employer is deleted and the other inherits its key.
          Merge the two entries, or give one a new key')]
```

## 4. Box 4 — display↔display and key↔display collisions; `resolve()` is total

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_company_index.py'
BEFORE
  FAIL: test_two_entries_sharing_a_display_name_is_a_finding
  FAIL: test_displays_differing_only_by_a_non_breaking_space_collide
  FAIL: test_a_display_that_is_another_entrys_key_is_a_finding
  FAIL: test_an_unlinted_collision_really_does_flip_with_file_order
AFTER   OK
```

`test_resolve_is_total_on_a_lint_clean_index` walks every claimed spelling of a
lint-clean fixture and asserts it resolves to its own entry. Two guards keep the rule
from over-firing: an entry may still spell itself more than one way, and the alias
guards from phase 7 are untouched.

## 5. Box 5 — not-a-regular-file at the index path

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_company_index.py'
BEFORE  FAIL: test_a_directory_at_the_index_path_raises
        FAIL: test_a_dangling_symlink_at_the_index_path_raises
AFTER   OK

$ .venv/bin/python -m unittest automation.reconcile.tests.test_reconcile
BEFORE  FAIL: test_a_directory_at_the_index_path_is_a_finding_not_a_no_op
        FAIL: test_a_dangling_symlink_at_the_index_path_is_a_finding
        FAIL: test_an_empty_index_file_is_a_finding
        ERROR: test_the_is_dir_guard_precedes_every_import
AFTER   OK
```

Both new errors land in the reconciler's existing `unreadable:` handler — the same
place `chmod 000` already landed. `test_a_symlink_to_a_real_index_still_loads` guards
the rule at not-a-regular-file rather than not-a-symlink.

## 6. Box 6 — the detector says NOT INSPECTED when it found nothing

```
$ .venv/bin/python -m unittest discover -s automation/publish/tests -p 'test_review_gate.py'
BEFORE  FAIL: test_an_index_that_yields_no_names_reports_not_inspected (shape='empty mapping')
        FAIL: ... (shape='entries that are not mappings')
        FAIL: ... (shape='entries with no display')
AFTER   Ran 55 tests — OK
```

All three shapes used to print `(advisory only):  (none)`; all three now print the
`NOT INSPECTED` banner, and the banner's wording no longer claims the file is absent.

## 7. Box 7 — the stop-list test can fail

The defect lives in the TEST, so the before/after is the same poison run against the
two test files. A nonce token that occurs nowhere else in the tree is added to
`ALIAS_STOP_LIST` in `automation/shared/company_index.py`; the guard should go red.

```
$ (base worktree, BASE test file, corpus INCLUDES company_index.py + test_company_index.py)
$ .venv/bin/python -m unittest discover -s automation/shared/tests \
      -p 'test_company_index.py' -k stop_list
Ran 3 tests in 0.102s
OK                      <-- the guard passed with a poisoned list. It cannot fail.

$ (same poison, NEW test file, carriers excluded by filename)
FAIL: test_stop_list_holds_no_vocabulary_new_to_this_repo (AliasTests)
AssertionError: Lists differ: ['qqzznonceword'] != []
: these tokens are new vocabulary — publishing them would blind the advisory leak detector
Ran 4 tests in 0.259s
FAILED (failures=1)
```

The claim the guard defends is unchanged and still true. Re-measured against the
narrowed corpus:

```
tokens: 152
new to the corpus once the two list-carrying files are excluded: 0
[]
```

Exclusion is by FILENAME, so the byte-identical vendored copies go with it. An
in-suite `assertNotIn` on the nonce fails if the exclusion ever stops working, so the
tautology cannot come back silently.

## 8. Blast radius on the owner's real index and applications

Shapes and counts only — no names.

```
$ (lint the real index through the new loader and every new rule)
type: RawIndex   entries: 222   duplicates: 0
TOTAL FINDINGS: 0
```

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --company-keys --strict --json
index_present = True    index_empty = False    index_error =        index_keys = 222
applications = 243      keyed = 243            distinct_keys = 208
unkeyed = 0             malformed = 0          unresolved = 0       ok = True   exit 0
```

**No new lint rule fired on the real index.** Nothing to fix, nothing to file.

## 9. Full gate, green, on the final tree

```
$ zsh <scratch>/gate.sh
===== gates =====
PASS  vendor-drift
PASS  byte-compile
PASS  reconcile
PASS  leak-guard
PASS  review-gate
PASS  instruction-budget
PASS  verify-links
PASS  mail-safety
===== unit suites =====
PASS  tests:reconcile
PASS  tests:gardener
PASS  tests:hooks
PASS  tests:shared
PASS  tests:publish
PASS  tests:store-example
PASS  tests:resume-writer
PASS  tests:job-search
PASS  filter-variants
PASS  tests:app-tracker
PASS  tests:github-wf
===== export dry-run =====
PASS  export-strict

ALL GREEN
```

## 10. CI's shape reproduced in a clean worktree

```
$ git worktree add --detach <scratch>/ci_wt HEAD
$ ls <scratch>/ci_wt | grep -E '^(private|config\.yaml)$'      # empty — neither present
$ (affected suites run there)
```

See the worklog for the transcript of that run.
