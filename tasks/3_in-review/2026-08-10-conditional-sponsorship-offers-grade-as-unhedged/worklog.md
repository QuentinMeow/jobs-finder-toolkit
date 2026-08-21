# Worklog — 2026-08-10-conditional-sponsorship-offers-grade-as-unhedged

## 2026-08-20 — session 1 (agent)

- Picked up while fixing a higher-severity defect in the same function: a
  refusal written in the sponsorship head noun's own PREDICATE ("H-1B
  sponsorship is unavailable.") graded `match`/`likely`/high. Both defects are
  the hedge/negation grammar one step outside where the module was looking, so
  they were repaired and measured together.
- The task predicted the repair correctly: a conditional is a sibling of the
  hedge rule, not a new mechanism. One thing it could not predict — a FRONTED
  condition sits outside the bounded clause scope `_sponsor_offer_is_hedged`
  reads, cut off by the very comma break that scope relies on. So the condition
  is read over the SENTENCE HEAD instead, and the trap the task named ("if you
  are excited about distributed systems") is handled by requiring the
  subordinator to govern an approval or a gating resource rather than by an
  adjacency bound.
- All three `conditional-offer` matrix rows flipped to `expected-change` with
  `expect` blocks and notes; `--check` green at 101 rows. Corpus carries the
  conditional case and its ordinary-"if" tripwire.
- Next: review/merge with the rest of `fix/sponsorship-negation-safety`.
