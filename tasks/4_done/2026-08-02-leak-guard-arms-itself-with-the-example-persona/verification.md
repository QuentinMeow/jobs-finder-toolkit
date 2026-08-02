# Verification — 2026-08-02-leak-guard-arms-itself-with-the-example-persona

All runs from a git worktree of `fix/leak-guard-fail-open`, using that worktree's
own copy of every script. The probe token is the literal `ZZPROBEZZ` — no real
identity token appears in any command, log, or assertion here.

## The blocked export, before and after

BEFORE — worktree at `main` (`f360aec`), the reproduction as filed:

```
$ JOBHUNT_CONFIG="$PWD/config.example.yaml" JOBHUNT_PERSONAL_TOKENS="ZZPROBEZZ" \
    automation/publish/export_public.py --dest <scratch>
REPRO_EXIT=1
  identity tokens:      7 (config.yaml / $JOBHUNT_PERSONAL_TOKENS)
  identity source:      real config (<source checkout>/config.example.yaml)
FAIL: 116 violation(s) found.
  - CONTENT .github/workflows/ci.yml:222  (token: 'Jordan')  '# 3. Render + validate the worked example using the fake "Jordan Rivers"'
  - CONTENT AGENTS.md:12  (token: 'Jordan')  '(timeless tooling + the fake **"Jordan Rivers"** example) with a **private overlay** for real'
  - CONTENT CONTRIBUTING.md:5  (token: 'Jordan')  'fictional "Jordan Rivers" example candidate under `examples/` — never anyone's'
  - CONTENT README.md:53  (token: 'Jordan')  'the fictional "Jordan Rivers" example candidate. Requires Python 3.11+'
```

Seven identity tokens where one was supplied: the other six are the fictional
persona's name parts, email and handles, screened against the toolkit's own docs.

AFTER — the fix branch, identical command:

```
AFTER_REPRO_EXIT=0
  identity tokens:      1 (config.yaml / $JOBHUNT_PERSONAL_TOKENS)
  identity source:      fictional example config (<export>/config.example.yaml) — no identity resolved from config
OK: no public-repo leaks detected. Safe to publish.
Leak guard PASSED.
```

One token — the probe — and the report now names the example correctly.

## Tests: watched RED before GREEN

`ExampleConfigIdentityTests` (5) + the new `ExporterEndToEndTests` case, against
the UNFIXED guard:

```
$ python -m unittest ...ExampleConfigIdentityTests \
    ...ExporterEndToEndTests.test_export_survives_an_absolute_jobhunt_config_in_the_environment -v
EXIT=1
test_a_copy_of_the_example_in_another_tree_is_still_the_example ... FAIL
test_a_copy_under_a_different_filename_is_still_the_example ... FAIL
test_a_real_config_named_config_example_yaml_is_still_real ... ok
test_an_unreadable_config_is_not_silently_declared_the_example ... ok
test_the_report_does_not_call_a_copied_example_a_real_config ... FAIL
test_export_survives_an_absolute_jobhunt_config_in_the_environment ... FAIL
Ran 6 tests in 17.486s
FAILED (failures=4)
```

The two that pass in BOTH directions are the safety tests: a real config must stay
real. They are what stops this fix becoming a way to disarm the guard, so they are
expected green before and after.

Same command after the fix:

```
EXIT=0
Ran 6 tests in 22.248s
OK
```

## The publish suite, green under BOTH invocations

The failure this defect caused was environment-dependent, so both are recorded:

```
$ env -u JOBHUNT_CONFIG python -m unittest discover automation/publish/tests
SUITE_NO_ENV_EXIT=0
Ran 239 tests in 311.603s
OK (skipped=1)

$ JOBHUNT_CONFIG="$PWD/config.example.yaml" python -m unittest discover automation/publish/tests
SUITE_WITH_ENV_EXIT=0
Ran 239 tests in 399.039s
OK (skipped=1)
```

The second invocation is the one that used to fail: with `$JOBHUNT_CONFIG`
exported, `test_export_enumeration._shared_export`, `test_export_destination`
and `test_leak_guard.ExporterEndToEndTests` all went red on the same root cause.
