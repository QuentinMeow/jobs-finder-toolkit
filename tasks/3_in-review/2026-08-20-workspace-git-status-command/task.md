# Show public and private Git work at a glance

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: Owner request in the 2026-08-20 session
- **Claimed-by**: Codex

## Goal

Add one short, read-only repository command that summarizes the public toolkit
repository and its optional private overlay. Its compact default must show all
worktrees and known local/cached-remote branches; a verbose mode must expose the
underlying file and commit detail without contacting a remote.

## Context

The owner currently has to combine several Git commands in both repositories to
see uncommitted work, linked worktrees, branch locality, upstream divergence,
and whether a branch is already merged into `main`. The entry point must identify
this toolkit from its own location, work when invoked from another directory,
omit a missing private overlay, and refuse an unrelated copied script.

## Definition of done

- [x] A short executable entry point renders both repositories, omitting an
      absent private overlay, and offers compact and verbose modes.
- [x] Every registered worktree and every local/cached-remote branch is shown,
      with dirty/upstream/merged state represented accurately.
- [x] Automated tests cover clean, dirty, untracked, local-only, remote-only,
      merged, unmerged, detached-worktree, no-overlay, and outside-CWD behavior.
- [x] Focused tests and the applicable repository gates pass.
