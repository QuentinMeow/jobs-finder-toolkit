# Verification — 2026-08-26-issues-267-274-occupation-evidence

## Frozen before/after title verdicts

The repaired matrix has 29 fictional profile/title inputs, adding Android and React Native target controls plus the issue-reported Mobile Mechanic and a Mobile Sales Representative negative. Three measurements expose both the original defect and the first implementation's configuration gap:

```
pre-feature equivalent at 07ee313 (primary ignored): match=28, review=1, no_match=0
first implementation at 4a1fdb2 with broad mobile primary terms: match=14, review=15, no_match=0
repaired occupation-phrase matrix: match=12, review=17, no_match=0
repair delta: match=-2, review=+2, no_match=0
target-family recall: 12/12 remained match
```

The two repaired verdicts are `Mobile Mechanic` and `Mobile Sales Representative`, both moved from main-list `match` to bounded `review`. No title became a hard drop.

## Focused occupation and pipeline regressions

```
$ <repo-root>/.venv/bin/python -m unittest skills/job-search/scripts/tests/test_primary_occupation_evidence.py
........
Ran 8 tests
OK
EXIT=0
```

```
$ <repo-root>/.venv/bin/python -m unittest skills/job-search/scripts/tests/test_primary_occupation_evidence.py skills/job-search/scripts/tests/test_filter_variants.py skills/job-search/scripts/tests/test_pipeline_corrections.py skills/job-search/scripts/tests/test_compact_output.py skills/job-search/scripts/tests/test_location_title.py
Ran 199 tests
OK
EXIT=0
```

## Public filter corpus

```
$ <repo-root>/.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 185 cases
EXIT=0
```

## Full job-search suite

```
$ <repo-root>/.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -p 'test_*.py'
Ran 827 tests
OK
EXIT=0
```

## Config-less impacted repository gates

The dedicated worktree had no `config.yaml` and no mounted private overlay. The impact selector included the policy and job-search lanes and folded all uncommitted implementation paths into its selection.

```
$ <repo-root>/.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
12 of 37 gates selected; policy and job-search lanes
ALL GREEN (12 of 37 gates ran)
EXIT=0
```

## Eval gate

Eval gate: skipped — no `SKILL.md`, `LESSONS.md`, or `reference.md` changed. The behavior is pinned by deterministic unit and corpus tests; profile documentation changes are small additions outside the instruction-harness paths.
