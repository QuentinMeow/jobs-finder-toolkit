# Handover — hygiene-stack

- **Date**: 2026-07-29
- **Task(s)**: `tasks/3_in-review/2026-07-29-vendored-config-repo-root-wrong`; plan + task
  refresh for the six unstarted workspace phases

## What happened

After phases 0, 3 and 4 merged, four stacked PRs (#89 → #92) cleaned up what they left behind.

- **#89** adds the `github-workflow` public skill. It writes down the PR-description format
  (a human-facing Before / After / What you'll notice section first, plain English, technical
  detail underneath), the fact that stacked PRs need no tool — GitHub detects the pattern when
  each PR's base is the previous PR's head — and the gates in the order you actually meet them.
  `scripts/check_pr_body.py` enforces the mechanical half.
- **#90** fixes a real bug: `REPO_ROOT` was computed by counting two directories up, which is
  wrong in all four vendored copies of `config.py`. A config-less run through any skill loaded
  an *empty* config rather than the example persona. It is now discovered by walking up.
- **#91** closes the benchmark-profile question. There was no regression — the previous
  session measured it under the wrong config.
- **#92** makes the execution plan and the six remaining task files true: phases 0/3/4 recorded
  as done, every appendix number re-measured, each remaining phase given what the finished ones
  taught it.

## Where things stand

- Four PRs open, stacked, targeting each other in order; #89 targets `main`. CI green.
- `tasks/0_backlog/` now contains only work that has not started.
- **Two more pieces of the owner's application history were found in the public tree and
  redacted** — a task file listing real employers, and the phase-5 move table naming companies
  inside file paths. That is the third occurrence. No automated check found any of them:
  company names are not identity tokens, so only a person reading the diff catches them. The
  review gate is the only thing that puts that diff in front of someone.
- Every PR in this stack was written using the format the skill in #89 defines, and every body
  was validated by that skill's own checker before posting.

## Needs your attention

- [Config discovery fallback](../../../message-queue/needs-human/decisions/config-discovery-example-fallback.md)
  — implemented on the default path (raise only when an overlay is mounted). Confirm, or pick
  the stricter option and the two docs get rewritten to match.
- [Private-scope reconciler](../../../message-queue/needs-human/decisions/private-scope-reconciler.md)
  — none exists, so the overlay hook reports the skip. Your overlay's process layer has 2
  findings, so enabling it today blocks your next overlay commit until they clear.
- [Logs as store projections](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  — pre-existing, unrelated, still open.
- [Workspace layout review](../../../message-queue/needs-human/reviews/workspace-restructure-plan.md)
  — answered and folded; safe to delete once you have confirmed nothing was mis-folded.
- Your benchmark MANIFEST documents a manual symlink step that is now unnecessary. It lives in
  the overlay, so striking it is yours to do; nothing depends on it.
- Eight items in the private queue mirror remain open from earlier sessions; untouched.
