# `classify_sponsorship()` still misses denials that match no phrase at all

- **Status**: open (narrowed 2026-07-31; **severity corrected upward 2026-08-01** — the
  2026-07-31 correction pass wrote a safety claim into this file that the code did not
  have, see the note below)
- **Severity**: **high** — a denial can still reach the candidate as an explicit
  **offer**. `--visa-policy require_positive` is NOT safe: one denial shape below still
  returns `verdict: likely`, `confidence: high`, `decision: match`, `classify_visa: yes`,
  so a posting that refuses sponsorship in writing is shortlisted, unflagged, for the one
  candidate who cannot take it. The `unclear` fall-through and the false-denial shape are
  the lesser, still-open remainder.
- **Area**: job-search
- **Source**: GH issue #15 (comment thread); reconfirmed in
  `evals/results/stage2-canary-gate-19c3ff8-20260720.md` and
  `evals/results/stage3-canary-gate-446a954-20260720.md` (`js-visa-require-positive`
  rows); escalated by the live stage-1 example-profile run of 2026-07-31 (11,638 raw
  postings); narrowed by task
  `2026-07-31-sponsorship-negation-defeats-require-positive`; **severity restored
  2026-08-01** after an independent re-run of the reproduction below

> **Correction, 2026-08-01.** Between 2026-07-31 and this entry, this file said the
> severity was *"medium (was high — the classifier no longer reports a denial as an
> explicit offer, so `--visa-policy require_positive` is safe again …)"* and that *"An
> unrecognized denial classifies `unknown`"*. Both were false when written, and the
> reproduction below shows it in one command. The edit that introduced them was made by
> the pass whose stated purpose was removing false statements from tracked records, so
> nothing downstream re-checked them. **A severity line is a safety claim; it is
> re-measured on the tree that ships it, never carried forward from a prior read.**

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
  scope and is not applied. **This does not fail safe.** When the phrase left
  unguarded is an OFFER phrase, the sentence is scored as an explicit offer, not as
  silence — so a denial with a parenthetical in the middle of it
  ("We are unable, given current headcount constraints and the timeline for this
  particular opening, to offer visa sponsorship.") returns `likely` / `high` /
  `match` and `classify_visa` → `yes`. `_SPONSOR_NEGATION_MAX_GAP_TOKENS` is 8; that
  sentence puts 17 tokens between `unable` and `offer visa sponsorship`.

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
from job_metadata import assess_sponsorship as a
for t in ('We do not offer relocation or visa sponsorship.',
          'We do not sponsor community events.',
          'We are unable, given current headcount constraints and the timeline '
          'for this particular opening, to offer visa sponsorship.'):
    print(a(t)['verdict'], a(t)['confidence'], a(t)['decision'])
"
# prints:
#   unknown  unknown  review     <- should be 'unlikely' (denial matches no phrase)
#   unlikely high     no_match   <- should be 'unknown'  (non-immigration "sponsor")
#   likely   high     match      <- should be 'unlikely'; THIS is the high-severity one
```

Re-run 2026-07-31 on the stack tip `40871e6`: the first two print `unknown` then
`unlikely`, exactly as stated. Re-run 2026-08-01 on the branch that carries this
correction: all three reproduce, including the third — which the previous version of this
file said could no longer happen.

The one figure in this file that is **not** reproducible is "roughly 28 of 430 `likely`
rows on the 2026-07-31 run" (and the 11,638 raw postings behind it). Those come from a
live keyless board sweep whose postings have since moved on; they are recorded as what
that run reported, not as a claim about any tree, and nothing here depends on them.

## Impact

Three shapes, and they do not cost the same.

1. **A denial reported as an offer (high).** When a denial's sentence carries an offer
   substring that the negation scope cannot reach, the posting classifies `likely` at
   `high` confidence with `decision: match`, so `--visa-policy require_positive` — the
   policy chosen precisely by someone who needs sponsorship — returns it with **no**
   `sponsorship_requires_review` flag. The user is pointed at an employer that said no
   in writing. This is the reason the entry's severity is high.
2. **A denial reported as silence (medium).** An unrecognized denial classifies
   `unknown`, and the default `exclude_negative` policy keeps `unknown`, so the posting
   reaches the candidate as if sponsorship were merely unstated — advisory-only output
   (the skill always tells the agent to verify with the employer), but a weaker signal
   than the JD actually gave.
3. **A non-denial reported as a denial (medium).** The posting is dropped silently
   under both policies; it needs an unrelated "sponsor" use in the JD, which is uncommon.

## Root cause

`_SPONSOR_NEGATIVE` / `_SPONSOR_POSITIVE` are fixed substring tuples. Detection is still
lexical: if no phrase from either tuple matches, there is nothing for the negation scope
to act on. And `_SPONSOR_NEGATIVE` hits are accepted without the `_SPONSOR_CONTEXT_RE`
gate that non-strong `_SPONSOR_POSITIVE` hits must pass.

## Fixed on 2026-07-31 (kept as history)

Three wrong-polarity symptoms this file used to describe are resolved **for the wordings
named below**. Item 2 is the one that was over-claimed: the negation scope closed the
shapes it can reach, not the class. Pinned by tests in
`automation/shared/tests/test_job_metadata.py`,
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
   offer phrase inside a negated clause as a denial of that offer — **but only when the
   cue is within 8 tokens of the phrase.** Outside that window the class is untouched;
   see Symptom, and the third line of the reproduction. Claiming otherwise is what made
   this file's severity wrong.
3. **Export-control boilerplate read as an immigration denial.** "…must be eligible to
   obtain the required authorizations without sponsorship for an export license"
   returned `unlikely` / high confidence, and the default policy drops denials, so
   export-controlled postings disappeared silently. A sentence that is export-control
   language with no immigration word in it is no longer sponsorship evidence.

## Fixed on 2026-08-01 (kept as history)

**A quantified denial promoted to a confident offer.** The 2026-07-31 scope-limit rule
("not for *every* role" negates a universal, so it is a limit on an offer rather than a
refusal) accepted the bare word `all` as well. `all` also has a collective reading, so
"We are unable to sponsor visas for **all** new hires" — a flat denial that names the
population it covers — was read as a scope limit, which **deleted** the denial. Deleting
it dissolved the `denial + positive -> review` conflict, so the same JD's unrelated
positive phrase was left unopposed and the posting graded `likely` / `high` / `match`
with `classify_visa: yes`. The rule is now restricted to DISTRIBUTIVE quantifiers
(`every` / `each`, plus an explicit `guarantee` hedge). Pinned by
`QuantifiedDenialTests`, `test_require_positive_never_presents_a_quantified_denial_as_an_offer`,
and three `sponsorship-quantified-denial-*` / `sponsorship-do-not-sponsor-all-*` corpus
cases.

Worth recording as method, not just as a bug: the invariant the scope-limit rule was
written under — *a scope limit may only REMOVE a denial, never create an offer* — holds
of the evidence lists by construction and was never enforced at the VERDICT level, where
removing a denial is itself a two-step promotion (`review`/`unknown`/low →
`match`/`likely`/high). The unenforced half is where the defect landed.

## Suggested fix

Three independent pieces; any can ship alone.

0. **The long-distance negation (the high-severity remainder).**
   `_SPONSOR_NEGATION_MAX_GAP_TOKENS` is 8 tokens, and beyond it an offer phrase inside a
   denial is scored as an offer rather than ignored. Two candidate repairs, and the choice
   is an owner call because they trade recall against safety differently: (a) raise the
   budget but stop counting tokens inside a comma-delimited parenthetical, so
   "unable, *given …*, to offer visa sponsorship" measures 2 tokens rather than 17; or
   (b) leave the budget alone and make an unreachable cue *demote* the offer to `unknown`
   instead of leaving it `likely`, i.e. fail toward "kept and flagged" the way every other
   ambiguity in this module does. Measure both against the corpus before choosing.
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
