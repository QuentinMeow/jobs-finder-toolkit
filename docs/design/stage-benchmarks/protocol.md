# Stage benchmarks (v1) — fine-grained, fixture-pinned measurement

**Status:** adopted 2026-07-20. Successor to end-to-end-only measurement under
`docs/design/token-usage-modes/benchmark-scenario.md` (which remains the
definition of the *confirmation row*; this protocol adds the per-stage layer
beneath it). Operating rules inherit from `evals/ab-protocol.md` — matched
pairs, one pre-registered primary metric, model-pinned runs.

## Why stages

The end-to-end scenario costs ~450k tokens per row and mixes every mechanism
together, so a single lever's effect drowns in network noise (job boards, web
fetches), LibreOffice latency, and JD-difficulty variance. Almost every lever
touches exactly one stage of the pipeline. Measuring **that stage alone,
against pinned input fixtures**, resolves a lever's effect at n = 1–2 pairs
instead of a 450k-token row per arm — and the saved intermediate artifacts
double as the fair-comparison inputs the next lever starts from.

Two consequences, stated up front:

- **Stage rows do NOT sum to a leg total.** An isolated stage re-pays boot
  and loses cross-stage context carryover; absolute stage numbers are valid
  only against other rows of the *same* stage. Cross-stage claims come from
  the end-to-end confirmation row only.
- **A stage win must survive the confirmation row.** After a slate of stage
  wins ships, one full scenario run (benchmark-scenario.md, isolated config)
  confirms the cumulative effect against the last full row.

## Fixtures — `private/benchmark/fixtures/` (never committed to public)

All fixtures are snapshots of real intermediates, captured once, then frozen
(a fixture edit invalidates every row that used it — version the folder name,
e.g. `fixtures/v1/`). Sources: the existing benchmark drafts under
`private/benchmark/applications/6_drafted/` and one fresh search capture.

| Fixture | Contents | Isolates stage(s) |
|---|---|---|
| `search-snapshot/` | one frozen `tmp/search_cache/`-format pre-filter JSON (+ `-latest` pointer) | S3 fetch, S4 filter/rank (run `--refilter`, zero network) |
| `jd-set/` | 6 frozen JD pages: 4 clean HTML, 2 JS-shell (to exercise the ATS-API fallback path), + expected workplace/visa verdicts in `expected.yaml` | S6 verification, S7 gates |
| `search-row/` | one frozen search-JSON candidate row + empty target tree | S8 handoff, S9 metadata |
| `handoff-folder/` | one complete handed-off folder (`meta.yaml` + `source/JD-*.md`), stretch-fit variant + like-fit variant | D3–D5 tailoring, D9 cover/bundle, D10 Step-7, D11 metadata |
| `tailored-pass/` | a frozen `tailored.yaml` known to PASS at capture time | D7 layout, D8 render+check (pure render/validate latency + cycles) |
| `context/` | hash-pinned copies of tailoring card + baseline + the 3 skill lists | D2 and all draft stages (context never drifts mid-comparison) |

Capture note: the profile/baseline/card evolve with the owner's real hunt —
fixtures deliberately freeze the copies, so a fixture round is internally
consistent even when the live profile has moved on.

## Stage tasks — subject-agent protocol

A stage row = one **pinned prompt** given to a fresh subject agent
(model-pinned: `claude-sonnet-5`, same as all prior rows), with
`JOBHUNT_CONFIG` pointed at the benchmark config, entry state restored from
fixtures, and the stage's natural exit boundary (artifact written / script
exit — see the boundary tables in `stage-map.md` §D,
which this section pins). The prompt tells the agent to do the stage's job
per the normal skill instructions — it does NOT inline shortcuts; the point
is to measure the skill surface as agents actually experience it.

Per row, record (into `evals/results/` via the template):

- `total_tokens` (**primary metric for token levers**), `tool_calls`,
  `wall_clock_s` (**primary for D8/S3 latency levers**);
- the self-audit (files read + `wc -c`, large stdout);
- **tool-failure telemetry**: failed tool calls, retries and their
  classification (from the transcript-mining script over the run's session
  transcript);
- the stage artifact itself, kept under
  `private/benchmark/artifacts/<row-id>/` for pairwise quality comparison.

## A/B rules (inherited + stage-specific)

1. Matched pairs on the same fixture; A = baseline SHA, B = lever branch;
   fresh session per run; n = 2–3 pairs per stage (stages are cheap — a pair
   costs ~10–40k tokens, not ~900k).
2. ONE pre-registered primary metric + decision rule, written in the results
   file **before** the B runs.
3. Quality is gate-first: the stage's hard gates must PASS identically
   (check.py / --check-metadata / --check-locations / handoff validation),
   and the stage artifact must be non-worse under the blind pairwise read
   (`evals/rubrics/judging.md`) applied with the artifact-quality rubric
   (`evals/rubrics/artifact-quality.md`, promoted alongside this protocol).
   Efficiency wins that fail a gate are losses.
4. Network-touching stages (S3 fresh-fetch, D4 research) are benchmarked in
   back-to-back pairs only, same capture window — or against local fixtures
   where the fixture exists (S6, S8).
5. Validity scope: one model id, one fixture version, one SHA pair — state
   all three on every row.

## Failure-rate telemetry (standing)

Every stage row and every future full row runs the transcript miner over its
own session transcript and records: tool-call count, failure count by tool,
retry classification (meaningless / transient / adaptive), tokens burned in
failed+meaningless-retry turns. Target: keep "meaningless retry" at zero — a
nonzero count is a bug to file in `known-issues/`, not noise to accept.
