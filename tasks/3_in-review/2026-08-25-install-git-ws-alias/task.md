# Install the workspace dashboard alias in every checkout

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: Owner report in the 2026-08-25 session that `git ws` works on only one laptop
- **Claimed-by**: Codex

## Goal

Make the repository-local `git ws` shorthand available after the tracked checkout bootstrap runs, instead of depending on an alias that exists only in one laptop's `.git/config`.

## Context

The dashboard script itself was merged in PR #338 and is available at `automation/workspace/status.py`. The shorthand was configured manually with `alias.ws` in one checkout's local Git configuration, which Git never clones. `automation/bootstrap_overlay.py` is the existing idempotent setup command for repository-local Git metadata and must preserve a conflicting user-owned alias rather than overwrite it.

## Definition of done

- Bootstrap apply installs the expected repository-local `alias.ws` when it is missing.
- Bootstrap check reports a missing or conflicting alias without changing it.
- Bootstrap preserves a conflicting user-owned alias.
- Focused tests and the repository's pre-PR gates pass.
- A public PR explains that the dashboard existed before but its shorthand did not travel between devices.
