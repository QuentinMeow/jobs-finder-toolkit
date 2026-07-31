# Verification — 2026-07-29-vendored-config-repo-root-wrong

All output below is real, trimmed to the relevant lines. The repo root is written
`<repo-root>` and the throwaway config-less worktree `<worktree>`; nothing else is
edited.

## 1. `REPO_ROOT` / `EXAMPLE_CONFIG` in all five copies

Same probe script before and after: import each copy of `config.py` under its own
module name and print the two constants.

BEFORE:

```
$ .venv/bin/python <scratch>/probe_roots.py
automation/shared/config.py
    REPO_ROOT      = <repo-root>
    EXAMPLE_CONFIG = <repo-root>/config.example.yaml   exists=True
skills/resume-writer/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>/skills/resume-writer
    EXAMPLE_CONFIG = <repo-root>/skills/resume-writer/config.example.yaml   exists=False
skills/application-tracker/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>/skills/application-tracker
    EXAMPLE_CONFIG = <repo-root>/skills/application-tracker/config.example.yaml   exists=False
skills/job-search/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>/skills/job-search
    EXAMPLE_CONFIG = <repo-root>/skills/job-search/config.example.yaml   exists=False
skills/email-assistant/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>/skills/email-assistant
    EXAMPLE_CONFIG = <repo-root>/skills/email-assistant/config.example.yaml   exists=False
```

AFTER:

```
$ .venv/bin/python <scratch>/probe_roots.py
automation/shared/config.py
    REPO_ROOT      = <repo-root>
    EXAMPLE_CONFIG = <repo-root>/config.example.yaml   exists=True
skills/resume-writer/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>
    EXAMPLE_CONFIG = <repo-root>/config.example.yaml   exists=True
skills/application-tracker/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>
    EXAMPLE_CONFIG = <repo-root>/config.example.yaml   exists=True
skills/job-search/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>
    EXAMPLE_CONFIG = <repo-root>/config.example.yaml   exists=True
skills/email-assistant/scripts/_vendor/config.py
    REPO_ROOT      = <repo-root>
    EXAMPLE_CONFIG = <repo-root>/config.example.yaml   exists=True
```

## 2. `_config_layer_present()` through a vendored import

`search_jobs` imports `scripts/_vendor/config.py` (its `sys.path` puts `_vendor/`
first). `$JOBHUNT_CONFIG` aimed at the tracked example is exactly how CI invokes
the job-search and resume-writer suites.

BEFORE — the store's "not configured" notice fires on an example-config run:

```
$ JOBHUNT_CONFIG=<repo-root>/config.example.yaml .venv/bin/python -c '...'
config module file   : <repo-root>/skills/job-search/scripts/_vendor/config.py
config_path()        : <repo-root>/config.example.yaml
config.EXAMPLE_CONFIG: <repo-root>/skills/job-search/config.example.yaml
_config_layer_present(): True
```

AFTER:

```
$ JOBHUNT_CONFIG=<repo-root>/config.example.yaml .venv/bin/python -c '...'
config module file   : <repo-root>/skills/job-search/scripts/_vendor/config.py
config_path()        : <repo-root>/config.example.yaml
config.EXAMPLE_CONFIG: <repo-root>/config.example.yaml
_config_layer_present(): False
```

The new test pinning this (`VendoredExampleConfigTests`) fails against the
pre-fix `config.py` — run in the worktree with only the five `config.py` copies
reverted to HEAD and the new tests present:

```
$ .venv/bin/python -m unittest test_store_integration.VendoredExampleConfigTests -v
FAIL: test_config_layer_absent_on_the_tracked_example_config
    self.assertEqual(self._probe("search_jobs._config_layer_present()"), "False")
AssertionError: 'True' != 'False'
- True
+ False

FAIL: test_vendored_example_config_constant_points_at_a_real_file
AssertionError: 'False' != 'True'

Ran 2 tests in 0.618s
FAILED (failures=2)
```

Same experiment for the five-copy invariant test:

```
$ .venv/bin/python -m unittest test_config_accessors.RepoRootResolutionTests -v
AssertionError: ...'/skills/application-tracker') != ...'<worktree>')
AssertionError: ...'/skills/job-search')         != ...'<worktree>')
AssertionError: ...'/skills/email-assistant')    != ...'<worktree>')
Ran 2 tests in 0.017s
FAILED (failures=8)
```

Both pass with the fix (verbose run in the working tree):

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests -v -p 'test_store_integration.py'
test_config_layer_absent_on_the_tracked_example_config ... ok
test_vendored_example_config_constant_points_at_a_real_file ... ok
Ran 16 tests in 30.488s
OK

$ .venv/bin/python -m unittest discover automation/shared/tests -p 'test_config_accessors.py' -v
test_example_config_marks_the_root_of_a_git_less_export ... ok
test_falls_back_to_the_modules_own_directory_with_no_marker ... ok
test_git_file_marker_of_a_worktree_is_honoured ... ok
test_git_marker_wins ... ok
test_every_copy_points_example_config_at_a_real_file ... ok
test_every_copy_resolves_the_same_repo_root ... ok
Ran 23 tests in 0.113s
OK
```

## 3. The leak guard still tells the example config from a real one

`check_public.py` imports the CANONICAL module, whose `REPO_ROOT` was already the
repo root and is byte-for-byte the same value after the change (section 1, first
row). Both discriminations verified directly:

```
$ JOBHUNT_CONFIG=<repo-root>/config.example.yaml .venv/bin/python -c '...'
config module     : <repo-root>/automation/shared/config.py
config.REPO_ROOT  : <repo-root>
EXAMPLE_CONFIG    : <repo-root>/config.example.yaml
identity_status   : fictional example config (<repo-root>/config.example.yaml) — no identity resolved from config
identity_tokens   : []

$ env -u JOBHUNT_CONFIG -u JOBHUNT_PERSONAL_TOKENS .venv/bin/python -c '...'
config.REPO_ROOT  : <repo-root>
config_path()     : <repo-root>/config.yaml
identity_status   : real config (<repo-root>/config.yaml)
identity token cnt: 4 (non-zero => guard is ARMED)
```

Arming tests:

```
$ .venv/bin/python -m unittest discover automation/publish/tests -p 'test_leak_guard.py' -v
test_allow_unarmed_still_passes_on_the_clean_tree (ArmingCLITests) ... ok
test_unarmed_run_exits_nonzero (ArmingCLITests) ... ok
test_env_var_arms_the_guard (ArmingTests) ... ok
test_example_config_yields_zero_identity_tokens (ArmingTests) ... ok
test_supplementary_tokens_alone_never_arm_the_guard (ArmingTests) ... ok
test_unarmed_report_names_the_config_it_looked_for (ArmingTests) ... ok
Ran 49 tests in 18.614s
OK
```

No leak-guard edit was needed or made.

## 4. Definition-of-done command list (working tree, real config present)

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 323 tests in 28.814s
OK

$ .venv/bin/python -m unittest discover automation/publish/tests
Ran 137 tests in 73.628s
OK

$ .venv/bin/python -m unittest discover skills/job-search/scripts/tests
Ran 314 tests in 186.256s
OK

$ .venv/bin/python -m unittest discover skills/resume-writer/scripts/tests
Ran 92 tests in 35.367s
OK

$ .venv/bin/python -m unittest discover skills/application-tracker/scripts/tests
Ran 51 tests in 20.350s
OK

$ .venv/bin/python -m unittest discover automation/maintenance/gardener/tests
Ran 27 tests in 5.375s
OK

$ .venv/bin/python automation/publish/check_public.py
Public-repo leak guard
  repo root:      <repo-root>
  tracked files:  710
  identity tokens:      4 (config.yaml / $JOBHUNT_PERSONAL_TOKENS)
  supplementary tokens: 7 (leak_tokens.txt; never arming)
  active tokens:        11 (union, deduped)
  identity source:      real config (<repo-root>/config.yaml)

OK: no public-repo leaks detected. Safe to publish.

$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (8 checks clean)

$ .venv/bin/python automation/maintenance/gardener/verify_links.py
  references: all resolve
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync
  OK: links, symlinks, and vendored copies verified.

$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.
```

## 5. Config-less checkout (no `config.yaml`, no `private/`, no token secret)

```
$ git worktree add --detach -f <worktree> HEAD
Preparing worktree (detached HEAD 3c7620b)
```

BEFORE the patch — the fallback pointed at a file that cannot exist, so a truly
config-less run loaded an EMPTY config and the example persona never appeared:

```
$ cd <worktree> && env -u JOBHUNT_CONFIG -u JOBHUNT_PERSONAL_TOKENS <repo-root>/.venv/bin/python -c '...'
config: no config.yaml found — using the fictional example persona at
  <worktree>/skills/job-search/config.example.yaml. ...
config: <worktree>/skills/job-search/config.example.yaml could not be read
  ([Errno 2] No such file or directory: ...); continuing with an EMPTY
  configuration — every value falls back to its default.
config module        : <worktree>/skills/job-search/scripts/_vendor/config.py
REPO_ROOT            : <worktree>/skills/job-search
EXAMPLE_CONFIG       : <worktree>/skills/job-search/config.example.yaml
config_path()        : <worktree>/skills/job-search/config.example.yaml
candidate_name()     : ''
```

AFTER the patch — the Jordan Rivers example actually loads, and the
"could not be read / EMPTY configuration" line is gone:

```
$ cd <worktree> && env -u JOBHUNT_CONFIG -u JOBHUNT_PERSONAL_TOKENS <repo-root>/.venv/bin/python -c '...'
config: no config.yaml found — using the fictional example persona at
  <worktree>/config.example.yaml. ...
config module        : <worktree>/skills/job-search/scripts/_vendor/config.py
REPO_ROOT            : <worktree>
EXAMPLE_CONFIG       : <worktree>/config.example.yaml   exists= True
config_path()        : <worktree>/config.example.yaml
candidate.name       : 'Jordan Rivers'
candidate.name_slug  : 'Jordan_Rivers'
resume_stem()        : Jordan_Rivers_Software_Engineer_Resume
_config_layer_present(): False
```

Full gate list re-run there (cwd = worktree, `env -u JOBHUNT_CONFIG -u
JOBHUNT_PERSONAL_TOKENS`, repo venv python):

```
### sync_vendored.py --check
vendored copies in sync
--- exit=0

### unittest discover automation/shared/tests
Ran 323 tests in 11.259s
OK
--- exit=0

### unittest discover automation/publish/tests
Ran 137 tests in 78.041s
OK (skipped=1)
  identity source:  fictional example config (<tmp>/export/config.example.yaml) — no identity resolved from config
  OK: no public-repo leaks detected. Safe to publish.
--- exit=0

### unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
Ran 314 tests in 23.757s
OK
--- exit=0

### unittest discover skills/resume-writer/scripts/tests
Ran 92 tests in 34.923s
OK
--- exit=0

### unittest discover skills/application-tracker/scripts/tests
Ran 51 tests in 21.789s
OK
--- exit=0

### unittest discover automation/maintenance/gardener/tests
Ran 27 tests in 4.823s
OK
--- exit=0

### automation/publish/check_public.py
Public-repo leak guard
--- exit=2

### automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (8 checks clean)
--- exit=0

### automation/maintenance/gardener/verify_links.py
  OK: links, symlinks, and vendored copies verified.
--- exit=0

### automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.
--- exit=0
```

Two results need reading, neither caused by this change:

- `check_public.py` exit **2** is `EXIT_UNARMED`: a config-less tree with no
  `JOBHUNT_PERSONAL_TOKENS` has zero identity tokens, so the guard fails closed.
  CI branches on exactly that (`ci.yml` runs `--allow-unarmed` when the secret is
  absent). Reverting only the five `config.py` copies to HEAD in the same
  worktree gives the **same exit 2**, so it is pre-existing. The CI branch is
  clean with the fix:

```
$ automation/publish/check_public.py --allow-unarmed
WARNING: leak guard is UNARMED (--allow-unarmed): zero identity tokens ...
  identity source:  fictional example config (<worktree>/config.example.yaml) — no identity resolved from config
OK: no public-repo leaks detected. Safe to publish.
--- exit=0
```

- `OK (skipped=1)` in `automation/publish/tests` is
  `test_skill_manifests.py:340` — `skipTest("private overlay not mounted")`.
  Expected without `private/`.

## 6. Evidence that the `config.example.yaml` fallback marker is load-bearing

`test_export_arming` / `test_export_enumeration` run the leak guard inside an
EXPORTED tree, which has no `.git` (the exporter only creates one under
`--git-init`). Both the local and the config-less runs report:

```
  identity source:  fictional example config (<tmp>/export/config.example.yaml) — no identity resolved from config
```

so the exported tree resolves its root through marker 2. A `_HERE`-only fallback
would have made that read `real config (...)`, silently changing the exporter's
arming report. Marker precedence is pinned by `RepoRootMarkerTests`.
