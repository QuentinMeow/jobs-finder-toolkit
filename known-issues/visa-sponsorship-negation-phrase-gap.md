# `classify_sponsorship()`'s negative-phrase list misses some real denial wordings

- **Status**: open
- **Severity**: medium (wasted cost or manual workaround — a false non-denial can
  let a sponsorship-denying posting reach the candidate as `unclear` rather than
  a confirmed `no`)
- **Area**: job-search
- **Source**: GH issue #15 (comment thread); reconfirmed in
  `evals/results/stage2-canary-gate-19c3ff8-20260720.md` (`js-visa-require-positive`
  row) and `evals/results/stage3-canary-gate-446a954-20260720.md` (`js-visa-require-positive`
  row)

## Symptom

`classify_sponsorship()` (in `scripts/shared/job_metadata.py`) scans a job
description for an explicit sponsorship denial (`_SPONSOR_NEGATIVE`) or offer
(`_SPONSOR_POSITIVE`) and returns `unlikely` / `likely` / `unknown` accordingly,
with an explicit denial always winning. During a live gate run, two real JD
denial phrasings were found that the current `_SPONSOR_NEGATIVE` phrase list does
**not** catch, so those postings classify as `unknown` instead of the correct
`unlikely`:

- "Immigration Sponsorship support will NOT be available for this position"
- "We are unable to provide visa sponsorship."

Note: an earlier, related bug — `--visa-policy require_positive` being a silent
no-op when the profile ships `needs_sponsorship: false` — was also reported in GH
issue #15 and has since been **fixed** (`apply_visa_policy()` in
`.agents/skills/job-search/scripts/search_jobs.py` now sets
`visa["needs_sponsorship"] = True` whenever `--visa-policy` is passed). This file
covers only the remaining, unfixed gap: the negative-phrase list itself.

## Reproduction

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts/shared')
from job_metadata import classify_sponsorship
print(classify_sponsorship('Immigration Sponsorship support will NOT be available for this position.'))
print(classify_sponsorship('We are unable to provide visa sponsorship.'))
"
# both print 'unknown' instead of the correct 'unlikely'
```

## Impact

Under the default `exclude_negative` visa policy, `unknown`-labeled postings are
kept (only a confirmed `no` is excluded), so a posting that explicitly denies
sponsorship in one of these phrasings passes through to the candidate as if
sponsorship status were merely unstated. This is advisory-only heuristic output
(the skill always tells the agent to verify with the employer), but it weakens the
signal the agent relies on for the visa gate.

## Root cause

`_SPONSOR_NEGATIVE` in `scripts/shared/job_metadata.py` is a fixed tuple of
substring phrases. It has near-miss entries — `"unable to provide sponsorship"`
(no "visa") and `"not able to provide visa sponsorship"` (no "unable") — but
neither matches `"unable to provide visa sponsorship"` verbatim, and it has no
entry that matches a `"<subject> will NOT be available"` denial construction at
all.

## Suggested fix

Extend `_SPONSOR_NEGATIVE` in `scripts/shared/job_metadata.py` to cover both
observed phrasings, e.g. add `"unable to provide visa sponsorship"` (in addition
to the existing `"unable to provide sponsorship"`), and either add a literal
`"will not be available"` / `"will not be provided"` entry or generalize the
negation scan to a regex that tolerates an intervening subject between "will
NOT" and "available"/"sponsor". Add both denial sentences as regression cases in
`.agents/skills/job-search/scripts/tests/` (or wherever `classify_sponsorship`
already has coverage) so future phrase-list edits don't regress them.
