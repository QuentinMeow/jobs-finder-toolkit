# Eval result — resume-writer (multi-experience delta gate)

| Field | Value |
|-------|-------|
| Skill | `resume-writer` |
| Canary set | `evals/resume-writer/canaries.yaml` (7 canaries, including `rw-multi-experience-baseline`) |
| Run kind | regression pre-merge, uncommitted delta on base SHA |
| Git SHA | `58313ef4dd2e` + current working-tree delta |
| Model version | GPT-5.6 Sol (Cursor inherit) |
| Config mode | examples-only fake config; isolated temporary applications root |
| Date | `2026-07-20` |
| Judge | fresh runner for the new artifact canary + separate manual rubric review of all seven |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `rw-tailor-single-posting` | 1 | n/a | n/a | n/a | Conceptual delta review PASS; locked fields, baseline anchoring, skill gates, render/check path unchanged for the legacy example. Legacy render/check passed. |
| `rw-layout-budget-verdict` | 1 | n/a | n/a | n/a | Conceptual delta review PASS; legacy verdict remains `739/734pt` OVERFLOW and render remains authoritative. |
| `rw-multi-experience-baseline` | 1 | not exposed | ~7 | 41 | Fresh isolated run PASS: 662/734pt estimate (including 16pt extra header), one-page resume/letter, ordered employers, direct bullets before projects, correct ownership, metadata/location valid, exact temp-only outputs. |
| `rw-bundled-txt-structure` | 1 | n/a | n/a | n/a | Conceptual delta review PASS; the E2E bundle rendered a 223-word, three-paragraph letter with all three canonical packet sections. |
| `rw-skill-gating-weak-never` | 1 | n/a | n/a | n/a | Conceptual delta review PASS; Rust/Kafka behavior retained. Boundary/negation and nested `AWS (Lambda, SQS, SNS)` selective-gating regressions also pass unit tests. |
| `rw-skill-category-question-consequences` | 1 | n/a | n/a | n/a | Conceptual delta review PASS; category-question instructions were not changed. |
| `rw-duplicate-preflight` | 1 | n/a | n/a | n/a | Conceptual delta review PASS; duplicate-preflight instructions and behavior were not changed. |

Pass rate: **7/7**.

## Verdict

- **Regression: PASS.** A separate read-only reviewer first found six implementation/setup
  gaps; all six were fixed and re-reviewed as resolved. The new multi-experience canary then
  ran in a fresh isolated session and produced no repository changes.
- **Quality gates:** 42-test resume-writer suite passed before review; focused post-review
  extraction/fixture/validation regressions passed; legacy and multi-experience renders passed.
- **Efficiency:** no token metric was exposed for the fresh runner. Its artifact run completed
  in approximately 7 seconds with 41 total tool calls (14 shell invocations). Existing six
  canaries retain the model-pinned 6/6 baseline recorded in
  `resume-writer-06c3c5e50000-20260720-regate.md`; the current delta review found no behavioral
  or large-efficiency regression in those paths.
- **Non-blocking warnings:** the synthetic multi-experience fixture reports 94% bullet drift
  and approximately 1.3 inches trailing whitespace; both are below failure thresholds and are
  intentionally retained to exercise warning output.
