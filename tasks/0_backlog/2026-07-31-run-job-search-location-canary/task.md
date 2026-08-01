# Run the job-search single-company canary at the location-gate branch head

- **Priority**: P1 (this round)
- **Area**: benchmarks
- **Source**: branch `wip/17-location-gate-jd-body` — the eval gate was REQUIRED
  for that PR and could not be run in the session that wrote it.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Run `js-single-company-location-verdict` (and the rest of
`evals/canaries/job-search.yaml` if a fuller pass is wanted) at that branch's head
and record the result in `evals/results/`, so the location-gate change merges with
its gate satisfied rather than deferred.

## Context

That PR edits `skills/job-search/SKILL.md` and `skills/job-search/LESSONS.md` in a
way `evals/README.md` puts squarely in **MUST run**: it changes a verdict
definition (the single-company re-check now reports a three-valued
match/review/no-match outcome), changes what the agent is told to relay, and
changes the meaning of `--match-only`. It also edits the canary's own rubric and
failure modes, so the rubric being tested is new.

The run did not happen because the canary is network-required against a live ATS
board (`setup:` says so) and the authoring session was explicitly barred from
fetching one; that session's worktree also had no `config.yaml` and no overlay.
This is a deferral, not a skip — the PR body records it as such.

Two of the rubric lines are new and are the point of the run:

- a `REVIEW` row is presented as "needs the posting read", never relayed as a
  no-match, and is opened with `--jd` before any claim is made about it;
- no role is reported as US-remote on a region word in its TITLE while the JD
  requires office days.

## Definition of done

- `js-single-company-location-verdict` run at the branch head against a real board,
  `rubric_pass` recorded, and no large `total_tokens` / `tool_calls` regression
  versus the runs already in `evals/results/`.
- A results file added from `evals/results/TEMPLATE.md`, model-pinned per
  `evals/README.md`.
- If the canary fails, the finding goes back to the branch as a fix, not to the
  rubric.
