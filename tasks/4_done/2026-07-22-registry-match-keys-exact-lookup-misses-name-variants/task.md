# Resolve company-name variants consistently in job-search skip logic

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: 2026-07-22 job-search execution session; migrated from the pre-AgentFold task queue
- **Claimed-by**: Cursor agent (2026-07-22)

## Goal

Treat conservative legal-suffix variants of the same employer as one identity
throughout registry resolution and both job-search skip logs, without broad
fuzzy matching or conflating known-distinct companies.

## Context

Registry identity previously used exact normalized names, aliases, and tokens.
An aggregator spelling such as `Acme Ltd.` therefore did not match a registry
or log row stored as `Acme`, allowing recently searched or already considered
postings to resurface.

The fix belongs in `skills/job-search/scripts/registry.py` and
`search_jobs.py`. It must preserve exact-key behavior, support companies absent
from the registry, and abstain when two registered companies share the same
suffix-stripped base.

## Definition of done

- Registry keys match fictional short and legal-suffix variants symmetrically.
- Ambiguous registered bases and unrelated employers never intersect.
- Both company-search-log and applications-log skips fire across variants in
  either direction while a different role at the same company still surfaces.
- Focused and full job-search tests, the shared suite, filter-variant corpus,
  and vendored-copy drift check pass.
