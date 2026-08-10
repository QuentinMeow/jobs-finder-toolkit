# Should a preferred metro also match its suburbs, and who decides which suburbs?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [issue triage index, 2026-08-03 batch](../../../tasks/0_backlog/2026-08-09-issue-triage-2026-08-03-batch/task.md) · GitHub issue #273
- **Blocks**: nothing. Search runs today; the effect is narrower results, not an error.
- **Default path**: **change no code.** The `location.require_match` fix that shipped
  2026-08-09 already keeps non-preferred US cities instead of dropping them, which recovers
  most of the loss this question is about. Re-measure before building anything. Do not add a
  suburb alias table meanwhile.
- **Cost if wrong**: recurring-loss
- **Safe to merge because**: nothing was written and no matching rule changed. The shipped
  `require_match` fix is independent of this question and revertible on its own.

## Background

`preferred = _has(metro, nloc)` (`automation/shared/location.py:855`) is literal token
matching with no geographic model. A profile naming `boston` rejects Cambridge, Waltham,
Tewksbury and Andover. `seattle` rejects Bellevue and Redmond. A New York list naming
`manhattan`, `brooklyn`, `queens` and `bronx` still rejects Staten Island.

Two things make this more than a preference gap.

**The toolkit contradicts itself.** `aggregators.py:333-354` sends a `distance` radius to
JobSpy, and `skills/job-search/reference.md:192` states that a `{location: "City, ST",
distance: 40}` entry *"covers the whole metro"*. The fetch honours a radius; the gate that
judges the results does not. So the toolkit fetches Redmond and then discards it.

**The casualties are verified and concrete**: principal-level roles at a major employer whose
main campus is a Seattle suburb, rejected by a Seattle profile; the same shape for a San
Francisco profile against a South Bay campus.

**But the blast radius shrank on 2026-08-09.** Before that day, `require_match: false` was a
no-op whenever `us_only: true` — the shipped default — so these suburbs were classified
`other_us` and dropped before the review queue. That conjunction is now fixed, so with the
shipped default profile every one of these suburbs is **kept**. What remains is that they are
not *boosted* as preferred, so they rank lower than a literal city match. That is a ranking
question, not a recall question, and it is a much smaller problem than the issue describes.

## Options

The axis: how much geographic knowledge the public toolkit should own, against how much
per-candidate judgement that knowledge silently encodes.

### Option A — change nothing in code; document and lint *(recommended)*
State plainly in `profiles/README.md` and `_TEMPLATE.yaml` that `preferred` is a literal
token list, and add a profile lint that warns when a profile names a metro whose common
suburbs are absent. The user writes the suburbs they would actually commute to.

***Example consequence:*** You add `bellevue, redmond, kirkland` to your own profile once,
and the big-campus roles in those suburbs start ranking as preferred. A user who never edits
their profile still sees those roles — they just sit lower in the list than a literal Seattle
match.

### Option B — ship an opt-in static metro→suburb alias table
A tracked table (`seattle → bellevue, redmond, kirkland, …`) that a profile switches on with
one key.

***Example consequence:*** You set `metro_aliases: true` and Redmond roles jump into the
preferred tier — along with Tewksbury for a Boston profile, 25 miles out, which you would
never actually commute to. Removing individual entries means editing tracked public data that
every other user shares.

### Option C — carry the fetch radius into the gate
The source config already knows the query origin and radius. Pass that provenance into the
posting's location evidence so the gate uses the same radius the fetch used.

***Example consequence:*** Preferred-ness matches exactly what you asked to be searched, with
no table to maintain — but a posting's tier now depends on which query found it, so the same
job can be preferred via one source and not via another.

## Recommendation

**Option A.** The recall emergency this issue described was mostly the `require_match`
conjunction bug, and that is fixed. What is left is ranking, where the honest answer is that
only the candidate knows which suburbs they would commute to — Tewksbury and Cambridge are
both "Boston" to a table and are not remotely the same to a person. A lint gets the user to
state that once, in their own profile, without the public toolkit pretending to know.

**Strongest case against this:** Option C is the architecturally correct answer and Option A
is a documentation patch over a real inconsistency. The toolkit *already* promises in
`reference.md:192` that a distance entry "covers the whole metro", and Option A resolves that
contradiction by weakening the promise rather than honouring it. A user who configured a
40-mile radius has already told us their commute tolerance in exactly the terms Option C
would use — so the information Option A asks them to re-enter is arguably already on file.

**Confidence:** medium — I verified the literal matching, the shipped-profile behaviour before
and after the `require_match` fix, and the `reference.md` promise. I did **not** re-measure
how many real postings change tier now that the conjunction bug is fixed, and that number is
the one that should actually decide this.

**Your answer:** ______
