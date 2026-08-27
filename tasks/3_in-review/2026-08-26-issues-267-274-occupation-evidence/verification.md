# Verification — 2026-08-26-issues-267-274-occupation-evidence

## Frozen before/after title verdicts

The same 25 fictional profile/title inputs were evaluated before and after the implementation. The profile dictionaries already carried `titles.primary` in the baseline measurement; the old classifier ignored it.

```
baseline at 07ee313: match=24, review=1, no_match=0
after implementation: match=10, review=15, no_match=0
delta: match=-14, review=+14, no_match=0
target-family recall: 10/10 remained match
```

## Focused occupation and pipeline regressions

```
$ <repo-root>/.venv/bin/python -m unittest skills/job-search/scripts/tests/test_primary_occupation_evidence.py
.....
Ran 5 tests
OK
EXIT=0
```

```
$ <repo-root>/.venv/bin/python -m unittest skills/job-search/scripts/tests/test_primary_occupation_evidence.py skills/job-search/scripts/tests/test_filter_variants.py skills/job-search/scripts/tests/test_pipeline_corrections.py skills/job-search/scripts/tests/test_compact_output.py skills/job-search/scripts/tests/test_location_title.py
Ran 196 tests
OK
EXIT=0
```

## Public filter corpus

```
$ <repo-root>/.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 181 cases
EXIT=0
```

## Full job-search suite

```
$ <repo-root>/.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -p 'test_*.py'
Ran 824 tests
OK
EXIT=0
```

## Config-less impacted repository gates

The dedicated worktree had no `config.yaml` and no mounted private overlay. The impact selector included the policy and job-search lanes and folded all uncommitted implementation paths into its selection.

```
$ <repo-root>/.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
ALL GREEN
EXIT=0
```

## Eval gate

Eval gate: skipped — no `SKILL.md`, `LESSONS.md`, or `reference.md` changed. The behavior is pinned by deterministic unit and corpus tests; profile documentation changes are small additions outside the instruction-harness paths.
