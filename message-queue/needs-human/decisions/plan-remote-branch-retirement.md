# May the cleanup planner write a script that deletes merged REMOTE branches?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-21
- **Source**: [the cleanup planner's remote-branch section](../../../automation/workspace/cleanup.py)
- **Blocks**: nothing. The planner already lists the pile; only the emitted
  deletion block waits on this.
- **Default path**: the planner LISTS every cached remote branch with the
  reasons it is not a candidate (`--remote-branches`) and emits nothing. No
  remote branch is deleted, no command that would delete one is written into
  the script, and the tool's only network call stays `git fetch --prune origin`.
- **Cost if wrong**: data
- **Safe to merge because**: nothing is written outside the repository and
  nothing outward is reached. The default path adds one read-only section to a
  report and one key to `local/workspace/cleanup-<run>.json`, both of which are
  git-ignored scratch. Undo is deleting the section; there is no state to
  revert.

## Background

Seventeen merged branches sit on this repository's remote right now. Until
today the cleanup planner could not see them at all: `classify` skipped every
ref whose scope is `R`, so a plan whose whole purpose is "stop things
accumulating" mentioned none of the seventeen things that had accumulated. That
reporting gap is now closed — `--remote-branches` lists them, with each one's
containment verdict against the fetched base.

What is NOT done is deleting them, and there are two independent reasons.

**1. This repository has already been burned by exactly this.**
`skills/github-workflow/reference.md` records incident `#136`: a base branch was
deleted, and GitHub CLOSED the pull request stacked above it one second later
(`base_ref_deleted` 21:05:08, `closed` 21:05:09; reopened only after the branch
was restored). It also made the rewritten commits unreachable, degrading
review-ledger rows from "EXISTS but is NOT an ancestor" to "UNKNOWN OBJECT" in a
fresh clone. That document's rule is "never `--delete-branch`", and
`merge_stack.py` rejects the flag at argument parsing. A planner emitting remote
deletions would be writing, into a script, the command the handbook forbids.

**2. The precondition that would make it safe needs a network call this tool
does not make.** "No OPEN pull request names this branch as its head OR as its
base" cannot be answered from a git ref. It needs the GitHub API
(`gh api repos/{owner}/{repo}/commits/<sha>/pulls`, or a PR listing). This
planner makes exactly ONE network call — `git fetch --prune origin` — and that
is load-bearing: it is why a dry run is genuinely read-only and why the tool can
be trusted to run unattended. Adding a second one is a change in what the tool
IS, not a feature toggle.

If the answer is yes, the shape is already worked out and the ordering matters:
push an `archive/<slug>-<sha>` tag FIRST and verify it landed, THEN delete with
`git push origin --force-with-lease=refs/heads/<b>:<sha> :refs/heads/<b>` —
never a plain `--delete`, which succeeds unconditionally and would silently
discard a commit somebody pushed between the plan and the run. Not `--atomic`
across the batch either: one stale lease would abort all seventeen.

## Options

The axis is reach against recoverability: how much of the cleanup the tool can
finish on its own, against how far its blast radius extends past this machine.

### Option A — listing only (the default path)

The planner reports the pile and stops. Deleting a remote branch stays something
the owner does deliberately, in the GitHub UI or with `gh`, one at a time.

***Example consequence:*** you run the planner, see "17 cached · 16 contained by
the base", pass `--remote-branches`, read the sixteen names, and delete the ones
you want on github.com. The tool never surprises you, and the seventeen branches
are still there next month if you do not.

### Option B — plan them into the emitted script, still deleting nothing itself

The planner adds a `gh` call to find open PRs, drops any branch named as a head
or a base, and writes an archive-tag-then-`--force-with-lease` block into
`local/workspace/cleanup-<run>.sh`. The tool still deletes nothing; the script
you read and run does. Where `gh` is absent or unauthenticated, every remote
branch is kept.

***Example consequence:*** you read the script, see sixteen tag-then-delete
pairs, run it, and sixteen branches disappear from github.com in one go — along
with, on a bad day, the base of a PR you had open on another machine, which
GitHub closes one second later. The lease and the PR check are what stand
between you and that; the lease is solid, the PR check is only as fresh as the
moment the plan was written.

## Recommendation

**Option A.** The reporting gap was the actual complaint — the pile was
invisible — and listing closes it at zero risk. Option B buys you one command
instead of sixteen clicks, and pays for it with a second network dependency, a
blast radius that extends to a shared server, and a script carrying the exact
verb this repository's own handbook says never to run. Sixteen clicks, once, is
not the bottleneck; branches piling up unnoticed was.

**Strongest case against this:** the same argument was available for local
branches and would have been wrong there. The owner's complaint is that cleanup
is manual, and a tool that reports sixteen branches and then makes you delete
them by hand has moved the work rather than removed it — which is precisely
what the harness-worktree rule did before it was fixed, and it took an operator
running eleven prohibited `git worktree remove` calls outside the plan to
surface that. A listing nobody acts on may simply relocate the same failure to
github.com.

**Confidence:** medium — I verified incident #136 in
`skills/github-workflow/reference.md`, verified that the seventeen branches are
real and all contained by the fetched base, and verified that the listing costs
no network call beyond the fetch. I did NOT test any `gh` PR-lookup path, did
not measure how often a stale PR check would actually catch something, and have
not asked whether you delete these branches on GitHub already.

**Your answer:** ______
