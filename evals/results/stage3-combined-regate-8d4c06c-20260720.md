# Eval result — combined re-gate: Stage-3 mode switch × PR #23 multi-experience

| Field | Value |
|-------|-------|
| Skill | `resume-writer` — full current 7-canary set (incl. #23's `rw-multi-experience-baseline` and the batched Step-7 rubric) |
| Run kind | combined-state re-gate: Stage-3 (`4a1d589` merge) landed on top of PR #23, whose SKILL.md/LESSONS/reference edits and canary updates were gated separately — the combination was not. job-search suite NOT re-run: #23 touched no job-search or AGENTS.md files, so the Stage-3 gate's 5/5 at `446a954` remains valid for js (documented rationale). |
| Git SHA | 6 canaries at `4a1d589`; `rw-layout-budget-verdict` re-run at `8d4c06c` (see delta note) |
| Model version | runners `claude-sonnet-5`, one fresh session per canary |
| Config mode | examples fallback; fixtures per issue #16; multi-experience canary per its own isolated-tree setup |
| Date | 2026-07-20 |
| Judge | manual — orchestrator per `evals/rubrics/judging.md`, artifacts inspected, zero-write claims verified |

## Per-canary results

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------|--------------|--------------|------------|-------|
| `rw-tailor-single-posting` | 1 | 137,165 | 601 | 57 | Card built + used; justified backup swap (IaC/CI-CD coverage); estimate OVERFLOW→trim→OK 704pt, 1 cycle; check.py pass (67% drift soft-warn, swap-driven); **batched Step 7 honored — queue legitimately empty, documented**. |
| `rw-layout-budget-verdict` | 0 → **1 (re-run)** | 67,552 / 72,381 | 210 / 200 | 23 / 21 | First run: bands/budget/simulate all correct but the verdict again omitted the check.py-authority statement (3rd occurrence across gates; ~50% compliance as a trailing bullet). Fixed structurally at `8d4c06c`: the authority note is now part (2) of a two-part verdict definition. Re-run states it verbatim → PASS. |
| `rw-bundled-txt-structure` | 1 | 105,211 | 295 | 40 | Three `===` sections; paras 138/146 w, 318-w body; check.py 0 warnings; 1-page verified; restored incidentally re-rendered resume bytes. |
| `rw-skill-gating-weak-never` | 1 | 74,643 | 231 | 22 | False premise caught; Rust Never-blocked ("closed decision, not a Step-7 item" — correct under batching); Kafka Weak-refused; zero resume edits (card build only). |
| `rw-skill-category-question-consequences` | 1 | 62,314 | 91 | 12 | **Batched protocol**: single-skill queue → one single-select question; consequence labels verbatim in mandated order, Other last; stopped; zero writes (verified). |
| `rw-duplicate-preflight` | 1 | 53,885 | 73 | 13 | Folder-scan detection, hard block, zero writes (verified), refresh offered. |
| `rw-multi-experience-baseline` (new, #23) | 1 | 91,388 | 328 | 32 | Isolated-tree setup from manifest (seeded inputs only); both employers preserved in canonical order, direct bullets before projects; employer overhead in estimate (662pt OK); 1-page with both employers verified; zero writes outside the isolated tree. |

Pass rate: **7/7** (one canary required a protocol restructure + re-run).

## Head-delta note (`4a1d589` → `8d4c06c`)

The re-run head differs by one restructure of the Step-5.5 verdict protocol only
(authority note folded into a two-part verdict definition; trailing bullet
removed). No other canary's protected behavior references that block, so the six
`4a1d589` runs remain valid; delta and non-interaction recorded here.

## Verdict

- **Gate: PASS.** The combined state — Stage-2 tiering + Stage-3 mode switch +
  #23 multi-experience pipeline + batched Step-7 — holds the full current rubric.
- **Recurring-flake fixed structurally:** the check.py-authority verbalization
  failed in 2 of 4 gate samples as a trailing bullet; as part of the verdict
  definition it bound on the first re-run sample. Watch one more gate cycle.
- Batched Step-7 (from #23) is coherent with the Stage-2/3 quickstart: empty
  queues are documented, single-skill queues ask one question, consequence
  labels and order survive.
