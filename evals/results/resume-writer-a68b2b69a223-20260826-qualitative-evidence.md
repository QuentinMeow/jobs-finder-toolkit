# Eval result — resume-writer

| Field | Value |
|-------|-------|
| Skill | `resume-writer` — all 9 canaries |
| Canary set | `evals/canaries/resume-writer.yaml` |
| Run kind | regression pre-merge |
| Run commit | `a68b2b69a223` plus the uncommitted `evals/README.md` count correction, which does not affect subject behavior or rubric bytes |
| Anchor commit | `a68b2b69a223` — carries the exact skill, reference, and canary bytes exercised |
| Model version | `gpt-5.6-sol`, `model_reasoning_effort="xhigh"` |
| Config mode | examples fallback with isolated public-only configs and disposable fixtures; private overlay not read |
| Date | `2026-08-26` |
| Judge | manual strict rubric judgement by GPT-5.6 Sol xhigh; artifacts inspected independently |

```eval-pin v1
skill resume-writer
pin sha256=e51fd1c36a0dcf5b bytes=33223 path=skills/resume-writer/SKILL.md
pin sha256=96f4e8f53400b6ab bytes=8314 path=skills/resume-writer/LESSONS.md
pin sha256=1d5b989da0872a18 bytes=36195 path=skills/resume-writer/reference.md
pin sha256=9896e6fff6e88284 bytes=18273 path=evals/canaries/resume-writer.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `rw-tailor-single-posting` | 1 | not measured | not measured | not measured | Preflight, baseline start, locked fields, five profile projects, all default artifacts, one-page render, validation, and DOCX integrity passed. Step 7 ran and its complete queue was empty, so zero questions was the correct per-skill cardinality. Limitation: this fixture does not exercise question formatting or option order; `rw-skill-category-question-batch` covers that behavior separately. |
| `rw-layout-budget-verdict` | 1 | 114,793 | not measured | not measured | Correctly distinguishes the 739pt estimate from the authoritative rendered one-page PDF gate and preserves supported content. |
| `rw-multi-experience-baseline` | 1 | 210,327 | not measured | not measured | Preserved both employers, all six direct bullets, and all four projects; render and check exited 0. Two advisory warnings were disclosed, not bypassed. |
| `rw-bundled-txt-structure` | 1 | 108,163 | not measured | not measured | Produced the canonical bundle and cover artifacts; paragraph two used the fixture's source-backed 50M+, 30+, and 35% metrics; render/check exited 0 with no warnings. |
| `rw-sparse-source-qualitative-cover-letter` | 1 | 45,649 | not measured | not measured | Produced a 130-word paragraph using specific source-backed actions and no number, estimate, unsupported outcome, or invented detail. |
| `rw-skill-gating-weak-never` | 1 | 80,590 | not measured | not measured | Declined the Never skill, withheld the Weak skill absent JD support, and preserved the stored categories. |
| `rw-skill-category-question-batch` | 1 | 27,430 | not measured | not measured | Asked exactly two one-skill questions in one batch with the required option order and made no category edit. |
| `rw-multi-role-one-folder` | 1 | 165,709 | not measured | not measured | Created one shared resume, two exact JD mappings, and separate bundles/cover letters; render/check exited 0 with no warnings. A proposed unsupported metric-heavy rewrite was rejected and not bypassed. |
| `rw-duplicate-preflight` | 1 | 71,747 | not measured | not measured | Detected the duplicate before writing and left the sentinel unchanged. |

Pass rate: `9/9`.

## Verdict

- **Regression: PASS; does not block merge.** Every expected behavior held and no listed failure
  mode occurred. In `rw-tailor-single-posting`, Step 7 ran and returned a complete queue of zero
  uncategorized skills, so asking zero questions satisfied the per-skill requirement; fabricating a
  skill merely to force an interaction would violate the workflow. That fixture does not exercise
  the question format or option order. The independently passing `rw-skill-category-question-batch`
  canary supplies that coverage with two real uncategorized terms.

- **Efficiency vs baseline:** not compared. These are the first recorded GPT-5.6 Sol xhigh runs and
  the fresh non-interactive sessions included heterogeneous fixture setup and repository ritual.
  Eight rows reported 824,408 tokens in total; `rw-tailor-single-posting` did not expose a token
  count. Wall-clock time and tool calls were not measured, so no efficiency conclusion is licensed.

## A/B section

Not applicable — this was a single-variant regression run.

## Stage row

Not applicable — no stage fixture or matched-pair run was used.
