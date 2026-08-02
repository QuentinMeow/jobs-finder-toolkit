# Worklog — 2026-07-31-salary-range-parses-a-garbled-band

## 2026-07-31 — session 1 (agent, branch `wip/35-pipeline-parse-defects`)

- Checked the anchoring hypothesis first, as the task asked. It is real: the
  `_AMOUNT` number pattern had no digit boundary at either end, so `$3240 -
  $175,000` read `240` as the low. Fixed at the match site with `(?<![\d.,])` /
  `(?!\d|[.,]\d)`.
- Anchoring alone does **not** explain the reported row. A second, independent
  route reaches the same `$240 - $175,000` shape with both matches well-formed:
  a real salary band and a small non-salary dollar range (a stipend) in the same
  compensation paragraph are both kept — the nearest preceding keyword to each is
  "base salary" — and `_salary_envelope` collapses them to (min of mins, max of
  maxs). Reproduced from a fixture; that is the case the task's row came from.
- Chose to fix the CAUSE per band rather than only sanity-check the pair. A pair
  check at the envelope would have dropped the whole fact, losing the correct
  `$140,000 - $175,000` band with the bogus one. A period-aware floor drops only
  the band that is not pay, so the real band survives — "silently dropped beats
  wrong" is true, but a correct band should not be collateral.
- Kept the pair check anyway as a backstop at `_salary_envelope`, because the
  collapse can stitch two individually credible bands into a pair no posting
  stated, and per-band plausibility cannot see that.
- Thresholds set generously and argued in the code comment: period floors sit
  below any real posted rate (hourly, part-time monthly and annualised intern
  bands all clear them) and the 10x spread is far wider than the widest real
  all-levels annual band (~6x).
- Noticed but did NOT fix: a bare 4-6 digit figure with no comma ("$175000 -
  $195000") parses to nothing, before and after. Widening the number pattern
  would let year ranges ("2024 - 2026") in, so it belongs in its own task with
  its own corpus.
