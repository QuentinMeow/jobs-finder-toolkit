# Should the public repository history be rewritten for privacy?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-30
- **Source**: [runtime skill adapters task](../../../tasks/4_done/2026-07-30-runtime-skill-adapters/task.md)
- **Blocking**: nothing. The non-destructive runtime fix and current-tree cleanup proceed.
- **Default path**: keep published history unchanged; prevent the identifiers from
  appearing in the current tree, future commits, branch name, commit messages, and PR text.

## Background

The public repository already contains overlay-only skill identifiers in older
commits. Removing them from the current tracked tree necessarily leaves the old
objects in Git history and shows the removed lines in the cleanup diff. A normal
pull request cannot erase either surface.

Erasing those objects requires rewriting published history and force-pushing the
default branch. That invalidates commit IDs, disrupts open branches and pull
requests, and requires every existing clone to re-clone or repair its history.
It is materially more destructive than the runtime fix and should not be inferred
from a request to create a PR.

## Options

### Option A — keep history unchanged (recommended)

Merge the current-tree cleanup and dynamic local adapter workflow. Existing
historical objects remain reachable, but no identifier is stored in the new
tracked snapshot or future adapter configuration. This is safe for every clone
and preserves all existing commit and PR references.

### Option B — coordinate a full history rewrite

Plan a separate maintenance window, inventory branches/tags/releases, rewrite
every affected ref, force-push, invalidate or rebuild open PRs, and tell all
collaborators to re-clone. This gives the strongest removal but causes repository-
wide disruption and still cannot retract copies already fetched or cached.

## Recommendation

Choose Option A unless the identifiers themselves are sensitive enough to justify
invalidating the repository's published history. The current fix closes the
ongoing leak path; a history rewrite is high-cost, cannot recall existing clones,
and should be a separately approved operation with a rollback and communication
plan.

**Your answer:** ______
