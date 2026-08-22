# Eval result — company-research

| Field | Value |
|-------|-------|
| Skill | `company-research` |
| Canary set | `evals/canaries/company-research.yaml` |
| Run kind | regression pre-merge |
| Run commit | `02fa203db610` plus uncommitted working tree |
| Anchor commit | `none` |
| Model version | `gpt-5.6-sol` (`xhigh`) |
| Config mode | examples fallback (isolated public copies; `JOBHUNT_CONFIG` pinned to copied `config.example.yaml`) |
| Date | `2026-08-21` |
| Judge | independent `gpt-5.6-sol` (`xhigh`) agents against `evals/rubrics/judging.md` |

```eval-pin v1
skill company-research
pin sha256=6594a24bcdd7be04 bytes=8995 path=skills/company-research/SKILL.md
pin sha256=19d4ce6cb6029fa6 bytes=4163 path=skills/company-research/LESSONS.md
pin sha256=d58730dbc55ce0cd bytes=16759 path=skills/company-research/reference.md
pin sha256=fb325b0de343b116 bytes=41017 path=skills/company-research/dossier-guide.md
pin sha256=d3d1953d8a4da79b bytes=15124 path=evals/canaries/company-research.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `cr-quick-chat` | 1 | not measured | not measured | not measured | Chat-only; loaded the router and task-relevant sources, wrote nothing, and did not load the dossier/profile/application tiers. |
| `cr-full-research-structure` | 1 | not measured | not measured | not measured | Final independent judge: 7/7 checks; 17 files, all required depth/source/confidence/scope rules. The run's validation loop repaired seven missed inline scope tags and one heading before acceptance. |
| `cr-product-cold-reader` | 1 | not measured | not measured | not measured | Independent judge: 5/5; beginner-first explanation, dependency-ordered vocabulary, illustrative flow, and ownership boundary. |
| `cr-moat-5whys` | 1 | not measured | not measured | not measured | Post-repair rerun: 4/4; typed 5-Whys, Claim/Evidence/Judgment, and one categorical Strong/Moderate/Weak rating per competitor. |
| `cr-ai-strategy` | 1 | not measured | not measured | not measured | Independent judge: 7/7; GA/beta/planned/unverified maturity, structural edge, inverse threat, and internal adoption. |
| `cr-question-bank` | 1 | not measured | not measured | not measured | Post-repair rerun: 3/3; every question has a company anchor and intent; no compensation/WLB/visa/work-model probes. |
| `cr-honest-scaffolding-fictional` | 1 | not measured | not measured | not measured | Post-repair rerun: 3/3; no invented facts and all five required verification sources named. |

Pass rate: `7/7`.

## Verdict

- **Regression:** PASS. The retiered skill preserved the complete dossier behavior, added a verified chat-only quick path, and produced no `Invalid prompt` policy rejection in any canary run.
- **Efficiency vs baseline:** not measured. Subagent runs had no per-SHA token, wall-clock, or tool-call instrumentation, so this record makes no efficiency-regression claim.

