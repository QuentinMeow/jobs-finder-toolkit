# Verification — 2026-08-01-github-workflow-canaries-for-the-pending-row-protocol

## Model-pinned regression canaries

```
Fresh-session subjects: gpt-5.6-sol, xhigh reasoning
gw-pr-body-must-report-the-slowdown: PASS (10 tool calls)
gw-second-pr-stacks-on-the-first: PASS (5 tool calls)
gw-refuses-to-bypass-the-gate: PASS (4 tool calls)
gw-rebase-stack-after-bottom-merges: PASS (6 tool calls)
Pass rate: 4/4
total_tokens: not measured
wall_clock_s: not measured
```

## Eval content pins

```
$ .venv/bin/python automation/evals/record_pins.py --write evals/results/github-workflow-812524f14d9e-20260803-ci-stack-latency.md
note: not pinned (absent): skills/github-workflow/LESSONS.md
refreshed eval-pin block for `github-workflow` (3 file(s) pinned).
```

The subsequent report showed all three pins differ from committed `HEAD`, as
expected: the record intentionally pins the uncommitted instruction and canary
bytes tested in this stack tip rather than falsely naming the parent commit.
