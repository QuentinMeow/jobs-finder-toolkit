# `classify_sponsorship()` still misses denials that match no phrase at all

- **Status**: open (narrowed 2026-07-31 — the wrong-polarity symptoms below are fixed)
- **Severity**: medium (was high — the classifier no longer reports a denial as an
  explicit offer, so `--visa-policy require_positive` is safe again; what is left is
  denials falling through to `unclear`, plus one false-denial shape)
- **Area**: job-search
- **Source**: GH issue #15 (comment thread); reconfirmed in
  `evals/results/stage2-canary-gate-19c3ff8-20260720.md` and
  `evals/results/stage3-canary-gate-446a954-20260720.md` (`js-visa-require-positive`
  rows); escalated by the live stage-1 example-profile run of 2026-07-31 (11,638 raw
  postings); narrowed by task
  `2026-07-31-sponsorship-negation-defeats-require-positive`

## Symptom

`classify_sponsorship()` / `assess_sponsorship()` (in `automation/shared/job_metadata.py`)
scan a job description for an explicit sponsorship denial or offer and return
`unlikely` / `likely` / `unknown`. Polarity is now decided structurally, but the
*evidence detector* is still a fixed tuple of substring phrases, so a denial that
matches **neither** list is invisible and the posting classifies `unknown`:

- "We do not offer relocation or visa sponsorship." — the denial phrases need
  "offer sponsorship" contiguous, and the offer phrases need "visa sponsorship
  available" / "offer visa sponsorship"; neither matches, so nothing fires and the
  negation scope has nothing to act on.
- A negation more than ~8 words from the phrase it governs is outside the negation
  scope and is not applied.

A second, opposite shape is still live: denial phrases carry **no**
immigration-context gate (offer phrases do), so a non-immigration use of "sponsor"
can read as a visa denial — "We do not sponsor community events" matches
`do not sponsor` and returns `unlikely`, which DROPS the posting under both visa
policies. The export-control sense of the word is now guarded specifically (below);
the general case is not.

## Reproduction

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'automation/shared')
from job_metadata import classify_sponsorship
print(classify_sponsorship('We do not offer relocation or visa sponsorship.'))
print(classify_sponsorship('We do not sponsor community events.'))
"
# prints 'unknown' (should be 'unlikely') and 'unlikely' (should be 'unknown')
```

## Impact

An unrecognized denial classifies `unknown`, and the default `exclude_negative` policy
keeps `unknown`, so the posting reaches the candidate as if sponsorship were merely
unstated — advisory-only output (the skill always tells the agent to verify with the
employer), but a weaker signal than the JD actually gave. The false-denial shape is
worse in kind, because the posting is dropped silently under both policies; it needs an
unrelated "sponsor" use in the JD, which is uncommon.

## Root cause

`_SPONSOR_NEGATIVE` / `_SPONSOR_POSITIVE` are fixed substring tuples. Detection is still
lexical: if no phrase from either tuple matches, there is nothing for the negation scope
to act on. And `_SPONSOR_NEGATIVE` hits are accepted without the `_SPONSOR_CONTEXT_RE`
gate that non-strong `_SPONSOR_POSITIVE` hits must pass.

## Fixed on 2026-07-31 (kept as history)

All three wrong-polarity symptoms this file used to describe are resolved, pinned by
tests in `automation/shared/tests/test_job_metadata.py`,
`skills/job-search/scripts/tests/test_visa.py`, and
`skills/job-search/filter_variants/corpus.yaml`:

1. **The original phrase-list misses.** "Immigration Sponsorship support will NOT be
   available for this position" and "We are unable to provide visa sponsorship"
   classified `unknown`; both now classify `unlikely`.
2. **The escalation — a denial reported as an explicit offer.** A denial containing an
   offer substring ("does not currently offer visa sponsorship", "no H1-B visa
   sponsorship available") returned `decision: match`, `confidence: high`, so
   `--visa-policy require_positive` surfaced postings that refuse sponsorship — roughly
   28 of 430 `likely` rows on the 2026-07-31 run. A bounded negation scope now reads an
   offer phrase inside a negated clause as a denial of that offer.
3. **Export-control boilerplate read as an immigration denial.** "…must be eligible to
   obtain the required authorizations without sponsorship for an export license"
   returned `unlikely` / high confidence, and the default policy drops denials, so
   export-controlled postings disappeared silently. A sentence that is export-control
   language with no immigration word in it is no longer sponsorship evidence.

## Suggested fix

Two independent pieces; either can ship alone.

1. **Detection.** Give the denial side the structural treatment the offer side now has:
   when a negation cue governs an *offer verb* ("not offer", "not provide", "cannot
   extend"), accept a bare sponsorship head ("visa sponsorship", "sponsorship") within a
   tight window (≈5 tokens) as the denied object. Keep the window tight — a generic
   "cue … sponsorship head" rule misfires on EEO copy such as "we do not discriminate
   against candidates who need visa sponsorship", which is not a denial.
2. **The false-denial shape.** Gate generic denial phrases ("do not sponsor",
   "no sponsorship") on immigration context the way non-strong offer phrases are gated,
   with a `_SPONSOR_STRONG_NEGATIVE` set (phrases naming visa / H-1B / immigration /
   green card explicitly) exempt from the gate. Measure first: "This role does not offer
   sponsorship." carries no immigration word either, so a naive symmetric gate would turn
   a real denial into `unknown` — that regression is pinned by
   `sponsorship-explicit-denial` in the corpus.

Add fictional regressions to `skills/job-search/filter_variants/corpus.yaml`, run
`validate_filter_variants.py`, and re-vendor with
`automation/vendoring/sync_vendored.py`.
