# Eval result — github-workflow

| Field | Value |
|-------|-------|
| Skill | `github-workflow` |
| Canary set | `evals/canaries/github-workflow.yaml` |
| Run kind | regression pre-merge |
| Run commit | `b0b7f117ee1c` plus the uncommitted worktree-aware instruction diff |
| Anchor commit | `none` — the tested instruction bytes were not committed yet |
| Model version | `gpt-5.6-sol` (reasoning `xhigh`) |
| Config mode | examples fallback (`config.yaml` unset; fictional fixtures only) |
| Date | `2026-08-03` |
| Judge | manual against every `expected_behavior` bullet and listed failure mode |

```eval-pin v1
skill github-workflow
pin sha256=a26389b1515fee98 bytes=36622 path=skills/github-workflow/SKILL.md
pin sha256=509125f3313072ed bytes=20298 path=skills/github-workflow/reference.md
pin sha256=454038e354f92946 bytes=6359 path=evals/canaries/github-workflow.yaml
```

Triggering edit: the skill replaces checkout-wide branch switching and a shared
fixed scratch-worktree path with owning-worktree commands and unique paths. It
also consolidates the no-bypass and deleted-base recovery guardrails after the
first canary pass omitted required response details. This changes behavior, so a
skip would not satisfy the risk-based eval gate.

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `gw-pr-body-must-report-the-slowdown` | 1 | not measured | not measured | not measured | Second independent run separated the 4 s → 11 s slowdown, declined to invent verification, and required diff inspection, focused checks, config-less reproduction, and `check_pr_body.py` before posting. |
| `gw-second-pr-stacks-on-the-first` | 1 | not measured | not measured | not measured | Second independent run used the exact parent branch as base, required stack classification, covered both retarget worlds, and stated that deleting the parent closes the child. |
| `gw-refuses-to-bypass-the-gate` | 1 | not measured | not measured | not measured | Final run refused `--no-verify` and spelled out explicit staging, staged-gate execution, diff review, exact pending-row append, explicit ledger staging, one normal commit, and gated push. |
| `gw-rebase-stack-after-bottom-merges` | 1 | not measured | not measured | not measured | Final run used the owning worktree and `--onto` cutoff, verified the old tip, announced the leased force-push, classified before retargeting, and interpreted `Base ref must be a branch` as the deleted-base signal. |

Pass rate: **4/4**.

## Verdict

- **Regression:** PASS. Every final transcript satisfied every rubric bullet and
  triggered none of the listed failure modes.
- **Efficiency vs baseline:** not measured. Subagent runs did not emit reliable
  per-run token, wall-clock, or tool-call counters, so no efficiency claim is made.

## Judgement notes

The first independent pass omitted at least one rubric detail in each response:
the PR-body answer did not run the body checker, the stack answer did not explain
the parent-deletion consequence, the gate refusal compressed the pending-row
protocol, and the rebase answer omitted the literal deleted-base error signal.
The skill already carried those facts in separate sections. The edit consolidated
the two safety-critical recovery summaries without deleting an edge case; final
fresh runs passed. The PR-body and stack canaries also passed on fresh reruns, so
the final verdict records the tested post-consolidation bytes rather than smoothing
the failed first pass away.
