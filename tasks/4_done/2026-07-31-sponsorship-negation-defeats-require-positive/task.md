# A negated sponsorship sentence classifies as an explicit offer, so `--visa-policy require_positive` surfaces denials

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: live stage-1 example-profile run, 2026-07-31 (11,638 raw postings);
  extends `memory/known-issues/visa-sponsorship-negation-phrase-gap.md`; two
  further `job_metadata.py` defects folded in mid-task (see "Scope added
  2026-07-31")
- **Claimed-by**: agent session 2026-07-31 (branch `wip/22-sponsorship-negation`)

## Goal

Make the sponsorship classifier refuse to label a negated clause as an explicit
offer, so `--visa-policy require_positive` returns only postings that actually
offer sponsorship.

## Context

`classify_sponsorship_evidence()` / `assess_sponsorship()` in
`automation/shared/job_metadata.py` (vendored into
`skills/job-search/scripts/_vendor/`) scan for denial phrases first and offer
phrases second, denial winning. The denial list is a fixed substring tuple, so a
denial it does not literally contain falls through — and if the same sentence
contains an offer substring, the offer rule fires with
`decision: match, confidence: high`.

Observed live (companies omitted, public tree):

```
"... does not currently offer visa sponsorship for this role"      -> likely
"... will not consider applicants for employment immigration
 sponsorship or support for this position"                          -> likely
"Must be eligible to work in the United States; no H1-B visa
 sponsorship available"                                             -> likely
"We are not able to offer visa sponsorship for this position
 at this time"                                                      -> likely
```

Impact is worst exactly where it matters: a candidate who needs sponsorship runs
`--visa-policy require_positive`, and the strict filter hands back postings that
explicitly refuse to sponsor. On the 2026-07-31 run, ~28 of 430 `likely`
postings (~7%) were denial-only text. `LESSONS.md` § "Visa heuristic
false-positives" already warns an agent to verify a `yes` by hand; this task is
about the classifier, not the warning.

Constraints:
- Edit the canonical `automation/shared/job_metadata.py`, then re-vendor with
  `automation/vendoring/sync_vendored.py` — never edit a `_vendor/` copy.
- Sponsorship is a content gate: add fictional regressions to
  `skills/job-search/filter_variants/corpus.yaml` (never a real posting) so
  `validate_filter_variants.py` guards the shapes.
- Generic "must be authorized to work in the US" boilerplate must keep yielding
  `unknown`, never `no` (LESSONS § Visa filtering) — a negation guard must not
  regress that.

## Scope added 2026-07-31

Two more defects in the same function/file were folded into this task rather than
split across branches that would collide in `job_metadata.py`. Both share the root
shape of the first: a substring standing in for a meaning, producing a confident
wrong answer that silently removes an opportunity.

1. **Third-party years become the candidate's required YOE**
   (`_GENERAL_EXPERIENCE_RE` + `_yoe_candidate_confidence`). "Our founders bring 25
   years of engineering experience" was read as a 25-year minimum, beating the real
   "3+ years" bullet below it. `scoring.experience_ok` then hard-dropped the posting
   under `max_years_experience`, and `analyze_job_metadata` wrote
   `required_yoe: {min: 25, confidence: high}` plus a `senior_staff` level into
   owner-visible tracking metadata.
2. **Export-control boilerplate read as a sponsorship denial.** "…must be eligible
   to obtain the required authorizations without sponsorship for an export license"
   is ITAR/EAR licensing language, not immigration. It scored `unlikely` / high, and
   the DEFAULT `exclude_negative` policy drops denials — so export-controlled
   postings disappeared with no trace at all.

## Definition of done

- [x] A bounded negation look-back (or equivalent) prevents a positive phrase
      from firing inside a negated clause; all four sentences above classify
      `unlikely`.
- [x] `.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --profile example`
      passes with new fictional sponsorship regressions in the corpus.
- [x] Unit coverage in `skills/job-search/scripts/tests/` for the four shapes plus
      a true offer and the "must be authorized to work in the US" boilerplate.
- [x] `automation/vendoring/sync_vendored.py` run; drift check clean.
- [x] `memory/known-issues/visa-sponsorship-negation-phrase-gap.md` closed or
      narrowed to whatever remains — narrowed to detection (denials matching no
      phrase at all) plus the un-gated generic denial phrase; severity high -> medium.
- [x] Third-party YOE attribution: a company/team/customer subject with no applicant
      vocabulary after it yields "no requirement stated", not a number; the real
      requirement in the same JD still wins.
- [x] Export-control sentences with no immigration word are not sponsorship evidence;
      an immigration denial sitting next to one still decides.
- [x] Every new corpus case and unit test that asserts changed behaviour fails
      against the pre-fix module (`verification.md`).
