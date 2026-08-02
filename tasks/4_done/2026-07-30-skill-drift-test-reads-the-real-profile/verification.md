# Verification — a gardener test reads the owner's real profile

Every command below was run from the repo root on branch `fix/03-owner-data-paths`, with the
private overlay mounted and `JOBHUNT_CONFIG` unset — the condition the defect needs.
Absolute home paths are redacted to `<repo-root>`.

## The defect, reproduced before the fix

```
$ unset JOBHUNT_CONFIG; .venv/bin/python -m unittest discover automation/gardener/tests
......................................x.............................................
----------------------------------------------------------------------
Ran 84 tests in 54.988s

OK (expected failures=1)
gardener · skill-drift (report-only) [DRY-RUN]
  policy: private/docs/03-folder-structure-and-memory.md
  baseline: private/me/baseline.yaml
  profile:  private/me/profile.md
  DRIFT: 1 baseline skill token(s) are not in the profile's canonical Skills lists (non-canonical spelling?):
    DRIFT  Skills: <one real skill token from the owner's baseline, redacted here>
  (report-only — fix the baseline spelling to match the profile, or add the skill to the profile's Skills lists.)
```

The suite passed while printing a report derived from the owner's real baseline and profile.

## After the fix — the same command prints nothing about the overlay

```
$ unset JOBHUNT_CONFIG; .venv/bin/python -m unittest discover -s automation/gardener/tests -p 'test_skill_drift.py'
.......
----------------------------------------------------------------------
Ran 7 tests in 0.094s

OK
```

The resolution is now asserted inside the test, not inferred from the absence of output:
`test_run_is_report_only_and_resolves_inside_its_fixture` pins `config.baseline_path()` and
`config.profile_md_path()` to files in its own temp directory, and re-checks the same two paths
on the dict `skill_drift.analyze()` returns, before calling `run()`.

## The regression detector fails on the pre-fix test

`test_fixture_isolation.py` re-runs the rest of the folder's suite in a subprocess under a
`sys.addaudithook` recorder with `JOBHUNT_CONFIG` unset, and fails if any file under
`<repo-root>/private/` is opened. Restoring the old test body and running only the guard:

```
$ git show HEAD:automation/gardener/tests/test_skill_drift.py > automation/gardener/tests/test_skill_drift.py
$ .venv/bin/python -m unittest discover -s automation/gardener/tests -p 'test_fixture_isolation.py'
AssertionError: Lists differ: [...] != []

First list contains 2 additional elements.
First extra element 0:
'<repo-root>/private/me/baseline.yaml'

+ []
- ['<repo-root>/private/me/baseline.yaml',
-  '<repo-root>/private/me/profile.md'] : a test in automation/gardener/tests read the owner's
  private overlay with no JOBHUNT_CONFIG pin. Pin the config at a fixture (see
  test_skill_drift._pinned_config) and assert the resolved paths.

----------------------------------------------------------------------
Ran 2 tests in 48.055s

FAILED (failures=1)
```

The fixed test was then restored.

## The detector is proved live, not vacuous

In a checkout with no overlay (CI, any contributor clone) `private/` does not exist, so the
overlay assertion alone would pass forever even if the audit hook were broken. The companion
canary plants a read inside a scratch "guarded" tree and asserts the recorder catches it:

```
$ .venv/bin/python -m unittest discover -s automation/gardener/tests -p 'test_fixture_isolation.py' -v
test_no_test_in_this_folder_reads_the_private_overlay ... ok
test_the_recorder_catches_a_read_under_the_guarded_tree
Canary: without this, a checkout with no overlay passes vacuously forever. ... ok

----------------------------------------------------------------------
Ran 2 tests in 50.773s

OK
```

## The `expected failures=1` question from the task

Still the right expectation, and not a leftover.
`test_verify_links.test_link_inside_an_indented_code_block_is_not_a_link` encodes DESIGN §1d
step 2, which `_mask_fences()` does not implement — it masks fences and HTML comments only. It
still fails, so it is reported as an expected failure rather than an unexpected success, which
is exactly the signal the marker is for. No change made.

## Cost, stated plainly

The guard's child is a second full run of the folder's suite, ~45s of which is
`test_verify_links` building a temp git repo per test. The folder went from ~47s to ~97s. The
cheaper fix is to speed up that module, not to narrow the guard.

## Full gate

```
$ zsh <scratch>/gate.sh
ALL GREEN
```
