# Eval result — application-tracker

| Field | Value |
|-------|-------|
| Skill | `application-tracker` |
| Canary set | `evals/application-tracker/canaries.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `9e3bec374fb4` plus the uncommitted skill diff |
| Model version | `gpt-5` (Codex runtime, 2026-07-28) |
| Config mode | examples fallback / fictional fixtures; no live writes |
| Date | `2026-07-28` |
| Judge | fresh-context manual review against every canary rubric plus deterministic tests |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `at-pipeline-health` | 1 | not captured | not captured | 0 live writes | Folder-derived rollup, action/staleness surfacing, and no unsolicited moves. |
| `at-validate-drafted-metadata` | 1 | not captured | not captured | 0 live writes | Rejects v4, retired `stage`, unknown structured fields, and `total_compensation_range`; validates v5 coupling and JD mappings. |
| `at-enrich-insert-only` | 1 | not captured | not captured | 0 live writes | JD-first, insert-only, formatting-preserving enrichment remains intact. |
| `at-status-move-on-request` | 1 | not captured | not captured | 0 live writes | Explicit whole-app update stays transactional and rollup-consistent. |
| `at-update-one-role-multi-app` | 1 | not captured | not captured | 0 live writes | Exact one-role transition preserves siblings and never invents scheduling data. |
| `at-refresh-in-progress-company-view` | 1 | not captured | not captured | 0 live writes | Renders every in-progress role once, keeps ambiguous evidence at company scope, preserves prose, and is byte-stable on repeat. |

Pass rate: `6/6`.

## Verdict

- **Regression:** PASS. All six canaries passed. The application-tracker suite passed `51/51`,
  shared metadata passed `90/90`, shared calendar passed `26/26`, vendoring passed, and the
  reconciler reported six clean checks.
- **Efficiency vs baseline:** No clean telemetry was exposed. Company-view refresh is one command
  plus one cheap idempotence check; no material regression was observed.
