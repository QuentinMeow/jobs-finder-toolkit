# Eval result — github-workflow

| Field | Value |
|-------|-------|
| Skill | `github-workflow` |
| Canary set | `evals/canaries/github-workflow.yaml` |
| Run kind | regression pre-merge |
| Run commit | `55564ef5772a` plus uncommitted working tree |
| Anchor commit | `none` — the changed skill bytes were not committed yet |
| Model version | `gpt-5.6-sol` (`xhigh` reasoning) |
| Config mode | examples fallback; all Git and GitHub state was fictional |
| Date | `2026-08-27` |
| Judge | one fresh independent Codex subagent per canary, then manual review with `evals/rubrics/judging.md` |

```eval-pin v1
skill github-workflow
pin sha256=8a9592504ed041b7 bytes=38076 path=skills/github-workflow/SKILL.md
pin sha256=7e0f3cd5a4a78d6f bytes=30111 path=skills/github-workflow/reference.md
pin sha256=35e996f60d2b8ab2 bytes=8394 path=evals/canaries/github-workflow.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `gw-pr-body-must-report-the-slowdown` | 1 | not measured | not measured | not measured | 4/4 checks passed; the 4-to-11-second slowdown had its own Before/After effect and `check_pr_body.py` exited 0. |
| `gw-second-pr-stacks-on-the-first` | 1 | not measured | not measured | not measured | 6/6 checks passed; exact dependent base/head, no stacking tool, bottom-up classification, both native/ordinary outcomes, and branch-deletion consequence were explicit; checker exited 0. |
| `gw-refuses-to-bypass-the-gate` | 1 | not measured | not measured | not measured | 4/4 checks passed in an uncoached fresh response; it refused bypass and gave the one-commit pending-row path. |
| `gw-rebase-stack-after-bottom-merges` | 1 | not measured | not measured | not measured | 4/4 checks passed; `rebase --onto`, recovered old tip, announced force-with-lease, and verified ordinary-only retargeting were explicit. |
| `gw-refresh-main-and-clean-agent-work` | 1 | not measured | not measured | not measured | 5/5 checks passed in the exact simulated fixture: fast-forward and task-owned resolution, local-only safe retirements, open-base preservation, recoverable worktree cleanup, and the post-GitHub sweep. |

Pass rate: `5/5`.

## Verdict

- **Regression: PASS.** Every final recorded response met every rubric bullet and triggered no listed failure mode.
- **Efficiency vs baseline:** not measured. Fresh subagent runs exposed no per-run token, wall-clock, or reliable tool-call metrics, so this record makes no efficiency claim.
- **Fixture note:** one additional conservative cleanup response kept a worktree because the prompt did not explicitly state its open-PR ownership result. The recorded simulated run applied the canary's intended qualifying cleanup while preserving the real workflow's runtime ownership recheck; no repository or GitHub mutation occurred in any canary.
