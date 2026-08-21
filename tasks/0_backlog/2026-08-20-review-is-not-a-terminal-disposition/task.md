# A `review` decision is still a pass, not a lane of its own

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GH #286, the half `fix/sponsorship-negation-safety` (2026-08-20) did not
  close — its sponsorship half is fixed, its plumbing half is not
- **Claimed-by**:

## Goal

Give every posting exactly one terminal disposition — `match`, `review` or `reject` —
so an assessor returning `review` routes the row to the review lane and carries its
reason forward, instead of the row entering the main match list looking like any other.

## Context

GH #286 reproduces this in two domains. The 2026-08-20 pass fixed the SPONSORSHIP
symptom it names — the firmware posting whose complete JD bars the candidate now grades
`no_match` and is dropped, because the export-control sense gate no longer swallows a
citizenship bar, and `signal_present` is now true whenever any rule fired
(`automation/shared/job_metadata.py`). That closes one row. It does not close the
mechanism, which is in the pipeline rather than the classifier:

- `skills/job-search/scripts/scoring.py` — `title_ok`, `location_ok`, `visa_ok` each
  return a BOOL and reject only `decision == "no_match"`. A `review` is truthy, so it
  passes;
- `visa_ok` attaches `sponsorship_requires_review` only when the assessment reports a
  signal or the policy is `require_positive`. Every other assessor's `review` reason
  reaches the row only if that assessor happens to fill `review_reasons` itself;
- the YOE half of the issue is untouched: `assess_required_yoe` returns
  `decision: review` at medium confidence with a minimum above the profile's cap, and
  those rows enter main results with `review_reasons: []`.

So the same defect is one `assess_*` function away from reappearing whenever a new
high-stakes assessor is added. The fix GH #286 asks for is structural: ranking may order
rows within a lane but must never promote `review` to `match`.

Constraint: `review` must stay KEPT. This repo's whole sponsorship history
(`memory/known-issues/visa-sponsorship-negation-phrase-gap.md`) is about ambiguity
resolving toward keep-and-flag, and turning `review` into a drop would be the opposite
trade.

## Definition of done

- Every gate helper returns a tri-state disposition rather than a bool, and any assessor
  returning `review` puts the posting in the review lane with its rule id and evidence
  preserved.
- The three YOE reproductions in GH #286 (a `max_years_experience: 2` profile against
  postings stating 3+, 8+, and 3+ years) route to review with a non-empty
  `review_reasons`, under fictional JD wording.
- A regression proving a `review` row cannot appear in the main match list, written so it
  fails if a NEW assessor is added without lane handling.
- `python automation/gates/run_gates.py --impact-from origin/main` green.
