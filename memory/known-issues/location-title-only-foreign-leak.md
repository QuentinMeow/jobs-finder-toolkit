# Foreign role with generic location field classifies as us_remote when the city is only in the title

- **Status**: fixed 2026-07-21 by `e967b91` ("Job search: harden filtering and expand target
  coverage"); confirmed still fixed 2026-08-02 — see Resolution below
- **Severity**: medium (wasted verification work; the JD-text gate catches it downstream)
- **Area**: job-search
- **Source**: job-search canary run on branch `fix/search-hardening`
  (`evals/results/job-search-1949cca7515f-20260721-search-hardening.md`), 2026-07-21

## Symptom

A posting whose foreign city appears only in the *title* (e.g. "Senior SRE —
Bangalore") while its location field holds a generic value like
"Hybrid or Remote" is classified `us_remote` by `automation/shared/location.py`
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

## Resolution

Fixed by `e967b91`. The search leg now hands the title to the classifier —
`skills/job-search/scripts/scoring.py`, in the `assess_location(...)` call:

```python
        title=posting.title,
```

and `automation/shared/location.py`'s `assess_location` reads it in the REJECTING
direction only (its own docstring: "The title is read for geography in the REJECTING
direction only — it can mark a posting foreign … but a region word in a title … can never
carry a posting to a match on its own"). Foreign scope is asserted from
`" ".join((nloc, ntitle))`; US scope still only from the location field, so the fix could
not create the mirror-image false positive.

Re-running this entry's own reproduction on 2026-08-02:

```
>>> policy = {"preferred": ["Seattle", "New York"], "allow_remote": True,
...           "us_only": True, "require_match": False}
>>> assess_location("Hybrid or Remote", policy, title="Senior SRE — Bangalore")
category='foreign'  decision='no_match'  evidence=('location_hybrid', 'location_remote', 'foreign_scope')
>>> assess_location("Hybrid or Remote", policy, title="Senior SRE")
category='unknown'  decision='review'    review_reasons=('unclassified_location',)
>>> classify_location("Hybrid or Remote", policy)
'unknown'
```

The Bangalore-titled posting is now rejected outright rather than surviving to a JD fetch,
and even the title-less control no longer reaches `us_remote` — the bare-remote check
(`remote_without_us_scope`) demotes a location field that is nothing but workplace words.
Per `memory/known-issues/README.md` this file is kept one PR cycle and deleted later; it is
NOT deleted here, because `docs/roadmap/desired-state.md` cited it as a live defect and a
reader arriving from that citation needs to find this record.
