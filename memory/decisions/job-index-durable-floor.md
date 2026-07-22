# Preserve index-only job history during builds

- **Status**: decided
- **Date**: 2026-07-22
- **Decided by**: agent (within standing policy)
- **Supersedes / Superseded-by**: complements [derived-zone-git-tracking.md](derived-zone-git-tracking.md)

## Context

The private overlay tracks the compact jobs index and operational state but
gitignores raw payloads and the large derived zone. A checkout can therefore
have valid indexed history without the local inputs needed to regenerate it.
The builder previously rewrote the index solely from locally materialized
entities, so capturing new data on such a checkout could remove older,
still-queryable rows.

## Decision

Treat the pre-existing `index/postings.jsonl` as a durable floor. Both
incremental and rebuild paths deterministically union current entities with
pre-existing rows whose keys have no current entity, derived backing, or
tombstone signal. Current entities win by key. Index-only survivors preserve
their sequence, are marked `carried_from: index`, and do not gain fabricated
derived artifacts. Event-derived `by-day/` and triage indexes remain scoped to
locally available events.

## Alternatives considered

- Track `derived/` in git — rejected because it is large, churn-heavy, and
  contains full job-description prose.
- Drop index rows that cannot be regenerated locally — rejected because
  missing raw and derived data is an accepted multi-checkout state.
- Reconstruct synthetic derived entities from compact index rows — rejected
  because the index lacks the facts and provenance needed for an honest entity.

## Consequences

Builds cannot shrink queryable history merely because raw or derived zones are
not synced. Carried rows remain visibly stale and require fresh source
verification before action. A future explicit entity tombstone must suppress
index carry-forward; otherwise this decision should be revisited only if all
regeneration inputs become durably synchronized.
