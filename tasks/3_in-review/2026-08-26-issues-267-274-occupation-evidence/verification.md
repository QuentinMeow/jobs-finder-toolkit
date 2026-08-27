# Verification — 2026-08-26-issues-267-274-occupation-evidence

## Frozen before/after title verdicts

The repaired matrix has 31 fictional profile/title inputs, adding paired iOS-only
Android/React Native negative-policy controls to the broad-mobile target controls and the
issue-reported Mobile Mechanic and Mobile Sales Representative negatives. Three measurements
expose both the original defect and the first implementation's configuration gap:

```
pre-feature equivalent at 07ee313 (primary ignored): match=28, review=1, no_match=2
first implementation at 4a1fdb2 with broad mobile primary terms: match=14, review=15, no_match=2
repaired occupation-phrase matrix: match=12, review=17, no_match=2
repair delta: match=-2, review=+2, no_match=0
target-family recall: 12/12 remained match
iOS-only negative-policy controls: 2/2 remained no_match
```

The two repaired verdicts are `Mobile Mechanic` and `Mobile Sales Representative`, both moved from main-list `match` to bounded `review`. No title became a hard drop.
The matrix's only two hard drops are candidate-authored exclusions: Android and React Native
under the iOS-only profile. The same two titles remain main-list matches under the broad mobile
profile.

## Focused occupation and pipeline regressions

```
$ <repo-root>/.venv/bin/python -m unittest skills/job-search/scripts/tests/test_primary_occupation_evidence.py
.........
Ran 9 tests
OK
EXIT=0
```

```
$ <repo-root>/.venv/bin/python -m unittest skills/job-search/scripts/tests/test_primary_occupation_evidence.py skills/job-search/scripts/tests/test_filter_variants.py skills/job-search/scripts/tests/test_pipeline_corrections.py skills/job-search/scripts/tests/test_compact_output.py skills/job-search/scripts/tests/test_location_title.py
Ran 200 tests
OK
EXIT=0
```

## Public filter corpus

```
$ <repo-root>/.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 187 cases
EXIT=0
```

## Full job-search suite

```
$ <repo-root>/.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -p 'test_*.py'
Ran 828 tests
OK
EXIT=0
```

## Publication dependency

Read-only GitHub verification on 2026-08-27 found PR #371 open against `main`, with head
`codex/issue-234-manager-product-corpus` at
`67a0375f012e7ef579482de5b0272d4ec13bb0b2`. This branch was built on that exact commit.
Publish it as a stacked PR with the #371 head branch as its base while #371 is open. Rebase
onto `main` only after #371 merges.

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
