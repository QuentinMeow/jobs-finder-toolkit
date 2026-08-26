# Refresh main and clean finished agent branches around GitHub work

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: Owner request in the 2026-08-25 session
- **Claimed-by**: Codex

## Goal

Make every GitHub workflow attempt to refresh local `main`, resolve in-scope conflicts safely,
and retire finished local `codex/` and `claude/` branches or worktrees without losing unique work.
Clean the currently eligible local agent branches and worktrees.

## Context

The public and private repositories may each have their own `main`, branches, and worktrees. The
existing owner decision allows post-merge branch sweeps only after fresh exact-tree containment
and open-PR dependency checks; remote deletion stays disabled because deleting a stacked base
branch can close its child PR. `automation/workspace/cleanup.py` provides the recoverable worktree
path and re-checks its preconditions when the emitted script runs.

## Definition of done

- Both repositories have attempted a fast-forward pull of `origin/main`.
- Every local `codex/` or `claude/` branch/worktree is either safely retired or reported with its
  keep reason.
- `github-workflow` carries the mandatory pre/post GitHub refresh and cleanup routine, and
  `gardener` routes active GitHub cleanup to it without making its report mutate state.
- Relevant skill validation, canary evaluation, and repository gates pass before merge.
