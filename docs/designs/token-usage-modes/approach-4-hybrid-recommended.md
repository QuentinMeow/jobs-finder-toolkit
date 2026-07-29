# Approach 4 — Staged hybrid (recommended)

**Strategy:** Sequence the other three approaches from risk-free to riskiest, so each
stage ships value on its own and the mode switch (the only stage with a real quality
trade-off) lands last, on top of infrastructure that shrinks how much the modes even
need to differ.

## Stage 1 — Script-first mechanics (Approach 2, no instruction rewrites)

Ship the pure wins first; none of these can reduce output quality:

1. `search_jobs.py --cache-dir/--refilter` (kills repeated full fetches when widening
   windows or re-emitting JSON).
2. `handoff.py` — folder + `meta.yaml` v3 + verbatim JD from a selected search-JSON
   row; agents start at gap analysis.
3. Compact default stdout; full detail to JSON file.
4. `build_tailoring_card.py` + a gardener/staleness check for it.
5. Raw-text JD fetcher (fetch once, save verbatim, share downstream).

*Gate:* script tests + a before/after token measurement on a standard
search-plus-two-drafts run (the baseline in [README](README.md)).

## Stage 2 — Instruction tiering (Approach 1, careful and eval-gated)

With Stage 1 done, SKILL.md workflows genuinely shrink (steps became script calls),
making the rewrite both easier and safer:

1. Quickstart headers on `job-search` and `resume-writer` SKILL.md.
2. `AGENTS.md` core/annex split (hard guardrails stay in core).
3. Ratchet `instruction_budget.py` budgets down to lock in the trim.

*Gate:* canary evals green per edited skill; instruction budget strict pass.

## Stage 3 — The mode switch (Approach 3, thin by construction)

Now `token_saving` mode is mostly *composition* of things that already exist
(quickstart-only reading, tailoring card, handoff.py, capped render cycles,
no-subagent search) rather than a separately implemented behavior. `full` mode adds
deep per-JD research, full-library reads, and iterative polish. Default:
`token_saving`; the quality floor (every validator, every hard gate) is
mode-independent; drafts record which mode produced them.

*Gate:* canaries in both modes; a documented upgrade path (`--mode full` re-run on an
existing folder).

## Why this ordering

- **Most savings arrive before any quality risk is taken.** Stages 1–2 are
  quality-neutral or quality-improving and are projected to cut half or more of a
  routine run's tokens on their own.
- **The mode diff stays small.** If modes were built first (Approach 3 alone), the
  token_saving path would need its own shortcuts implemented ad hoc — a bigger,
  riskier fork to maintain. Built last, the fork is a few flags over shared
  machinery.
- **Each stage is independently shippable** as a focused PR chain with its own
  verification, matching the repo's contribution style.

## Cons / open questions

- Longest calendar path to the headline feature (the visible mode switch).
- Stage 2 remains the high-stakes edit (safety-critical instructions); it can be
  deferred or shrunk if canaries prove brittle — Stages 1+3 still compose.
- Cache TTL semantics (Stage 1.1) and tailoring-card staleness need explicit rules
  before Stage 3 defaults the world onto them.
- Should `token_saving` search skip the subagent entirely (main session runs the
  script)? Recommended yes for routine runs; the SKILL.md quickstart should say when
  a subagent *is* warranted (anomaly investigation, multi-profile sweeps).
