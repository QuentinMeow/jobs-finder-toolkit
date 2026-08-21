# Verification — 2026-08-10-conditional-sponsorship-offers-grade-as-unhedged

Run on `fix/sponsorship-negation-safety` at `1dbc9d9`, macOS, `.venv/bin/python`.

## The three filed sentences land review/unknown/low, and ordinary "if" prose does not

```
$ .venv/bin/python -c "
import sys; sys.path.insert(0, 'skills/job-search/scripts/_vendor')
from job_metadata import assess_sponsorship as a
for t in (...): print(a(t)['decision'], a(t)['verdict'], a(t)['confidence'])"
review/unknown/low  If approved by counsel, the company will sponsor H-1B candidates.
review/unknown/low  Subject to internal approval, we sponsor work visas for this role.
review/unknown/low  Provided that a business need is established, we will sponsor visas.
match/likely/high   If you are interested in this role, we offer visa sponsorship.
```

The last line is the tripwire the task asked for: a fronted subordinator that
governs no approval or gating resource leaves the offer alone.

## Through the live gate under require_positive

`skills/job-search/scripts/tests/test_visa.py::
VisaPolicyBindingTests::test_a_conditional_offer_is_not_surfaced_by_require_positive`
asserts the posting is kept, `visa_label != "yes"`, and carries
`sponsorship_requires_review`.

## The verdict matrix

```
$ .venv/bin/python skills/job-search/scripts/sponsorship_matrix.py --check
sponsorship verdict matrix clean: 101 rows agree with their asserted reading
(exit 0)

$ .venv/bin/python skills/job-search/scripts/sponsorship_matrix.py --diff
41 moved, 0 of them unpredicted, 0 predicted moves did not happen
```

The three `conditional-offer` rows are flipped to `expected-change` and carry
`expect` blocks. The 41 moves are measured against the frozen `baseline_ref`
399a6ec, so they include every move landed by the passes between that commit and
this branch, not only this one's.

The three tripwire rows the task named
(`sponsorship-offer-then-scope-limit-is-an-offer`,
`control-plain-offer-stays-an-offer`,
`not-fixed-immigration-support-plus-every-applicant`) all still agree with their
asserted reading; `control-plain-offer-stays-an-offer` carries an evidence-only
`expect` block from the same branch, with its verdict untouched at
`match/likely/high`.

## The corpus

`sponsorship-conditional-offer-is-not-a-settled-offer` and
`sponsorship-ordinary-fronted-clause-leaves-the-offer-alone` were added to
`skills/job-search/filter_variants/corpus.yaml`; the filter-variants gate is
green.

## Full gate run

```
$ python automation/gates/run_gates.py --impact-from origin/main --jobs 8
ALL GREEN (30 gates, 1 skipped: example-render)
(exit 0)
```

`example-render` skips because LibreOffice is absent on this machine; CI runs it.

## Definition-of-done item NOT satisfied as written

"The measured count of postings whose verdict moves toward `likely` is ZERO"
cannot be true of this branch, and the reason is that the conditional fix did not
ship alone. The same pass repaired a higher-severity defect in the same function
and closed GH #233/#238/#265/#286-visa, which deliberately moves several rows
toward `likely` (an explicit transfer welcome, `open to sponsoring
employment-based visas`). Measured for the conditional change specifically: zero
rows move toward `likely`; all three move away from it.
