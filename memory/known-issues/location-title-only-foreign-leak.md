# Foreign role with generic location field classifies as us_remote when the city is only in the title

- **Status**: open
- **Severity**: medium (wasted verification work; the JD-text gate catches it downstream)
- **Area**: job-search
- **Source**: job-search canary run on branch `fix/search-hardening`
  (`evals/results/job-search-1949cca7515f-20260721-search-hardening.md`), 2026-07-21

## Symptom

A posting whose foreign city appears only in the *title* (e.g. "Senior SRE —
Bangalore") while its location field holds a generic value like
"Hybrid or Remote" is classified `us_remote` by `scripts/shared/location.py`
and survives location filtering.

## Reproduction

Feed `classify_location("Hybrid or Remote", policy)` a policy with
`us_only: true` — returns a match; nothing consults the title. Observed live
in the canary run when a Bangalore-titled role passed the search-stage
location filter.

## Impact

The role travels to JD-text verification before being rejected, costing one
`fetch_jd.py` fetch + a full JD read (~13 KB) per occurrence. It does NOT
reach drafting: the JD-verification step and the handoff location gate
(PR #38) both catch it. Frequency: at least one hit in a 5-canary run, so
likely routine in daily searches.

## Root cause

`classify_location()` sees only the location string; title text is never
scanned for city/country signals.

## Suggested fix

In the search-stage filter (not the shared classifier), when the location
field matches only via a generic remote/hybrid phrase, scan the title for
known foreign-city/country tokens and downgrade the verdict to `review`.
Keep the shared classifier pure (location-string in, category out); the
title heuristic belongs to the search leg that has the title in hand.
