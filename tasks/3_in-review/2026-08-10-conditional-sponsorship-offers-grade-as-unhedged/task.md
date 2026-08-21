# A conditional sponsorship offer grades as an unhedged offer

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: found and frozen while doing #231 / #238a / #265; recorded as the
  `conditional-offer` rows of
  `skills/job-search/filter_variants/sponsorship_verdict_matrix.yaml`
- **Claimed-by**: agent (2026-08-20, `fix/sponsorship-negation-safety`)

## Goal

An offer stated under a CONDITION ("if approved by counsel", "subject to
internal approval", "provided that a business need is established") must not
reach the candidate as an unhedged offer. It should land where every other
sponsorship ambiguity in this module lands: `review` / `unknown` / low, kept and
flagged, never `match` / `likely` / high.

## Context

`assess_sponsorship` in `automation/shared/job_metadata.py` already demotes an
offer stated under a POSSIBILITY modal or a discretion clause —
`_SPONSOR_HEDGE_RE` covers `may / might / could / possibly / potentially /
limited / discretionary / consider* / case-by-case`. A CONDITIONAL is the same
claim in a different grammar and is not covered, so these three currently grade
`match` / `likely` / `high`, with `classify_visa` returning `yes`:

    If approved by counsel, the company will sponsor H-1B candidates.
    Subject to internal approval, we sponsor work visas for this role.
    Provided that a business need is established, we will sponsor visas.

That is this module's expensive direction. `--visa-policy require_positive` is
the policy chosen precisely by someone who NEEDS sponsorship, and it returns
these with no `sponsorship_requires_review` flag — the same shape of defect as
the closed high-severity item in
`memory/known-issues/visa-sponsorship-negation-phrase-gap.md`, one grammar over.

The three readings are already frozen as `conditional-offer` rows in the
sponsorship verdict matrix, measured at `origin/main` 399a6ec. They were left
`expected-unchanged` on purpose: the work that filed this task was bounded to a
named list of DENIAL shapes, and conditionals were not on it, so moving them
would have been an unmeasured change riding along with a measured one.

Read before starting:

- `memory/decisions/sponsorship-an-unsettled-denial-is-review-not-a-silent-drop.md`
  — why the evidence layer and the verdict layer are separated here, and why a
  cue-list edit alone cannot succeed;
- `memory/known-issues/visa-sponsorship-negation-phrase-gap.md` — five passes of
  history, including three prescriptions in it that turned out wrong in detail;
- the hedged-offer rule (`_sponsor_offer_is_hedged`, `_SPONSOR_HEDGE_RE`,
  `_SPONSOR_HEDGE_MAX_GAP_TOKENS`) — a conditional is most likely a sibling of
  it rather than a new mechanism.

The trap to avoid: a conditional cue list that reaches "if" will fire on
ordinary JD prose ("if you are excited about distributed systems"). The
adjacency bound `_sponsor_cue_within` already enforces is what keeps the hedge
rule from doing that, and the same bound is what this needs.

## Definition of done

- The three sentences above land `review` / `unknown` / low with
  `sponsorship_requires_review` under both visa policies.
- `.venv/bin/python skills/job-search/scripts/sponsorship_matrix.py --diff`
  shows the three `conditional-offer` rows moving and NOTHING else; each moved
  row is flipped to `expected-change` in the same commit, with its `expect`
  block recorded and a `note` saying why.
- `--check` is green, and every tripwire row still agrees with its baseline —
  in particular `sponsorship-offer-then-scope-limit-is-an-offer`,
  `control-plain-offer-stays-an-offer` and
  `not-fixed-immigration-support-plus-every-applicant`, which are the rows a
  hedge that reaches too far takes with it.
- `.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check`
  is green with a fictional corpus case per conditional shape AND a tripwire
  case proving ordinary "if" prose beside a real offer is still an offer.
- The measured count of postings whose verdict moves toward `likely` is ZERO.
