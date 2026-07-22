# Should the search/application skip-logs become job-store projections?

- **Status**: parked-until-revisit (owner deferred, 2026-07-21)
- **Filed**: 2026-07-21
- **Source**: [raw-data-layer pipeline integration design](../../../design/raw-data-layer/02-job-postings-pipeline.md#6-pipeline-integration)
- **Blocking?**: nothing
- **Revisit when**: raw-data-layer execution-plan stage 3 (pipeline
  integration) has shipped and run for a few weeks

## The question

`applications-log.yaml` and `company-search-log.yaml` gate re-searching and
re-drafting today. Once the job store holds a superset of that information,
they *could* be regenerated from it (one source of truth) instead of being
independently maintained files.

## Why deferred

Doing it now would couple safety-critical skip logic to brand-new
infrastructure. The owner deferred at raw-data-layer sign-off; the store
integration deliberately treats the logs as the sole skip authorities
(design: `design/raw-data-layer/02-job-postings-pipeline.md` →
"Pipeline integration").

## Default path while parked

Logs stay independent and authoritative. When the revisit condition is met,
whoever picks this up should bring store-vs-log divergence data from real
usage — that evidence decides whether projection is worth the coupling.

**Your answer:** ______
