# Verification — 2026-07-31-shared-tests-import-vendored-copies

All output below is real, trimmed to the relevant lines. Absolute home paths are
redacted to `<repo-root>`.

## 1. The regression test fails against the pre-fix arrangement

The "before" run is the new test module with its `pin_shared_modules()` call
disabled (`if False: pin_shared_modules()`), which reproduces `main` exactly: no
finder on `sys.meta_path`, resolution decided by `sys.path` order.

```
$ .venv/bin/python -m unittest discover automation/shared/tests -p 'test_*.py' \
      -k CanonicalModuleResolutionTests
exit=1

FAIL: test_every_vendored_name_resolves_under_automation_shared (module='config')
AssertionError: False is not true : import config resolved to
  <repo-root>/skills/application-tracker/scripts/_vendor/config.py, which is not
  under automation/shared/ — a vendored copy is shadowing the module this suite
  claims to test
FAIL: test_every_vendored_name_resolves_under_automation_shared (module='job_metadata')
  ... resolved to <repo-root>/skills/application-tracker/scripts/_vendor/job_metadata.py
FAIL: test_every_vendored_name_resolves_under_automation_shared (module='layout')
  ... resolved to <repo-root>/skills/application-tracker/scripts/_vendor/layout.py
FAIL: test_every_vendored_name_resolves_under_automation_shared (module='location')
  ... resolved to <repo-root>/skills/application-tracker/scripts/_vendor/location.py
FAIL: test_every_vendored_name_resolves_under_automation_shared (module='metadata_editor')
  ... resolved to <repo-root>/skills/application-tracker/scripts/_vendor/metadata_editor.py
FAIL: test_every_vendored_name_resolves_under_automation_shared (module='skip_log')
  ... resolved to <repo-root>/skills/job-search/scripts/_vendor/skip_log.py
FAIL: test_every_vendored_name_resolves_under_automation_shared (module='store')
  ... resolved to <repo-root>/skills/job-search/scripts/_vendor/store/__init__.py
FAIL: test_submodules_of_vendored_packages_are_canonical_too (module='store.blobs')
FAIL: test_submodules_of_vendored_packages_are_canonical_too (module='store.serialization')
FAIL: test_resolution_survives_sys_modules_eviction   (7 modules)
FAIL: test_guard_beats_a_vendor_directory_at_the_front_of_sys_path  (all 10 names,
      every vendored directory — calendar_todos, company_index and mail included)

Ran 4 tests in 0.279s
FAILED (failures=39)
```

`test_every_test_module_installs_the_guard` also failed against the pre-fix tree,
listing all 26 test modules.

## 2. The same test passes after the fix

```
$ .venv/bin/python -m unittest discover automation/shared/tests \
      -k CanonicalModuleResolutionTests -k GuardWiringTests -v
test_every_vendored_name_resolves_under_automation_shared ... ok
test_guard_beats_a_vendor_directory_at_the_front_of_sys_path ... ok
test_resolution_survives_sys_modules_eviction ... ok
test_submodules_of_vendored_packages_are_canonical_too ... ok
test_every_test_module_installs_the_guard ... ok
test_explicit_path_loads_are_left_alone ... ok
test_the_finder_is_installed_ahead_of_the_path_finder ... ok
test_the_pinned_set_matches_the_vendoring_manifest ... ok

Ran 8 tests in 0.220s
OK
```

## 3. Full shared suite

```
$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 425 tests in 49.079s
OK
```

417 before this branch, 425 after (8 new).

## 4. Per-module shadowing audit — every `TARGETS`/`DIR_TARGETS` source

Probe: run `TestLoader().discover('automation/shared/tests')` (which imports every
test module into one process, exactly as the gate does), then resolve each
vendored name and print where it landed. Same script, run on `main` (via
`git stash -u`) and on this branch.

```
$ .venv/bin/python <scratch>/audit.py       # on main
CANONICAL  calendar_todos   -> automation/shared/calendar_todos.py
CANONICAL  company_index    -> automation/shared/company_index.py
SHADOWED   config           -> skills/application-tracker/scripts/_vendor/config.py
SHADOWED   job_metadata     -> skills/application-tracker/scripts/_vendor/job_metadata.py
SHADOWED   layout           -> skills/application-tracker/scripts/_vendor/layout.py
SHADOWED   location         -> skills/application-tracker/scripts/_vendor/location.py
CANONICAL  mail             -> automation/shared/mail/__init__.py
SHADOWED   metadata_editor  -> skills/application-tracker/scripts/_vendor/metadata_editor.py
SHADOWED   skip_log         -> skills/job-search/scripts/_vendor/skip_log.py
SHADOWED   store            -> skills/job-search/scripts/_vendor/store/__init__.py

$ .venv/bin/python <scratch>/audit.py       # on fix/01-shared-tests-import-path
CANONICAL  calendar_todos   -> automation/shared/calendar_todos.py
CANONICAL  company_index    -> automation/shared/company_index.py
CANONICAL  config           -> automation/shared/config.py
CANONICAL  job_metadata     -> automation/shared/job_metadata.py
CANONICAL  layout           -> automation/shared/layout.py
CANONICAL  location         -> automation/shared/location.py
CANONICAL  mail             -> automation/shared/mail/__init__.py
CANONICAL  metadata_editor  -> automation/shared/metadata_editor.py
CANONICAL  skip_log         -> automation/shared/skip_log.py
CANONICAL  store            -> automation/shared/store/__init__.py
```

Per-module result and why:

| Module | Before | Why | After |
|--------|--------|-----|-------|
| `config` | SHADOWED | `test_backfill_job_metadata` (first alphabetically) imports `backfill_job_metadata`, which puts its own `_vendor/` on `sys.path` and imports it | FIXED |
| `job_metadata` | SHADOWED | same path | FIXED |
| `layout` | SHADOWED | same path | FIXED |
| `location` | SHADOWED | same path | FIXED |
| `metadata_editor` | SHADOWED | same path | FIXED |
| `skip_log` | SHADOWED | `test_search_job_metadata` puts `skills/job-search/scripts/_vendor` on `sys.path`; the job-search scripts import it | FIXED |
| `store` | SHADOWED | same path (`store.blobs`, `store.serialization` followed the shadowed parent) | FIXED |
| `calendar_todos` | not affected **by luck** | vendored to application-tracker, whose `_vendor/` IS on `sys.path` — it stayed canonical only because `test_calendar_todos` inserted `automation/shared` at position 0 later. `test_guard_beats_a_vendor_directory_at_the_front_of_sys_path` shows it flipping to the vendored copy the moment that order changes | now pinned |
| `company_index` | not affected **by luck** | one vendored copy (application-tracker); same ordering accident as above, and the same test shows it flipping | now pinned |
| `mail` | not affected | its only copy is `skills/email-assistant/scripts/_vendor/mail`, and no test module in this suite ever puts the email-assistant script directory on `sys.path`. The hazard test forces that directory to `sys.path[0]` and confirms the pin holds | now pinned |

None of the three "not affected" modules was safe by design; each was safe by the
alphabetical accident the task says will drift back.

## 5. Vendoring drift still clean

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## 6. The vendored copies are still tested — by the per-skill suites

The pin applies only inside `automation/shared/tests`. The skill suites run in
their own processes and still import their own `_vendor/` copies:

```
$ JOBHUNT_CONFIG=$PWD/config.example.yaml .venv/bin/python -m unittest discover \
      -s skills/application-tracker/scripts/tests
Ran 77 tests in 49.156s ... OK
$ JOBHUNT_CONFIG=$PWD/config.example.yaml .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
Ran 333 tests in 39.400s ... OK
```

## 7. Full gate

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
