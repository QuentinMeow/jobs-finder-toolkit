# Sponsorship: only a distributive quantifier makes a negation a scope limit

- **Status**: decided
- **Date**: 2026-08-01
- **Decided by**: agent (within standing policy — reversible heuristic behind an advisory gate)
- **Supersedes / Superseded-by**: narrows item 1 of
  `memory/decisions/sponsorship-offer-versus-denial.md` (2026-07-31); every other item of
  that decision stands unchanged

## Context

The 2026-07-31 decision taught the classifier that a limit on an offer is not a refusal:
`not (for every x)` negates a UNIVERSAL and so entails that some x ARE sponsored, whereas
`does not sponsor` is the universal negation. That reasoning is correct, and the shape it
was written for — an employer states an offer, then bounds it — is the way nearly every
genuine sponsor writes it.

The cue list it shipped was `every / each / all / guarantee`. The bare word `all` does not
carry that reasoning. `every` and `each` are **distributive**: they range over individuals
one at a time, so a negation must outscope them and the sentence necessarily leaves
individuals on both sides — which is precisely what licenses the inference that some roles
are sponsored. `all` is number-neutral and also admits a **collective / definite** reading,
under which "for all new hires" means "for the new hires, as a class" and the sentence is
`∀x. ¬sponsor(x)` — a flat denial that merely names the population it covers. There the
quantifier bounds the DENIAL's own domain, not an offer, and nothing about sponsorship
existing is entailed.

That distinction turned out to be safety-critical rather than academic, because the
implementation makes a scope limit **delete** the denial:

> "We offer green card sponsorship to existing employees after two years. We are unable to
> sponsor visas for all new hires."

graded `verdict: likely`, `confidence: high`, `decision: match`, `classify_visa: yes` — a
posting that states in writing it will not sponsor a new hire, presented to a candidate who
IS a new hire as a confident sponsor, with no `sponsorship_requires_review` flag. The prior
decision's reopen trigger ("a flat denial reaching `unclear` through the quantifier path")
was set one notch too low: the path does not lead to `unclear`, it leads to `likely`.

The reason it goes that far is the second finding here. The prior decision's item 2 — *a
scope limit can only REMOVE a denial, never create an offer* — is **enforced only for the
evidence lists**, where a scope-limited phrase is put in its own bucket and never counted as
positive. Nothing enforces it for the VERDICT, and there removing a denial is not neutral:
it dissolves the `denial and (positive or hedged_offer) -> review` branch, so the posting
moves from `review`/`unknown`/low to `match`/`likely`/high in one step. A misread quantifier
is therefore a promotion in the unsafe direction, not merely a missing demotion.

## Decision

1. **A negation is a scope limit only when the quantifier bounding it is DISTRIBUTIVE** —
   `every` / `everyone` / `everybody` / `each` — or when it hedges a `guarantee`. Bare `all`
   is removed from `_SPONSOR_SCOPE_LIMIT_RE`.
2. **A quantifier that admits both readings keeps the denial.** This module already resolves
   every ambiguity toward the cheaper error (a false offer sends someone who needs
   sponsorship to an employer that said no in writing; `unclear` costs nothing), and an
   ambiguous quantifier is exactly such an ambiguity.
3. **The invariant is pinned at the verdict level, not just per phrase.**
   `QuantifiedDenialTests::test_no_quantified_denial_is_ever_promoted_to_a_confident_offer`
   asserts over the whole class — each quantified denial × each offer × both orderings —
   that the result is never `likely` / `match`.
4. `at all` no longer needs its own exclusion: bare `all` bounds nothing, so
   "we cannot sponsor visas at all" is a denial by the general rule. The corpus case stays
   as a pin.

## Alternatives considered

- **Gate the promotion behind "no denial phrase anywhere in the JD"** — the shape the prior
  decision exists to fix ("we are not able to sponsor visas for every role") matches a
  denial phrase itself, so this reverts that fix wholesale.
- **Make a scope-limited denial land `unknown` even beside an unhedged offer** — same
  problem: it demotes the corpus's blessed offer-plus-limit row, which is the one case the
  prior decision was written for.
- **Distinguish by discourse relation** (a concessive "however / that said" marks a limit on
  a preceding offer; two independent sentences partitioning a population do not) — the
  truest reading of the difference, but it needs "is the neighbouring offer unqualified?",
  which is not decidable from a phrase list. Revisit if the quantifier rule proves too
  coarse in a live run.
- **Annotate rather than delete** (keep the denial but mark it bounded, and let the
  aggregation decide) — a larger change to the evidence model than the defect warrants; the
  quantifier narrowing closes the reported class with three fewer moving parts.

## Consequences

- A JD whose refusal is written with `all` is a denial again, exactly as it was before
  2026-07-31: `unlikely` / high alone, and a `review` conflict beside an offer.
- The cost is the mirror error: an employer that genuinely means "not everyone" but writes
  `all` is now graded `unlikely` and dropped under the default policy. That is the cheaper
  of the two errors by this module's own stated asymmetry, and it is recorded here so the
  trade is visible rather than discovered.
- `require_positive` still surfaces employers whose offer is real but bounded — the
  offer-plus-limit row grades `likely` / high unchanged.
- **Revisit if** a live run shows a real sponsor writing its limit with `all` and being
  dropped, or if a flat denial reaches `likely` through any other path. The second half of
  that trigger is live today for an unrelated reason — a negation cue further than 8 tokens
  from the offer phrase it governs is not applied and the offer is scored as an offer — and
  is tracked in `memory/known-issues/visa-sponsorship-negation-phrase-gap.md`.
