# A bare city with no job description still reports `workplace: onsite` (#237 residual)

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: cluster C3 (location gate), branch `fix/location-gate-precision`, 2026-08-20

## Goal

Decide whether a location field with NO job description behind it should keep reporting
`workplace: onsite`, and make the two readings agree.

## Context

Issue #237 says a city states geographic scope, not how the work is done, and that emitting a
definite workplace label invites a downstream handoff to treat an inference as a posting fact.
`automation/shared/location.py` now honours that in the case the issue reproduced — a JD was read
and never mentions a work mode, so `_workplace_assessment` returns `unknown`.

It does NOT honour it when there is no JD at all:

```python
# automation/shared/location.py, end of _workplace_assessment
if location and (description or "").strip():
    return "unknown", "medium", evidence, review
if location:
    return "onsite", "medium", evidence, review
```

The second branch exists because two tests in `automation/shared/tests/test_job_metadata.py` pin it:

- `WorkplaceTests.test_concrete_city_is_onsite` — `classify_workplace("Seattle, WA") == "onsite"`
- `WorkplaceTests.test_analyze_sets_workplace_from_location` —
  `analyze_job_metadata(description="", location="Austin, TX")["workplace"] == "onsite"`

Both call with `description=""`. That file is owned by the `job_metadata` work in flight, so this
was left alone rather than edited across an ownership boundary.

The inconsistency is real but harmless today: it affects the METADATA reading only
(`job_metadata.classify_workplace`, `build_postings`), never the search gate — `scoring.location_ok`
always passes the full description, so it always takes the first branch. Whoever owns
`job_metadata` should decide: either the no-JD reading becomes `unknown` too (and those two tests
move with it), or the split is documented as deliberate — "with no JD, a city field is an office
address" — in which case the comment already in `location.py` is the record.

## Definition of done

- A decision recorded (in `memory/decisions/` or in the two tests' docstrings) about what a bare
  city with no JD means.
- If the reading changes: `_workplace_assessment`'s second branch removed, the two
  `test_job_metadata.py` tests updated, and
  `.venv/bin/python -m unittest discover -s automation/shared/tests -t automation/shared/tests`
  exits 0.
