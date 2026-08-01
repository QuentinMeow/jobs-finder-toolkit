# Sponsorship: an ambiguous quantifier unsettles a denial, it does not decide one

- **Status**: decided
- **Date**: 2026-08-01
- **Decided by**: agent (within standing policy — reversible heuristic behind an advisory gate)
- **Supersedes / Superseded-by**: completes
  `memory/decisions/sponsorship-scope-limits-need-a-distributive-quantifier.md` (2026-08-01)
  — its items 1–3 stand unchanged; **item 4 is reversed** (`at all` needs its own exclusion
  again) and the second bullet of its Consequences is superseded by this file. The
  8-token framing in its final Consequences bullet is corrected here and in
  `memory/known-issues/visa-sponsorship-negation-phrase-gap.md`

## Context

This is the fourth revision of one classifier rule in one night, and the first three failed
in a pattern worth naming before the decision, because the pattern is the reason for it.

- **Revision one** taught the classifier that a limit on an offer is not a refusal —
  `not (for every x)` negates a universal and entails that some x ARE sponsored — using the
  cue list `every / each / all / guarantee`. Correct in the direction it was aimed at.
- **Revision two** was that rule's cost in the other direction: because a scope limit
  **deletes** the denial, "we are unable to sponsor visas for all new hires" beside an
  unrelated positive graded `match` / `likely` / high, `classify_visa: yes`. A written
  refusal presented as a confident sponsor to the one candidate who cannot take the job.
- **Revision three** removed `all` from the cue list. That closed revision two — provably,
  and it is monotone toward safety: nothing in a 2,948-fixture sweep moves toward `yes`.
  And it reopened revision one's direction, one notch lower down. With `all` simply absent,
  an `all`-bounded denial fell through to the ordinary denial path, which asserts `high`
  confidence from the mere presence of a denial. So

  > "Our immigration team supports H-1B and green card cases, but we do not sponsor all
  > roles."

  graded `no_match` / `unlikely` / **high** with **no** `sponsorship_requires_review` flag,
  and was dropped under **both** visa policies. A posting stating in writing that the
  employer runs an immigration practice handling H-1B and green card cases was deleted from
  the shortlist without a trace. The same sentence written with `every` was kept and
  flagged; the quantifier was the entire difference.

Each revision was a confident narrow fix to the cue list, and a cue-list edit is exactly the
move that cannot succeed here: the list has one bit of output per quantifier, and the two
failure modes sit on opposite values of that bit.

The failure is also bounded in a way that says what the real class is. A posting is newly
dropped only when **no** `_SPONSOR_POSITIVE` phrase survives the context gate — with a
recognised offer beside it the verdict lands on the `denial and positive -> review` branch
and the posting is kept. So the class is *postings whose offer is phrased in words the
phrase list does not contain*, which is precisely the class a phrase list can never
enumerate, and precisely what
`memory/known-issues/visa-sponsorship-negation-phrase-gap.md` is about.

Finally, the asymmetry the module states about itself was not being honoured. Every other
ambiguity here resolves to kept-and-flagged — `review`, `unknown`, low confidence,
`sponsorship_requires_review`: the double negative, the hedged offer, the bare scope limit,
the export-control sense, the denial-beside-an-offer conflict, silence. This one resolved to
*silently deleted at high confidence*, on a sentence the prior decision record calls
ambiguous in so many words.

## Decision

1. **An ambiguous quantifier makes a denial UNSETTLED, not absent and not decisive.** Bare
   `all` (excluding `at all`) marks the denial it bounds; it never removes it.
2. **The evidence layer keeps the denial.** An unsettled denial stays in the `denial` list.
   It is never moved to `scope_limited`, never counted as positive, and never leaves the
   list, so every branch that could reach `match` / `likely` is preempted exactly as before.
   **No promotion is reachable through this pattern** — that is revision three's property,
   and it is structural, not a test result.
3. **The verdict layer stops asserting confidence it does not have.** `assess_sponsorship`'s
   `elif denial` branch used to answer `no_match` / `unlikely` / `high` from the presence of
   a denial alone, without asking whether that denial's reading was settled. It now splits:
   a settled denial answers exactly as before, and a posting whose ONLY denial is unsettled
   answers `review` / `unknown` / `low`, which `visa_ok` keeps and flags under **both**
   policies. **This is the only behavioural change**; the evidence lists decide nothing new.
4. **One settled denial anywhere still wins outright.** "…for all new hires. This role does
   not offer sponsorship." stays `no_match` / `unlikely` / high. A phrase read as settled
   at any occurrence is settled, however many quantified occurrences surround it.
5. **`at all` is excluded from the ambiguous-quantifier cue by name** — reversing item 4 of
   the prior decision, which could drop the exclusion only while bare `all` bounded nothing.
   There `all` intensifies the denial; "we cannot sponsor visas at all" is a flat refusal.
6. The verdict-level property is pinned in **both** directions in one test class, because
   every revision so far fixed one direction by reopening the other and no single test
   would have caught that.

## Alternatives considered

- **Put `all` back in the scope-limit cue list** — this is revision two verbatim; it deletes
  the denial and re-enables the two-step promotion to `likely` / `yes`.
- **Fix it in the evidence layer by giving the unsettled denial its own bucket outside
  `denial`** — the same promotion by a longer route: anything that leaves the `denial` list
  dissolves the `denial and positive -> review` conflict branch. The evidence layer's job
  here is to *mark* the ambiguity; only the verdict layer may act on it.
- **Demote the confidence but keep `decision: no_match`** — `visa_ok` branches on `decision`,
  not on `confidence`, so the posting would still be dropped under both policies and nothing
  observable would change. The defect is the drop, not the label.
- **Widen `_SPONSOR_POSITIVE` until it recognises "immigration team supports H-1B cases"** —
  treats the symptom of an unbounded class with one more phrase, and leaves the next wording
  to be discovered by a user who never sees the posting.
- **Also demote the `every` case** (make an offer-plus-distributive-limit `unclear`) — that
  is the regression the whole rule exists to prevent; it made `require_positive` return zero
  against the clearest sponsor in an 11.7k-posting scan. Left alone deliberately, and the
  fact that it is deliberate is now recorded in the known-issue rather than left implicit.

## Consequences

- The recall loss the prior decision recorded as its accepted cost is **withdrawn, not
  re-traded**: `all`-worded refusals are no longer dropped, and they are not promoted
  either. They land where every other ambiguity in this module lands.
- Cost: an employer that means a flat refusal but writes it with `all` is now `unclear` and
  is kept under the default policy, flagged for a human read, rather than dropped. This is
  the cheaper error by the module's own stated asymmetry (a false denial hides a job; a
  false offer sends someone who needs sponsorship to an employer that said no), and it is
  the direction every other rule here already errs in.
- Measured against the section-1b verdict matrix (33 fixtures) at the parent and at this
  branch: **4 rows move, all `no_match` -> `review`**; every other row is byte-identical.
  Across a 2,948-fixture combinatorial sweep the only transition present is
  `unlikely/high/no_match/no -> unknown/low/review/unclear` (260 cases, all containing a
  bare `all`, none containing `at all`). **0 moved toward `yes`; 0 moved `review` ->
  confident; 0 touched `match` in either direction.**
- **Revisit if** a live run shows postings accumulating in review on `all`-worded refusals
  in volume — the fix trades a silent drop for a flag, and a flag nobody reads is its own
  failure — or if a settled denial reaches `likely` through any other path. The second half
  of that trigger is live today for an unrelated reason: a negation cue the clause scope
  cannot reach is not applied and the offer is scored as an offer. It is tracked in
  `memory/known-issues/visa-sponsorship-negation-phrase-gap.md`, whose repair option (b) is
  this same move applied to the offer side. **That entry's mechanism is a clause-break
  truncation, not the 8-token budget** — the prior decision's final bullet and the
  known-issue both said "budget", both were measured wrong, and both are corrected: for the
  filed sentence `_sponsor_last_cue` returns `None` because `_SPONSOR_CLAUSE_BREAK_RE`
  matches `and the` inside the parenthetical, and the real distance is 12 tokens, not 17.
