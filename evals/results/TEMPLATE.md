<!--
One-page result-recording template. Copy to evals/results/<skill>-<git-sha>-<date>.md and fill.
Results are per-machine (network/board state + local model dependent). Tracked for now; may be
gitignored later. Pull tokens/wall-clock from: .venv/bin/python scripts/metrics/report.py --by-sha
-->
# Eval result — <skill>

| Field | Value |
|-------|-------|
| Skill | `<skill>` |
| Canary set | `evals/<skill>/canaries.yaml` |
| Run kind | regression baseline / regression pre-merge / A/B |
| Git SHA | `<12-char sha>` |
| Model version | `<claude model id>` |
| Config mode | examples fallback (config.yaml unset) / private overlay mounted |
| Date | `YYYY-MM-DD` |
| Judge | manual / skill-creator comparator / `<judge model + rubric>` |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `<id>` | | | | | |
| `<id>` | | | | | |
| `<id>` | | | | | |
| `<id>` | | | | | |

Pass rate: `<n_pass>/<n_total>`.

## Verdict

- **Regression:** PASS / FAIL. If FAIL, which canary(ies) + which check regressed, and whether it
  blocks the merge (rubric fail OR large efficiency blow-up vs baseline).
- **Efficiency vs baseline (if comparing):** token / wall-clock / tool-call deltas per canary
  (mean + median from `report.py --by-sha`).

## A/B section (only for run kind = A/B)

- **Pre-registered primary metric:** `<e.g. total_tokens>` — registered on `<date>` BEFORE runs.
- **Variants:** A = `<sha/branch>`, B = `<sha/branch>`. Model pinned: `<model id>`.
- **n paired runs:** `<5-10>`.
- **Efficiency (quantitative):** per-canary paired deltas; overall mean/median delta on the
  primary metric.
- **Quality (directional, blind pairwise):** `<e.g. B preferred 6/8, 2 ties>` — direction only,
  NO significance claim. Judge kappa on calibration set: `<>= 0.6>`.
- **Ship decision:** ship winner as a normal single-purpose commit / no change.

## Stage row (only for run kind = stage A/B — `docs/design/stage-benchmarks/protocol.md`)

Compact variant for a single-stage matched-pair row. Stage rows compare only against other rows of
the SAME stage + fixture version + model id — state all three.

| Field | Value |
|-------|-------|
| Stage id | `<S1–S9 / D1–D11>` (boundary + fixture per `docs/design/stage-benchmarks/stage-map.md`) |
| Fixture | `private/benchmark/fixtures/<version>/<fixture>/` (version pinned; an edit invalidates the row) |
| Variants (SHA pair) | A = `<baseline sha>`, B = `<lever branch sha>` |
| Model version | `<claude model id>` (pinned; a mid-test change voids the row) |
| Primary metric | `<total_tokens | wall_clock_s>` — registered `YYYY-MM-DD` BEFORE the B runs |
| Decision rule | e.g. "ship B if median `<metric>` drops ≥ X% with every gate still PASS" |
| n paired runs | `<2–3>` |

**Per-pair results** (matched pairs on the same fixture; paired delta = B − A on the same input):

| Pair | Fixture instance | A `<metric>` | B `<metric>` | Δ (B−A) | A tool_calls | B tool_calls |
|------|------------------|--------------|--------------|---------|--------------|--------------|
| 1 | `<id>` | | | | | |
| 2 | `<id>` | | | | | |

Median Δ on the primary metric: `<value / %>`. Secondary (descriptive): `tool_calls`, self-audit
bytes read.

**Gate results (must PASS identically on A and B — gate-first; an efficiency win that fails a gate
is a loss):** `check.py` `<PASS/PASS>` · `--check-metadata` `<ok/ok>` · `--check-locations`
`<match/match>` · handoff validation `<ok/ok>`. Blind pairwise artifact read (`evals/rubrics/judging.md`
with `evals/rubrics/artifact-quality.md`): `<e.g. B non-worse; 2 ties>` — direction only, no
significance claim.

**Failure telemetry** (transcript miner over each run's session transcript): tool calls A/B `<n/n>`,
failures by tool `<...>`, retry classification `<meaningless / transient / adaptive>`, tokens burned
in failed + meaningless-retry turns `<n>`. Target: meaningless-retry = 0 (nonzero → file in
`known-issues/`, not accepted as noise).

**Artifacts:** stage output for A and B saved under `private/benchmark/artifacts/<row-id>/` for the
pairwise quality read.

**Ship decision:** apply the pre-registered rule — ship B as one revertible commit / no change. A
shipped slate is still confirmed later by one end-to-end confirmation row (`protocol.md`).
