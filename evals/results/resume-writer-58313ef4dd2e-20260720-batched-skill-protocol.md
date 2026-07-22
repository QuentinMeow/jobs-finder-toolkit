# Eval result — resume-writer batched skill categorization

| Field | Value |
|-------|-------|
| Skill | `resume-writer` |
| Canary set | `evals/resume-writer/canaries.yaml` (7 canaries; Step 7 now batched) |
| Run kind | targeted regression pre-merge |
| Git SHA | `58313ef4dd2e` plus uncommitted protocol delta |
| Model version | `GPT-5.6 Sol` (inherited fresh subagent) |
| Config mode | private overlay mounted for live end-to-end exercise; examples fallback for the focused protocol prompt |
| Date | `2026-07-20` |
| Judge | manual against `evals/rubrics/judging.md` |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `rw-skill-category-question-batch` | 1 | unavailable | unavailable | unavailable | Fresh read-only subagent returned one interaction with exactly two single-select question objects, one each for OpenTelemetry and WebAssembly; each used the fixed Never → Weak or Selective → Approved → Other order and did not categorize either term. |
| `rw-tailor-single-posting` (Step 7 delta only) | 1 | unavailable | unavailable | unavailable | Live Airbnb application gathered the remaining queue, presented eight one-skill questions in one form, applied all answers in one profile patch, rebuilt the tailoring card once, updated the tailored resume once, and rendered once; `check.py` passed. |

Focused pass rate: **2/2**.

Deterministic regression checks: `python -m unittest discover -s skills/resume-writer/scripts/tests -p "test_*.py"` passed **49/49**; `check.py` compiled; the updated seven-canary YAML parsed successfully. `pytest` was unavailable in the repository venv, so the built-in `unittest` runner was used.

## Verdict

- **Targeted regression:** PASS. The changed Step 7 semantics enforce gather-first batching, one single-select question per skill, one grouped profile update, and one re-render.
- **Efficiency:** the protocol removes one user round-trip and one profile edit per extra skill. This run did not expose comparable token/wall-clock metrics.
- **Pre-merge note:** the five unaffected canaries were not re-run in fresh model-pinned sessions for this local delta; run the full seven-canary suite before merge.
