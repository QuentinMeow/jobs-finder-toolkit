# Handover — workspace-git-status

- **Date**: 2026-08-20
- **Task(s)**: 2026-08-20-workspace-git-status-command

## What happened

- Nothing is broken or half-implemented. The toolkit now has one read-only Git
  dashboard for the public repository and its optional private overlay.
- Compact output lists every worktree and branch; `-v` expands files, commits,
  upstreams, remote URLs, and worktree flags. Cached remote state is labeled and
  the command never fetches.
- The root agent contract now requires this dashboard before narrower Git-state
  inspection, preventing routine work from silently checking only the public
  repository. Fresh clones use the tracked script; `git ws` is an optional
  repository-local shorthand.
- All 21 selected implementation gates passed. The agent-contract follow-up
  passed the live two-repository check and strict instruction budget; final
  CI-equivalent evidence belongs in the PR at its published tip.

## Where things stand

- Implementation commit `736c240` is on `codex/workspace-status`; task
  `2026-08-20-workspace-git-status-command` is ready for review with the
  required-agent-preflight follow-up included.

## Decisions made for you

- Used `automation/workspace/status.py` as the entry point so the command stays
  inside this repo's purpose-named tooling tree; moving it would cost one docs
  update and no data migration.
- Kept compact mode complete, not truncated; verbose mode adds evidence. Remote
  refs are cached-only because fetching would make a status command networked.
- A copied script refuses unrelated repositories using four toolkit markers;
  the optional `private/` section disappears when that path is not its own repo.
- The portable script path, not the untracked `git ws` alias, is the enforced
  agent command; changing that would require only this contract paragraph.

## If X then Y

- If no local `main` or cached `origin/main` exists, branch rows say `main
  missing` instead of guessing merge state.

## Dead ends

- The first implementation commit was refused because public export omitted the
  new folder. `automation/workspace/` now ships, and the export suite pins it.

## Needs your attention

- No new question came from this task. The pre-existing owner queue remains
  unrelated: 44 items total; top is [search/draft `us_only` default
  asymmetry](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md)
  because an omitted key can repeatedly surface roles that the draft gate later
  rejects. If you do nothing, the documented split defaults remain unchanged.
