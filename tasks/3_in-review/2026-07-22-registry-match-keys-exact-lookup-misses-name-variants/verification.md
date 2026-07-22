# Verification — 2026-07-22-registry-match-keys-exact-lookup-misses-name-variants

Commands actually run on branch `fix/job-search-identity-and-yoe-20260722`
(2026-07-22, macOS, repo venv Python 3.13). Output is trimmed to result lines.

## Focused identity regressions

```console
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -p 'test_registry.py' -v
Ran 18 tests in 0.001s
OK

$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -p 'test_skip_identity.py' -v
Ran 10 tests in 0.006s
OK
```

## Complete affected suites

```console
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests
Ran 230 tests in 13.208s
OK

$ .venv/bin/python -m unittest discover -s automation/shared/tests
Ran 288 tests in 5.682s
OK
```

## Filter corpus and vendored copies

```console
$ .venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 27 cases

$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## Python compilation and patch hygiene

```console
$ .venv/bin/python -m compileall -q automation/shared/job_metadata.py \
    skills/job-search/scripts/registry.py \
    skills/job-search/scripts/search_jobs.py \
    skills/job-search/scripts/tests
(exit 0)

$ git diff --check
(exit 0)
```
