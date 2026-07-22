# metadata_editor mis-plans a field insertion after a block-style mapping in a non-final jobs entry

- **Status**: fixed (commit 44d26fa, same branch — _reliable_end_index clamps all plan sites; 3 regression tests) — delete after one PR cycle
- **Severity**: medium (wasted cost or manual workaround)
- **Area**: tracker
- **Source**: application-tracker canary run at-update-one-role-multi-app,
  2026-07-22, on `email/stage-2-progress-calendar` head `8118eea` (synthetic
  Acme multi-role fixture)

## Symptom

`status.py --update-job <slug> "<role>" <status>` fails with
`planned output changed values outside the requested field updates` on a
schema-valid multi-role `meta.yaml` whose **non-final** `jobs:` entry ends
with a **block-style** mapping (e.g. a block `salary_range:`). The
fail-closed guard correctly refuses to write, so no file corruption occurs
— but the requested transition cannot be applied.

## Reproduction

Two-entry `jobs:` list, both entries using block-style
`job_level`/`required_yoe`/`salary_range` mappings (the shipped single-role
example's style), no `status_date` yet on entry 1. Run
`status.py --update-job <slug> "<first role>" in_progress`. The editor
plans the `status_date` insertion for entry 1 but the line lands inside
entry 2, tripping the semantic-verification guard. Reformatting the fact
fields to flow style (`{min: ..., max: ...}` — the SKILL.md multi-role
example's style) makes the same command succeed.

## Impact

Any multi-role application written with block-style fact mappings cannot
take per-job transitions until hand-reformatted. Validation (`--check-metadata`)
accepts both styles, so the fleet can legitimately contain affected files.

## Root cause

Best hypothesis (from the canary diagnosis, marked as such): PyYAML's node
end-mark for a block mapping that terminates a non-final sequence item
extends past the item boundary, so `metadata_editor.plan_field_updates`
computes the insertion point for a new sibling field (e.g. `status_date`)
inside the NEXT `jobs:` entry.

## Suggested fix

In `automation/shared/metadata_editor.py`, clamp a jobs-entry field
insertion point to the entry's own extent — e.g. derive the entry's end
from the next sequence item's start line (or the sequence end) instead of
the last field node's end mark. Add a regression test: two-entry jobs list,
block-style facts, insert `status_date` into entry 1; assert entry 2 is
byte-identical and validation passes. Regenerate the vendored copy after
the fix.
