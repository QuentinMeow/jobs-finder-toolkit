# Show public and private Git work at a glance

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: Owner request in the 2026-08-20 session
- **Claimed-by**: Codex

## Goal

Add one short, read-only repository command that summarizes the public toolkit
repository and its optional private overlay. Its normal output must be one
decision-oriented line covering checkout sync, dirty worktrees, and local work
branches; verbose mode must expose the full local/cached-remote inventory and
underlying file and commit detail without contacting a remote.

## Context

The owner currently has to combine several Git commands in both repositories to
see uncommitted work, linked worktrees, branch locality, upstream divergence,
and whether a branch is already merged into `main`. The entry point must identify
this toolkit from its own location, work when invoked from another directory,
omit a missing private overlay, and refuse an unrelated copied script.

## Definition of done

- [x] A short executable entry point renders both repositories, omitting an
      absent private overlay, and offers one-line and verbose modes.
- [x] The default is exactly one actionable line and does not mix cached
      remote-only refs into the local-work count.
- [x] Verbose mode shows every registered worktree and local/cached-remote
      branch, with dirty/upstream/merged state represented accurately.
- [x] Automated tests cover clean, dirty, untracked, local-only, remote-only,
      merged, unmerged, detached-worktree, no-overlay, and outside-CWD behavior.
- [x] Focused tests and the applicable repository gates pass.
- [x] The root agent contract requires this dashboard as the first Git-state
      overview, so routine agent work does not silently omit the private repo.
