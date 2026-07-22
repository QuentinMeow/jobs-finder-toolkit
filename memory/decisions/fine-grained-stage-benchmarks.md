# Benchmark at stage granularity with pinned fixtures, not only end-to-end

- **Status**: decided
- **Date**: 2026-07-20
- **Decided by**: owner (mandate: "design the benchmark logic more fine
  grained for each part, instead of running things end to end"; mechanics by
  agent)

## Context

All prior token-program rows ran the full pinned scenario (~450k tokens per
row: one search + two drafts). That made each lever's effect expensive to
measure and noisy — network drift, LibreOffice latency, and JD-difficulty
variance confounded per-mechanism deltas (the Stage-3 row needed three
explicit confound paragraphs to be readable).

## Decision

Adopt `design/stage-benchmarks/protocol.md`: decompose each leg into
stages with observable boundaries, freeze intermediate artifacts as fixtures
under `private/benchmark/fixtures/` (versioned, capture-once), and A/B each
lever on the one stage it touches (matched pairs, pinned model, one primary
metric, gate-first quality). Stage artifacts are saved per row for blind
pairwise comparison. Every row also records tool-failure telemetry (failed
calls, retry classification) from its own transcript. The end-to-end
scenario survives as the *confirmation row* run once per shipped slate.

## Alternatives considered

- **End-to-end only (status quo)** — ~900k tokens per A/B pair and
  confound-laden reads; rejected by the owner's mandate.
- **Pure script microbenchmarks (no agent in the loop)** — cheap but blind to
  the dominant costs, which are agent reads/reasoning, not script runtime.
- **Synthetic fixtures (fictional candidate)** — leak-guard-friendly but
  unrealistic; tailoring quality against a fake profile wouldn't transfer.
  Real-intermediate fixtures stay in the private overlay instead.

## Consequences

- Fixtures freeze real intermediates; a fixture version bump invalidates
  cross-version comparisons and must be recorded on every row.
- Stage rows are comparable only within the same stage + fixture version +
  model id; leg-level claims require the confirmation row.
- `evals/results/` gains stage-row files; the template gets a stage variant.
