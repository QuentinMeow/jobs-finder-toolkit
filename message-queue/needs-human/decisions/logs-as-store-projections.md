# Should the search/application skip-logs become job-store projections?

- **Status**: parked-until-revisit (owner deferred, 2026-07-21)
- **Filed**: 2026-07-21
- **Source**: [raw-data-layer pipeline integration design](../../../docs/designs/raw-data-layer/02-job-postings-pipeline.md#6-pipeline-integration)
- **Blocks**: nothing
- **Default path**: logs stay independent and authoritative; nothing is projected from the store.
  Full rationale in “Default path while parked” below.
- **Cost if wrong**: ratify
- **Safe to merge because**: the logs stay exactly as they are; the store is additive and reads
  them without writing them.
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
(design: `docs/designs/raw-data-layer/02-job-postings-pipeline.md` →
"Pipeline integration").

## Default path while parked

Logs stay independent and authoritative. When the revisit condition is met,
whoever picks this up should bring store-vs-log divergence data from real
usage — that evidence decides whether projection is worth the coupling.

## Note appended 2026-07-30 — the applications half is now harder to reverse

Workspace phase 6 made the applications skip-log **append-only and
authoritative**: `applications-log.jsonl`, folded last-wins, never rewritten.
That was not a decision on this question — it fixed a separate bug (a
regenerated log meant deleting an application un-skipped its posting) — but it
does move the cost. Projecting the applications half from the store would now
mean *un*-making it authoritative, and the append-only file holds rows whose
application folder no longer exists, which the store cannot reconstruct. The
company-search half is untouched and still a plain upsert, so the question
stands unchanged for it.

If the answer here ever turns out to be "yes, project both", the migration owes
an answer for those folder-less rows.

**Your answer:** ______
