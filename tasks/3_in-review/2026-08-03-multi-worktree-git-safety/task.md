# Make Git automation safe across linked worktrees

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: Owner report and request on 2026-08-03
- **Claimed-by**: Codex

## Goal

Prevent repository automation in one linked worktree from moving, bypassing, or
silently weakening Git state and safety checks used by another worktree.

## Context

Branch cleanup advanced a shared local `main` ref without updating the worktree
that had `main` checked out. The follow-up audit also found hook installation,
push scanning, shared excludes, and recovery instructions that assumed a single
worktree. Work in this task must remain separate from the detached stress-test
worktree and must not repair the owner's primary checkout without approval.

## Definition of done

- Linked-worktree regression tests prove hook wiring and pushed-ref scanning use
  the correct immutable repository state.
- Shared adapter exclusions remain safe when worktrees have different overlays.
- Git workflow guidance identifies branch-owning worktrees and uses unique
  scratch worktree paths.
- Relevant focused tests, publication gates, and CI pass before merge.
