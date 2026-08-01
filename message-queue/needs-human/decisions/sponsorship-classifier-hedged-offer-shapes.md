# Should the sponsorship classifier resolve the two hedged phrasing shapes it currently gets backwards?

- **Status**: resolved-by-implementation (2026-07-31) — nothing is pending on you;
  read the Resolution below and reopen only if you disagree with the shape chosen.
- **Filed**: 2026-07-31
- **Source**: [job-search skill — visa heuristic](../../../skills/job-search/LESSONS.md)
- **Blocking**: nothing.
- **Default path**: superseded — the classifier now resolves both shapes (see
  Resolution). No manual second pass is required.

## Background

A live stage-1 run (11,683 postings, 105 boards + 4 aggregators) was filtered
with `--visa-policy require_positive` for a user who needs H-1B sponsorship.
The filter returned **zero** rows. Reading the underlying JDs shows the zero is
an artifact of two phrasing shapes the classifier resolved in opposite
directions from what `LESSONS.md` prescribes.

**Shape A — affirmative offer followed by a scope hedge.** A JD states an
unambiguous offer ("we do sponsor visas"), then immediately qualifies it
("however, we aren't able to ... for every role and every candidate"), then
reaffirms ("if we make you an offer, we will make every reasonable effort ...
and we retain an immigration lawyer to help with this"). The hedge sentence
puts a negation near the offer phrase, so the bounded-negation scope drove the
whole assessment to `review` -> label `unclear`. Under `require_positive` these
rows did not reach the shortlist; they landed in the review queue tagged
`sponsorship_requires_review`. In this run that shape accounted for **400
postings at a single employer** — and it was the clearest, most affirmative
sponsorship language in the entire scan.

**Shape B — discretionary availability.** A JD states "limited immigration
sponsorship may be available". This is exactly the discretionary case
`LESSONS.md` says "must land `unclear`", but it classified as `yes`.

So the two labels were, in effect, swapped relative to the documented intent:
the strongest real offer read `unclear`, and a hedged maybe read `yes`. Of
the 11,683 postings, only 2 scored `yes` at all (one of them Shape B), while
207 scored an explicit `no`.

The conservative bias itself is deliberate and documented — a wrong `yes` is
handed to someone making an immigration decision. The question is not whether
to relax that bias, but whether Shape A is distinguishable enough to stop being
collateral damage.

## Options

### Option A — Leave the classifier alone; fix only the operating procedure
Add a line to the skill making it mandatory to read `sponsorship_requires_review`
rows before reporting a sponsorship result.
Pros: no risk to a gate that feeds immigration decisions; no new false `yes`.
Cons: every sponsorship-required search needs a manual second pass; the headline
number stays wrong and a less careful run will report "zero roles".

### Option B — Add a distinct `yes_conditional` label
Treat "affirmative offer + scope hedge" as its own outcome, surfaced in the
shortlist under `require_positive` but rendered as `yes*` with the hedge
sentence attached. Shape B moves to `unclear` per the documented rule.
Pros: preserves the never-assert-a-bare-yes principle while making the rows
findable. Cons: a third label touches output formats, the corpus, and handoff
metadata.

### Option C — Narrow the negation scope so a reaffirmation cancels the hedge
Let a following affirmative clause restore the `yes`.
Pros: smallest surface change. Cons: genuinely risky — a reaffirmation is hard
to distinguish from a partial retraction.

### Option D — Grade on offer strength; a scope limit is not a denial (IMPLEMENTED)
Distinguish the two shapes structurally instead of adding a label or trusting a
reaffirmation. See Resolution.

## Recommendation

Option D, taken as an in-policy reversible change under async mode.

## Resolution (agent, 2026-07-31)

Both shapes are resolved, in the directions `LESSONS.md` prescribes, without a
third label and without the reaffirmation heuristic Option C wanted.

**The rule is logical, not lexical.** `not (for EVERY x)` denies a UNIVERSAL and
therefore entails that some x ARE sponsored; `does not sponsor` is the universal
negation. Only the second is a denial. So a negation whose own clause quantifies
over `every / each / all` — or hedges a guarantee — is recorded as a SCOPE LIMIT
(`sponsorship.scope_limit.*`) and counts as neither denial nor offer.

Two properties keep the safety posture the original design exists to protect:

- **A scope limit can only REMOVE a denial, never create an offer.** "We cannot
  sponsor every candidate" on its own is still `unclear`. Shape A's `likely`
  comes entirely from its separate, unhedged first sentence.
- **`at all` is excluded.** "We cannot sponsor visas at all" intensifies a denial
  rather than bounding it, and a backward quantifier only counts inside the
  negation it bounds — so "All roles require work authorization without
  sponsorship" stays a denial.

Shape B is resolved by the same axis read the other way: an offer stated only
under a possibility modal, a discretion clause or a quantity hedge ("limited …
may be available", "case-by-case", "at our discretion") is a HEDGED offer
(`sponsorship.hedged_offer.*`) and lands `unclear`. Grading is now monotone in
offer strength — **unhedged offer > hedged offer > silence, and a scope limit
moves nothing** — which is what makes the two observed cases consistent. A denial
sitting beside a hedged offer is a conflict (`review`), not a silent drop.

Option A's operating-procedure point is no longer load-bearing for these shapes,
but it remains true in general and is preserved by the `review` verdict itself:
`unclear` keeps and flags a posting, so a `require_positive` run that comes back
thin still has the review queue behind it.

Reversible: this is a heuristic behind an advisory gate, fully covered by
fictional regressions in `skills/job-search/filter_variants/corpus.yaml` and
`automation/shared/tests/test_job_metadata.py`. Recorded as an ADR at
`memory/decisions/sponsorship-offer-versus-denial.md`.

**Residual owner question (optional, not blocking):** Option B's distinct
`yes_conditional` label is still available if you want hedged offers to be
*findable* under `require_positive` rather than only kept in the review queue.
The fix removed the motivation for it — the shape that made it urgent now grades
`likely` — so it was not built.

**Your answer:** ______
