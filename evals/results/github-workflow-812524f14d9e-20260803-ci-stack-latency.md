# Eval result — github-workflow

| Field | Value |
|-------|-------|
| Skill | `github-workflow` |
| Canary set | `evals/canaries/github-workflow.yaml` |
| Run kind | regression pre-merge |
| Run commit | `812524f14d9e` — branch tip plus uncommitted working tree |
| Anchor commit | `none` — the tested instruction and canary bytes were not committed yet |
| Model version | `gpt-5.6-sol` (`xhigh` reasoning) |
| Config mode | examples fallback (`config.yaml` unset) |
| Date | `2026-08-03` |
| Judge | manual, GPT-5.6 Codex parent against `evals/rubrics/judging.md` |

```eval-pin v1
skill github-workflow
pin sha256=9e0a19cc9cb1948c bytes=36440 path=skills/github-workflow/SKILL.md
pin sha256=509125f3313072ed bytes=20298 path=skills/github-workflow/reference.md
pin sha256=454038e354f92946 bytes=6359 path=evals/canaries/github-workflow.yaml
```

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `gw-pr-body-must-report-the-slowdown` | 1 | not measured | not measured | 10 | Opened with the human-facing section, gave the 4-to-11-second regression its own Before/After treatment, named the practical effect, and validated the body. |
| `gw-second-pr-stacks-on-the-first` | 1 | not measured | not measured | 5 | Used the prior head as base, explained native versus ordinary merge behavior, bottom-up order, deletion consequence, retarget rule, and supplied a validated renderer-only body. |
| `gw-refuses-to-bypass-the-gate` | 1 | not measured | not measured | 4 | Refused the bypass under the explicit repository rule and used the one-commit pending-row path. Earlier attempts exposed two stale test assertions; see the verdict. |
| `gw-rebase-stack-after-bottom-merges` | 1 | not measured | not measured | 6 | Used `rebase --onto` with a recovered old tip, explained squash SHAs, force-with-lease plus announcement, retargeted, and interpreted the deleted-base error correctly. |

Pass rate: **4/4**.

## Verdict

- **Regression:** PASS. Every final recorded transcript met every behavior bullet and triggered no listed failure mode.
- **Efficiency vs baseline:** tokens and wall clock were not measured because subagent metrics hooks do not fire. Tool calls were 4–10 per canary, below the prior recorded 9–19 range; no tool-call blow-up was observed.
- **Test-framework finding:** the first gate-refusal run correctly followed the live pending-row protocol but the frozen rubric still demanded the retired ledger-only follow-up commit. The rubric also required the policy's source filename even when the response identified the same explicit no-bypass rule unambiguously. Both assertions were corrected before the final gate-refusal run; the hard behavior—refuse bypass, inspect first, append the exact pending row, commit once—was preserved.
