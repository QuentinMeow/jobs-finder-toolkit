# Eval result — coding-interview-cleanup

| Field | Value |
|-------|-------|
| Skill | `coding-interview-cleanup` |
| Canary set | `evals/coding-interview-cleanup/canaries.yaml` |
| Run kind | regression baseline / forward acceptance |
| Git SHA | `070324a06584` |
| Model version | `GPT-5 Codex session (exact build not exposed)` |
| Config mode | disposable untracked fixture plus private-overlay forward application; no private content recorded |
| Date | `2026-07-26` |
| Judge | manual artifact inspection against `evals/rubrics/judging.md` |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `cic-fresh-messy-screenshots` | 1 | n/a | n/a | n/a | Disposable fixture: backup reduced three inputs to two unique checksummed originals; exact-pixel crops, stable naming, guide, solution run, and audit passed. |
| `cic-resume-half-cleaned-folder` | 1 | n/a | n/a | n/a | Real-artifact forward test: existing 22-image backup and seven valid crops were preserved; repeat backup was a no-op and final audit passed. |
| `cic-coaching-guide-from-progressive-prompt` | 1 | n/a | n/a | n/a | Real-artifact forward test: obsolete initial-stage identity removed, coaching guide completed, implementation left logically unchanged, and all ten practice sequences passed. |

Pass rate: `3/3`.

## Verdict

- **Regression:** PASS. Every rubric check passed and no listed failure mode was observed.
- **Efficiency vs baseline:** This is the skill's first baseline, executed inside the active user
  session because a clean-session harness was unavailable. Per-canary token, wall-clock, and
  tool-call metrics were therefore not separable and are recorded as `n/a`; no comparative
  efficiency claim is made.
- The disposable fixture was removed after artifact inspection. The private forward application
  is referenced only at aggregate level so no personal or private problem content enters the
  public eval result.
