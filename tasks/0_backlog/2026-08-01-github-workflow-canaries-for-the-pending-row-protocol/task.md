# Run the github-workflow canaries against the pending-row commit protocol

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: PR that made `commit:` optional in the review ledger and pointed the pre-commit hook at `review_gate.py --staged`; that PR rewrote the "The review gate: one commit carries its own row" section of `skills/github-workflow/SKILL.md` and declared `Eval gate: debt`.

## Goal

Confirm the rewritten commit protocol in `skills/github-workflow/SKILL.md` does not regress the github-workflow canaries, and record the run under `evals/results/`.

## Context

The review gate no longer needs a follow-up ledger-only commit. `automation/publish/review_gate.py` accepts a row with no `commit:` (a PENDING row, anchored by `base:` + `digest:`, whose endpoint is resolved as the commit that introduced it), and `--staged` moves the endpoint from HEAD to the staged index. `automation/hooks/pre-commit` runs `--staged`.

The instruction change that needs the canaries is in `skills/github-workflow/SKILL.md`:

- the gate table's row 3 now names `--staged`;
- "The review gate and the one-commit lag" became "The review gate: one commit carries its own row" — a four-step lag procedure replaced by a three-command loop plus the two row shapes;
- the stacked-PR merge recipe no longer claims every branch tip is a ledger-only `Acknowledge …` commit.

That is a behavioural instruction edit, so `evals/README.md` asks for a canary run before merge. It was not reachable inside the PR that made the change: one measured github-workflow canary run costs about a session's worth of turns and tokens, and `evals/**` was concurrently owned by another agent. The mechanism itself is covered by 14 new regression tests in `automation/publish/tests/test_review_gate.py` (`PendingRowTests`); what is untested is whether an agent reading the new SKILL.md still lands a branch green.

## Definition of done

- `evals/canaries/github-workflow.yaml` run against the current `skills/github-workflow/SKILL.md`, model-pinned, with no large efficiency regression.
- A record filed under `evals/results/` per `evals/README.md`, naming the pending-row protocol as the change under test.
- If the canaries show the new protocol is followed incorrectly, a follow-up task or a SKILL.md correction, not a silent pass.
