# `salary_range` carries annual pay or nothing — never a converted or unlabelled band

- **Status**: decided
- **Date**: 2026-08-01
- **Decided by**: agent (within standing policy — a parser output rule, reversible)

## Context

`salary_range` is defined as posted pay in USD/**year**. The period-aware pay-band floor
added on 2026-07-31 removes an implausible ANNUAL band before `_salary_envelope` runs, and
the envelope's "prefer annual bands so a stray hourly band cannot shrink the envelope" line
then has no annual band left to prefer. Preference silently degrades to fallback, so an
intern's `$30 - $45 per hour` is published as the posting's salary range.

Measured on this branch against the parent commit, same JD text:

```
parent 4020119  ->  salary_range: min=240   max=175000   (garbled, but obviously so)
tip             ->  salary_range: min=30    max=45       (an HOURLY band, in a per-year field)
```

The second is worse. `$240 – $175,000` announces itself as broken; `$30 – $45` does not, and
it is written into `meta.yaml` by `status.py --enrich-metadata` and shown in the shortlist as
fact, stamped `source: job_description`, `confidence: high`.

A lone hourly band reached the same field by the same route before that change, so this is
one rule, not a patch on one regression.

## Decision

When no band the posting stated **per year** survives, `salary_range` is `None`.

Three options were on the table and the field's consumers decide between them.

1. **Nothing (chosen).** `salary_range: null` is already valid in schema v5 and is already
   the normal state for most postings, so no consumer learns anything new and no `meta.yaml`
   migrates. The tracker row reads "none parsed", which the reader resolves from the JD on
   disk. This is the failure mode the band guards were already written to prefer: *"a
   dropped band is recoverable … a wrong band is shown to the user as fact and written into
   meta.yaml."* Nothing is destroyed — `extract_salary_range` still returns the band with
   its `period`, so a consumer that wants hourly pay can read it there.
2. **An annualised figure — rejected.** Multiplying by 2080 h/yr encodes an assumption the
   posting never made: full-time FTE hours. That is exactly wrong for the intern, contract
   and part-time bands this path sees, and the repo's hardest guardrail is *never fabricate*.
   The derived number would then carry `source: job_description` and `confidence: high` — a
   figure the JD does not contain, labelled as one it does.
3. **The band plus a unit marker — rejected for now.** `salary_range` has exactly
   `{min, max, confidence, source}` in schema v5 and its validator. Adding `period` means
   changing the schema, the validator, three vendored copies, the tracker display and the
   shortlist — and until *every* consumer branches on it, each one that reads `min`/`max`
   keeps the identical bug with a label nobody looked at. Worth doing if hourly postings ever
   become a target segment; it is not a fix for this defect.

## Alternatives considered

- **Keep "prefer annual" and only harden the band floor** — leaves the fallback in place, so
  the next parser change that rejects an annual band re-opens the same hole.
- **Refuse only in the multi-band case** — the reported regression, but a lone hourly band
  publishes the same wrong unit by the same route.

## Consequences

- Postings that state only hourly, weekly, daily or monthly pay show no salary range. The
  aggregator fallback (`supplied_salary_range`) is unchanged and still fills the field where
  a feed supplied an annual figure.
- **Revisit if** hourly/contract roles become a target segment — the answer then is option 3
  (carry `period` through to the field), not option 2.
