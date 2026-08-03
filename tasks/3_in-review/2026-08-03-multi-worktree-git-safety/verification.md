# Verification — 2026-08-03-multi-worktree-git-safety

Commands below were run on 2026-08-03 in the isolated Codex worktree. The
owner's primary checkout and detached stress-test worktree were not used as test
targets.

## Linked-worktree hooks and exclusions

The absolute primary-checkout prefix is redacted below; the commands were run
with that checkout's repository virtual environment against this worktree.

```
$ <PRIMARY_CHECKOUT>/.venv/bin/python -m unittest automation.hooks.tests.test_overlay_hooks
Ran 33 tests
OK
```

## Immutable outgoing-ref scan

```
$ <PRIMARY_CHECKOUT>/.venv/bin/python -m unittest automation.hooks.tests.test_public_pre_push
Ran 6 tests
OK

$ <PRIMARY_CHECKOUT>/.venv/bin/python -m unittest automation.publish.tests.test_leak_guard.GitObjectTests automation.publish.tests.test_leak_guard.StagedTests
Ran 15 tests
OK
```

The normal pre-commit hook chain passed for commit `b0b7f117ee1c`. A first push
without a real configuration was refused as UNARMED; the normal armed push with
`JOBHUNT_CONFIG=<PRIMARY_CHECKOUT>/config.yaml` passed
and published PR #302. No bypass flag was used.

## Review-gate recovery and workflow instructions

```
$ <PRIMARY_CHECKOUT>/.venv/bin/python -m unittest automation.publish.tests.test_review_gate
Ran 86 tests in 66.394s
OK

$ <PRIMARY_CHECKOUT>/.venv/bin/python automation/metrics/instruction_budget.py --strict
skills/github-workflow/SKILL.md  597 lines  36622 bytes  NEAR
OK: all instruction files within budget.

$ git diff --check
<no output; exit 0>
```

## Behavioral eval gate

The risk-based skill eval ran with `gpt-5.6-sol` at `xhigh` reasoning. All four
final canary transcripts passed; efficiency was not measured. The tested bytes
and the honest first-pass misses are recorded in
`evals/results/github-workflow-b0b7f117ee1c-20260803-worktree-safety.md`.
