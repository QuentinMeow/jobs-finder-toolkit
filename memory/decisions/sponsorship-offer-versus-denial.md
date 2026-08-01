# Sponsorship: an offer plus a limit on that offer is not a denial

- **Status**: decided
- **Date**: 2026-07-31
- **Decided by**: agent (within standing policy — reversible heuristic behind an advisory gate)

## Context

Teaching the sponsorship classifier to read negation structurally fixed a real
false-offer rate: a denial the phrase list never anticipated ("does not
currently offer visa sponsorship") used to be reported as an explicit offer, and
`--visa-policy require_positive` handed those to a candidate making an
immigration decision.

It over-corrected. A live 11,683-posting scan found the single clearest
sponsorship offer in the whole market grading `unclear`: an employer states an
unambiguous offer, then bounds it ("we aren't able to sponsor for every role and
every candidate"). The bounding sentence carries its own negated offer phrase,
denial beat offer, and `require_positive` returned **zero** engineering roles at
an employer that previously returned 55. Returning zero when a real sponsor
exists is the worst outcome that filter can produce.

The same scan found the inverse: a vaguer "limited sponsorship may be available"
graded `yes`, contradicting the documented rule that discretionary language must
land `unclear`. The two labels were effectively swapped.

## Decision

Grade sponsorship on **offer strength**, and treat a limit on an offer as
distinct from a refusal.

1. **Scope limits.** A negation whose own clause quantifies over a UNIVERSAL
   (`every` / `each` / `all`) or hedges a guarantee limits the SCOPE of
   sponsorship rather than denying it, and counts as neither denial nor offer
   (`sponsorship.scope_limit.*`). This is a logical distinction, not a lexical
   one: `not (for every x)` entails that some x ARE sponsored, whereas `does not
   sponsor` is the universal negation.
2. **The asymmetry is preserved.** A scope limit can only REMOVE a denial, never
   create an offer. Text that only bounds ("we cannot sponsor every candidate")
   stays `unclear`.
3. **`at all` is excluded**, and a backward quantifier counts only inside the
   negation it bounds — so "we cannot sponsor visas at all" and "all roles
   require work authorization without sponsorship" both remain denials.
4. **Hedged offers.** An offer stated only under a possibility modal, a
   discretion clause or a quantity hedge ("limited … may be available",
   "case-by-case", "at our discretion") is a hedged offer
   (`sponsorship.hedged_offer.*`) and lands `unclear`, per LESSONS.md.
5. **Ordering.** Unhedged offer > hedged offer > silence; a flat denial still
   wins over everything, and a denial beside a hedged offer is a conflict
   (`review`), never a silent drop.

## Alternatives considered

- **Leave the classifier; fix the operating procedure only** — the headline
  number stays wrong, and a less careful run reports "zero roles offer
  sponsorship" when a sponsor is in the data.
- **A third `yes_conditional` label** — touches output formats, the corpus and
  handoff metadata to express something the offer-strength ordering already
  expresses. Still available if the owner wants hedged rows *findable* under
  `require_positive`; the shape that made it urgent now grades `likely`.
- **Let a reaffirmation cancel the hedge** — a reaffirmation is hard to tell from
  a partial retraction, which is exactly how a false `yes` gets made. The
  quantifier reading needs no such judgement and is order-independent.
- **Revert the negation work** — the false positives it fixed were real and
  worse than the false negatives it introduced.

## Consequences

- `require_positive` surfaces employers whose offer is real but bounded, which is
  how nearly every genuine sponsor writes it.
- Fewer bare `yes` labels: discretionary wording moves to `unclear`, which keeps
  and flags the posting rather than asserting anything.
- Revisit if a live run shows a flat denial reaching `unclear` through the
  quantifier path — the guard for that is the backward-cue constraint, and its
  regressions are `sponsorship-all-as-requirement-subject-stays-a-denial` and
  `sponsorship-at-all-is-still-a-flat-denial` in the corpus.
