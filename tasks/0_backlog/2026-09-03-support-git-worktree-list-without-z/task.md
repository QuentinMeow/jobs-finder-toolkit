# Support Git worktree listings without `-z`

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: Workspace preflight failure on 2026-09-03
- **Claimed-by**: 

## Goal

Make the workspace status dashboard work on Git versions whose `git worktree list --porcelain` command does not support the `-z` option, without weakening parsing correctness on newer Git versions.

## Context

`./automation/workspace/status.py --no-color` exits 2 on the current macOS host because its Git reports `unknown switch 'z'` for `git worktree list --porcelain -z`. Direct repository checks remain available, but the required at-a-glance preflight cannot run on this host.

## Definition of done

- The dashboard detects or safely falls back when `git worktree list --porcelain -z` is unavailable.
- Tests cover both NUL-delimited output and the supported fallback format.
- `./automation/workspace/status.py --no-color` exits 0 on this host.

## Follow-up diagnosis

The failure depends on executable selection: a legacy Git 2.23 on PATH rejects `-z`, while the installed Git 2.50 supports it and the dashboard succeeds when that binary is selected. Prefer documenting and detecting the supported runtime before adding a parser fallback. No implementation change is included in this task record.
