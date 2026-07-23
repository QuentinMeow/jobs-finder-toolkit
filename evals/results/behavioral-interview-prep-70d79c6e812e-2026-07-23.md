# Eval result — behavioral-interview-prep

| Field | Value |
|-------|-------|
| Skill | `behavioral-interview-prep` |
| Canary set | `evals/behavioral-interview-prep/canaries.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `70d79c6e812e` plus the current uncommitted working-tree change |
| Model version | `gpt-5.6-sol-xhigh` |
| Config mode | examples fallback; private overlay explicitly excluded |
| Date | `2026-07-23` |
| Judge | manual parent-agent read against every rubric bullet |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `bp-story-bank-file` | 1 | unavailable | unavailable | 9 | First-person, one project, long tagged chronology, explicit gaps, and no invented facts. |
| `bp-story-revision-credibility` | 1 | unavailable | unavailable | 9 | Rejected unsupported motive, savings, solo credit, and ordering; preserved the profile's exact 40% causality and shared credit. |
| `bp-story-to-question-mapping` | 1 | unavailable | unavailable | 13 | Four grounded families; 168-word / 84-second quick answer; all modules and both reference views; validator-clean. |
| `bp-tell-me-about-yourself` | 1 | unavailable | unavailable | 9 | Present-past-future, about 76 seconds, concise and grounded; no STAR/YAML treatment. |
| `bp-company-principles` | 1 | unavailable | unavailable | 15 | Four separate complete principle packages with every required module; timing/schema checks passed and unsupported principles were withheld. |

Pass rate: `5/5`.

## Verdict

- **Regression:** PASS. Every canary, including the adversarial credibility revision, met its
  quality rubric without using private candidate data.
- **Efficiency vs baseline:** Not assessed. The local metrics log was empty and the subagent API did
  not expose token, wall-clock, or tool-call counts for these fresh-context runs.
- **Run isolation:** The canaries returned proposed artifacts rather than editing tracked files.
  The Amazon rerun validated temporary source/render pairs under scratch and removed them afterward.
