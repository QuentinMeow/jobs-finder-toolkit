# Process folders: tasks/, known-issues/, design-decisions/, unresolved-decisions/

- **Status**: decided
- **Date**: 2026-07-20
- **Decided by**: owner (folders requested explicitly; layout details by agent within that mandate)

## Context

Work on this repo is done largely by agents across many sessions. Bugs,
tasks, and open design questions were scattered across GitHub issues, eval
result files' "follow-ups" sections, LESSONS.md entries, and session memory —
so each new session re-discovered them, and decisions needing the owner's
input had no single place the owner could read cold.

## Decision

Four root-level folders in the public repo, each holding one self-contained
file per item (formats defined in each folder's README):

- `tasks/` — actionable work items.
- `known-issues/` — bugs, canonical detailed record (GH issues link to these).
- `design-decisions/` — decided questions, ADR-style, append-only.
- `unresolved-decisions/` — questions awaiting the owner, each fully
  self-contained with options, recommendation, and a default path.

Because the public tree is leak-guarded, items naming real
companies/identity/dated personal facts live in same-format mirrors under the
private overlay: `private/tasks/`, `private/known-issues/`,
`private/unresolved-decisions/` (and `private/design-decisions/` when needed).

## Alternatives considered

- **GitHub issues only** — not self-contained offline, awkward for agents to
  write rich context into, and unavailable for private-overlay matters.
- **Single TODO.md / ISSUES.md files** — merge-conflict magnets across
  concurrent agent branches; one-file-per-item keeps PRs independent.
- **Folders under docs/** — these are working state, not documentation;
  root-level keeps them visible to the owner and to agents at boot.

## Consequences

- Eval-result "follow-ups" sections and session memory should now *file*
  items here instead of only mentioning them.
- Existing GH issues get a mirroring file; the file is canonical detail.
- Folder churn is intentional: resolved files are deleted after a PR cycle —
  git history is the archive.
