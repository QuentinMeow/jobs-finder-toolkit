# Run the github-workflow canaries against the two-track merge runbook

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: PR that corrected the merge recipe in `skills/github-workflow/SKILL.md`, added `skills/github-workflow/reference.md` and `skills/github-workflow/scripts/merge_stack.py`, and rewrote the `gw-second-pr-stacks-on-the-first` canary; that PR declared `Eval gate: debt`.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Confirm that an agent reading the corrected two-track merge instructions in
`skills/github-workflow/SKILL.md` and `skills/github-workflow/reference.md` classifies a PR
before merging it and picks the right command for each world, and record the run under
`evals/results/`.

## Context

The skill previously taught one merge recipe — `gh pr merge <n> --merge` followed by an
explicit `gh pr edit <n+1> --base main` — that is correct for an ordinary pull request and
wrong for a member of one of GitHub's native stacks, which answers HTTP 403 to
`gh pr merge` and is retargeted by GitHub itself. Ten native stacks exist in this
repository, so both worlds are live here.

The PR that fixed this changed instruction files in three ways that a canary can see:

- `skills/github-workflow/SKILL.md` §2 now opens the merge block with a classification step
  and gives a two-track command block instead of the two-line recipe;
- `skills/github-workflow/reference.md` is new and holds the long runbook, the failure-mode
  catalogue and the evidence;
- the Guardrails line changed from "never merge your own stack out of order" to "never merge
  a stack without classifying it first", with a different confirmation per world.

It also **rewrote a canary**. `gw-second-pr-stacks-on-the-first` used to REQUIRE the answer
"GitHub does not retarget it automatically", which is true only outside a native stack — that
rubric would now fail correct behaviour. Its `expected_behavior` now requires the
classification step and accepts either retarget branch. A canary set edited in the same diff
as the instructions it grades is exactly the case that needs a run rather than a reading.

This is a behavioural instruction edit, so `evals/README.md` asks for a canary run before
merge. It was not reachable inside the PR that made the change: one measured github-workflow
canary run costs about a session's worth of turns and tokens. The script half is covered by
49 regression tests in `skills/github-workflow/scripts/tests/test_merge_stack.py` (mocked
`gh`, no network); what is untested is whether an agent reading the new prose reaches for
`merge_stack.py` or the right hand-typed command.

The separate backlog item
`tasks/0_backlog/2026-08-01-github-workflow-canaries-for-the-pending-row-protocol/` covers a
different edit to the same skill (the pending-row commit protocol). A single run of
`evals/canaries/github-workflow.yaml` at a commit containing both changes discharges both;
say so in the record if that is what happens.

## Definition of done

- `evals/canaries/github-workflow.yaml` run against the current
  `skills/github-workflow/SKILL.md` and `skills/github-workflow/reference.md`, model-pinned,
  with no large efficiency regression.
- Every canary's `rubric_pass` passes, `gw-second-pr-stacks-on-the-first` included — that one
  is the point of this run.
- A record filed under `evals/results/` per `evals/README.md`, naming the two-track merge
  runbook as the change under test.
- If a canary shows the classification step is skipped or the wrong track is chosen, a
  follow-up task or a SKILL.md correction, not a silent pass.
