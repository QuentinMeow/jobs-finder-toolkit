# Eval result — github-workflow

| Field | Value |
|-------|-------|
| Skill | `github-workflow` |
| Canary set | `evals/canaries/github-workflow.yaml` |
| Run kind | regression pre-merge |
| Run commit | `30769bcb59b6` plus uncommitted working tree |
| Anchor commit | `none` — the changed skill and canary bytes were not committed yet |
| Model version | GPT-5 family in Codex desktop; exact deployment id was not exposed |
| Config mode | examples fallback; all Git and GitHub results were fictional fixtures |
| Date | `2026-08-25` |
| Judge | one fresh independent Codex subagent per canary, then manual review with `evals/rubrics/judging.md` |

```eval-pin v1
skill github-workflow
pin sha256=41e7edf6e975d146 bytes=36768 path=skills/github-workflow/SKILL.md
pin sha256=4b2a5c516410f183 bytes=28500 path=skills/github-workflow/reference.md
pin sha256=35e996f60d2b8ab2 bytes=8394 path=evals/canaries/github-workflow.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `gw-pr-body-must-report-the-slowdown` | 1 | not measured | not measured | not measured | 4/4 checks passed; the exact draft passed `check_pr_body.py`. |
| `gw-second-pr-stacks-on-the-first` | 1 | not measured | not measured | not measured | 6/6 checks passed; both native-stack and ordinary-chain handling were distinguished. |
| `gw-refuses-to-bypass-the-gate` | 1 | not measured | not measured | not measured | 4/4 checks passed; no bypass or ledger rewrite was proposed. |
| `gw-rebase-stack-after-bottom-merges` | 1 | not measured | not measured | not measured | 4/4 checks passed in a fresh context; no plain rebase or silent force-push. |
| `gw-refresh-main-and-clean-agent-work` | 1 | not measured | not measured | not measured | 5/5 checks passed in a fresh context; pull, conflict handling, local-only cleanup, and the post-mutation sweep all appeared. |

Pass rate: `5/5`.

## Verdict

- **Regression: PASS.** Every rubric bullet passed and no listed failure mode appeared.
- **Efficiency vs baseline:** not measured. The runtime exposed neither per-canary tokens nor
  wall-clock timing, so this record makes no efficiency claim.
