# Run the job-search canaries against the unreachable-negation demotion

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: eval-gate debt recorded in the PR for `fix/sponsorship-unreachable-negation`
  (GH issue #15 residual); `evals/README.md` "the eval-gated-merge rule (risk-based)"
- **Claimed-by**: (set when work starts, before the first change)

## Goal

Run `evals/canaries/job-search.yaml` against the tree that carries the unreachable-negation
demotion, and record the result in `evals/results/`. The change adds a verdict path, which
`evals/README.md` classifies as a **MUST run** ("changes step semantics, protocols, verdict
definitions, or deliverables"), and the PR shipped with the run outstanding.

## Context

The classifier change: when a negation cue sits in an offer phrase's own sentence but no
bound (`_SPONSOR_CLAUSE_BREAK_RE`, `_SPONSOR_NEGATION_MAX_GAP_TOKENS`) lets it reach the
phrase, the offer is demoted to `unknown` / `review` instead of being asserted as `likely`.
Both bounds are unchanged. Full rationale:
`memory/known-issues/visa-sponsorship-negation-phrase-gap.md`, "Fixed on 2026-08-02".

`js-visa-require-positive` is the canary that matters most — its whole subject is the
policy this change affects — but the demotion moves rows in *every* run that reads visa
labels, so the whole job-search set is in scope.

**What to watch for, because the unit suites cannot see it.** The demotion trades recall
for safety on one shape: a JD that puts a negation and an unrelated offer in the same
mid-clause position now lands `review` rather than `likely`. The posting is still KEPT
under both policies and carries `sponsorship_requires_review`, so nothing is hidden — but
if that shape is common in the live market, `require_positive` returns fewer clean `yes`
rows and more flagged ones. Measure the actual rate on a real scan rather than assuming it
is rare; the previous four revisions of this classifier each went wrong by reasoning about
frequency instead of counting it.

If the rate is high enough to hurt, repair 0(a) in the known-issue ("widen the reach") is
still open and would shrink the set that reaches the demotion. That is the owner call the
known-issue names.

## Definition of done

- [ ] `evals/canaries/job-search.yaml` run against a tree containing the demotion, with the
      model pinned, and the record written to `evals/results/`.
- [ ] The record states the measured `require_positive` row counts and how many rows carry
      `sponsorship_requires_review` because of `sponsorship.unreachable_negation.*` —
      the recall cost, counted rather than assumed.
- [ ] Either the known-issue's severity/consequence lines are re-measured and updated, or
      the record says explicitly that they still hold.
