# Handover — workspace-lifecycle-round-2

- **Date**: 2026-08-22
- **Task(s)**: 2026-08-22-the-shared-suite-is-red-for-the-owner-and-green-for-every-agent
  (filed); 2026-08-20-cleanup-script-rechecks-nothing-at-run-time (closed, `3_in-review`)

## What happened

- Nothing is on fire, but two things are half-done by design and one is stale.
  The primary checkout **cannot fast-forward** — a concurrent session holds uncommitted
  edits to `automation/gates/run_gates.py` — so local `main` sits behind `origin/main`.
  That is the exact case the new post-merge cutover refuses on, and it refuses correctly.
- The owner reported that branches and worktrees still accumulated after the previous
  round shipped. They were right, and the cause was not the tooling being absent — the
  dashboard is mandated as every session's first command and was read on 100% of sessions
  while the outcome never moved. At the moment cleanup becomes possible, no process is
  running: the agent's session ends AT the merge, and cleanup needs the merge visible in
  `origin/main`, which needs a fetch nobody performs.
- Five PRs merged (#357–#361). The action now happens in `merge_stack.py`, the one process
  alive at that moment, which already holds a confirmed 204.

## Where things stand

- Merged: #357 post-merge cutover, #358 dashboard truth + overlay privacy, #359 cleanup
  evidence + destructive-defect fixes, #360 gate-runner honesty, #361 a history correction.
- Verified against the REAL repository, not a fixture: the planner now says `RETIRE` for
  both orphan harness worktrees and `PROPOSE` for `fix/cleanup-worktree-gaps`, while the
  four live agent branches stay `keep`. The overlay section leaked 7 exact private strings
  before and leaks 0 after.
- The 17 stale remote branches are LISTED with verdicts and nothing is emitted. Deleting
  them is unanswered — see "Needs your attention".

## Decisions made for you

- **Remote branches are listed, never deleted.** `delete_branch_on_merge` stays off:
  `skills/github-workflow/SKILL.md:255` documents it and incident `#136` shows deleting a
  base branch closed the PR above it one second later. Undoing the listing is deleting one
  report section. Recorded in `message-queue/needs-human/decisions/plan-remote-branch-retirement.md`.
- **A detached worktree is now judged by evidence, not by the absence of a branch.** The old
  rule was an unconditional keep, and every harness worktree is detached by construction, so
  it fired on 100% of them forever. Evidence is containment in the fetched base plus the
  per-worktree reflog. Reversing it is one `keep_reasons.append`.
- **Private-overlay branch names print as ordinals (`codex/#2`), via an allowlist.** A
  blocklist would have to enumerate every employer — that list IS the private data, and it
  fails open. A hash of a low-entropy name is confirmable by guessing.
- **A non-zero `merge-tree` exit is now `unknown`, not `merged`.** It previously read as
  merged whenever git resolved a conflict by keeping "ours" — binary files, `-merge`
  gitattributes, submodule pointers. 22 tracked files here contain NUL bytes.

## If X then Y

- **If local `main` is still behind:** the cause is the concurrent session's uncommitted
  `run_gates.py`, not the cutover. `git -C <repo> merge --ff-only origin/main` refuses while
  those edits are unstaged. Commit or stash them, then it fast-forwards.
- **If a gate looks red in your checkout but green in a PR:** check `private/` first, not the
  diff. The suite aborts during collection in the primary checkout and passes 871 tests in
  any worktree. That is the filed task above, and it is the likeliest explanation.
- **If the planner proposes something surprising:** read the emitted script, not the report.
  The script re-checks every precondition at run time and records a refusal rather than
  aborting the run, so a stale plan degrades to "nothing happened", not to damage.

## Dead ends

- **Turning on `delete_branch_on_merge`** — abandoned after finding the documented decision
  against it and the `#136` timeline. It also would not touch the existing 17.
- **`git push origin --delete`** — measured to succeed unconditionally and lose commits raced
  in after planning. `--force-with-lease=refs/heads/<b>:<sha>` refuses a stale lease; `--atomic`
  across the batch lets ONE stale lease abort all 17.
- **A `BEHIND n` banner as the primary fix** — rejected by its own author's self-attack: this
  repo merged 88 commits in 18 hours, so it would be red daily and ignored within a week.
  Staleness is keyed on cache age instead, and the ACTION was made primary.
- **Filing a decision in an uncommitted worktree file** — done by me, and it existed in no
  ref, so the agent that needed it could not see it and filed its own. Same failure as
  recording an ask only in a handover, one layer up.

## Needs your attention

- [`plan-remote-branch-retirement.md`](../../../message-queue/needs-human/decisions/plan-remote-branch-retirement.md)
  — may the planner ever WRITE a remote deletion? *Why this matters:* 17 merged branches sit
  on GitHub and the tool can see them but not act. *If you do nothing:* they stay, the planner
  keeps listing them, and nothing is deleted — the default path is already shipped.
- [`2026-08-22-the-shared-suite-is-red-for-the-owner-and-green-for-every-agent`](../../../tasks/0_backlog/2026-08-22-the-shared-suite-is-red-for-the-owner-and-green-for-every-agent/task.md)
  — *Why this matters:* you and every agent get opposite answers from the same test command.
  *If you do nothing:* agents keep reporting green from worktrees while your checkout cannot
  run the suite at all. Restoring `config.yaml` fixes YOUR machine today; the task is about
  the next fresh clone.
- `1 pending · top: plan-remote-branch-retirement — 17 merged remote branches stay until you answer`
