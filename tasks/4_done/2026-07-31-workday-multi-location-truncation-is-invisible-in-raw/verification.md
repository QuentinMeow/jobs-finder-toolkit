# Verification — 2026-07-31-workday-multi-location-truncation-is-invisible-in-raw

Real output from branch `fix/25-recall-audit-cli`. The Workday payload is the
**recorded** fixture the test module already carries (`_wd_posting()`, captured
through the real `CaptureSession` into a throwaway store) — no live fetch, no
network.

## What was already fixed before this session

`automation/search-recall-audit/field_fidelity.py:166`:

```
_DERIVED_NATIVE_ID = {"workday": parsers._workday_req}
```

consumed by `_job_native_id` immediately below it. The id-less source already
resolved against its own raw payload, so Workday rows already had
`raw_resolved: True`, a `raw_location_view`, a gate decision and a place in
`sample`. `WorkdayRawResolutionTests` pins it and passed unmodified through this
change. **Nothing in that half was redone.**

## Before the fix — the tests fail

```
$ .venv/bin/python -m unittest discover automation/search-recall-audit/tests \
      -k TruncatedLocation -k FlagShape
EXIT=1
FAIL: test_it_fires_on_the_workday_shape_whatever_the_metro (location='Fairview, ST and 3 more')
AssertionError: 'truncated_location_list' not found in []
FAIL: test_it_fires_on_the_workday_shape_whatever_the_metro (location='Austin, TX and 12 more')
AssertionError: 'truncated_location_list' not found in []
FAIL: test_it_fires_on_the_workday_shape_whatever_the_metro (location='Springfield, ST AND 1 MORE')
AssertionError: 'truncated_location_list' not found in []
FAIL: test_it_leaves_the_four_existing_flags_alone
AssertionError: Lists differ: ['weird_separator'] != ['truncated_location_list', 'weird_separator']
FAIL: test_the_and_n_more_tail_is_flagged_not_read_as_a_faithful_copy
AssertionError: Lists differ: [] != ['truncated_location_list']
FAIL: test_the_flagged_case_reaches_a_judge
AssertionError: 'truncated_location_list' not found in '# Field-fidelity case:
workday-JR1980360 (source=workday) ... - dropped_raw_tokens (heuristic): []
- flags: []'
Ran 6 tests in 1.083s
FAILED (failures=6)
```

That last block is the defect in the tool's own words: the case file a judge would
have read said `dropped_raw_tokens: []` and `flags: []` for a posting whose
location string is `'Fairview, ST and 3 more'`.

The two negative controls in that run — a fully spelled-out location list, and a
Workday posting with a complete `locationsText` — passed before AND after. They
guard against a detector that fires on everything, so they are expected to pass in
both states.

## After the fix

```
$ .venv/bin/python -m unittest discover automation/search-recall-audit/tests
EXIT=0
Ran 40 tests in 3.715s
OK
```

The end-to-end assertion pair is the finding: for a Workday posting whose
`locationsText` is `"Fairview, ST and 3 more"`, built through the real builder into
a throwaway store and read back out of `corpus.jsonl`,

```
row["generated_location"] == "Fairview, ST and 3 more"
row["dropped_raw_tokens"] == []            # nothing lost BETWEEN raw and generated
row["flags"] == ["truncated_location_list"]  # and still not a faithful copy
```

Definition of done, item by item:

- [x] A Workday posting whose `locationsText` ends in `and N more` is flagged (or
      its hidden metros resolved) rather than reported as a faithful copy. —
      flagged; the hidden metros are not resolved, which is the task's own second
      option (deterministic flag, no per-posting detail fetch).
- [x] A test in `automation/search-recall-audit/tests/test_field_fidelity.py`
      pins the new behaviour on a recorded Workday payload (no live fetch). —
      `TruncatedLocationListTests` (store end-to-end) and `FlagShapeTests`
      (the regex, with negative controls).
- [x] The skill's field-fidelity section names the new flag if one is added. —
      `skills/search-recall-audit/SKILL.md`; the section named no flags at all, so
      the added line names all five.

## Gates

```
$ .venv/bin/python automation/reconcile/reconcile.py --check        EXIT=0
$ .venv/bin/python automation/publish/check_public.py --staged --allow-unarmed
                                                                    EXIT=0
$ .venv/bin/python automation/gardener/verify_links.py --require-roots --no-overlay
                                                                    EXIT=0
$ .venv/bin/python automation/metrics/instruction_budget.py --strict EXIT=0
$ .venv/bin/python automation/vendoring/sync_vendored.py --check     EXIT=0
$ .venv/bin/python automation/publish/review_gate.py --verify-all    EXIT=0
```
