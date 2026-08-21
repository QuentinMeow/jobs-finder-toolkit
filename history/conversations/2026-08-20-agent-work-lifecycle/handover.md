# Handover — agent work lifecycle

- **Date**: 2026-08-20
- **Task(s)**: none filed; work was owner-directed in session

## What happened

- **Nothing is on fire, but two things want your eye:** `config.yaml` is missing while the private
  overlay is mounted, so the local leak guard cannot arm and `pre-push` refuses; and one
  concurrent session still holds the main checkout on `codex/remove-subagent-count-limits`.
- Ten PRs merged (#340–#349), 25 issues closed, 69 open issues down to 44. The workspace dashboard
  now reports what each branch is for and what state its work is in, and a cleanup planner proposes
  retirements without ever performing them. Full detail in `summary.md` beside this file.

## Where things stand

- Merged: #340–#349. Two issue clusters were still running when this was written — JD metadata
  extraction and the filter-pipeline reports — on branches `fix/jd-metadata-extraction` and
  `fix/filter-pipeline-reports`.
- Cleanup done: 11 backup refs written under `refs/agent-trash/20260821T034231Z/`, 8 orphan
  scaffold branches deleted, 4 refused by `git branch -d` because their agents were still running.
  Nothing was overridden.

## Decisions made for you

- **Both full designs were rejected** in favour of roughly a quarter of the code. The binding reason
  is that `message-queue/needs-human/decisions/process-weight-what-to-cut.md` is open and its
  default path says no new gate is added while it is. Undoing this means re-reading `DESIGN-A.md`
  and `DESIGN-B.md`, which were not committed — they were session scratch.
- **Branch intent uses `git branch --edit-description`**, not a new record type. Reversing it costs
  nothing; nothing depends on the descriptions existing.
- **Merge detection is `git merge-tree` content containment**, not `git branch --merged`. This is
  load-bearing: the standard test misses squash-merges, and `patch-id` ignores whitespace, so both
  can call unique work merged. Reverting would reintroduce a data-loss path.
- **Pushes used `JOBHUNT_ALLOW_PUSH=1`** with a local token-independent leak scan on each outgoing
  tree first. You approved this in session after establishing that Codex pushes from a clone with
  no hooks at all, so CI's armed guard has been the enforcing gate all along. Restoring
  `config.yaml` removes the need.
- **`git branch -d`, never `-D`**, and `mv` rather than `rm`. A refusal is reported as a finding.

## If X then Y

- **If a future cleanup run proposes a worktree you did not expect**, read the emitted script before
  running it — that is exactly how the repo-root move was caught. The script is written to
  `local/workspace/cleanup-<run-id>.sh` and the planner never executes it.
- **If a PR suddenly conflicts and you did nothing**, it is `automation/publish/review_ledger.yaml`.
  Merging any PR re-dirties every other open PR. Resolve by byte-level append of the authored rows,
  never a line union and never a YAML round-trip — the round-trip reformats all 351 historical rows.
- **If `git branch --merged` says a branch is merged, do not trust it for deletion.** During this
  session it labelled a branch merged whose agent was still working, because the branch had no
  commits yet so its tip equalled `main`.
- **If the workspace suite feels slow**, that is expected: `tests-workspace` went from ~2.4s to ~65s
  because it builds real multi-worktree repositories rather than mocking git.

## Dead ends

- **A YAML round-trip to resolve the review ledger.** It parsed and re-dumped correctly and the gate
  accepted it, but it rewrote every historical row — 1,986 insertions to append 3. Discarded for a
  byte-level append.
- **In-place markers to hide surnames in leak-guard fixtures.** Brackets, case humps and underscores
  all *create* the word boundary the matcher looks for, so `ag[reed]` is a hit where `agreed` is not.
  Split literals are the only marking that survives.
- **Caching `assess_location` itself** to fix its 26,114 calls. The two call sites pass different
  policies and titles, so a cache on the function collapses nothing; the shared work is the text.
- **Instructing agents to use `python3`.** That interpreter lacks the repo's dependencies and
  produces misleading import errors. Use `.venv/bin/python`.

## Needs your attention

- **`delete_branch_on_merge` on the GitHub repo** — currently `false`. Turning it on permanently ends
  the remote half of the branch-litter problem. *If you do nothing:* every merged PR keeps leaving a
  remote branch behind, and the planner has more to propose each week.
- **`config.yaml` is absent while `private/` is mounted** — the leak guard cannot arm, so `pre-push`
  refuses and every push needs an override. *If you do nothing:* agents keep pushing with the
  override and CI remains the only armed check.
- **`message-queue/needs-human/decisions/process-weight-what-to-cut.md`** — still open, and it shaped
  this whole design. *If you do nothing:* no new gate can be added, which is the constraint that
  kept this change small.
- **`message-queue/needs-human/decisions/store-gc-execute-agent-runnable-or-owner-only.md`** — still
  open. *If you do nothing:* the cleanup planner stays plan-only, which is the safe default.
