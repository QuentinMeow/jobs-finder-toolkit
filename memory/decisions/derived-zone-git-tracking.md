# Keep the datastore's derived zone out of git

- **Status**: decided
- **Date**: 2026-07-22
- **Decided by**: owner
- **Supersedes**: the derived-zone part of decision 1 in
  [raw-data-layer-decisions.md](raw-data-layer-decisions.md)

## Context

The first raw-data-layer sign-off assumed `derived/` would remain a small
zone worth tracking beside `index/`, `annotations/`, and `state/`. The real
jobs build disproved that assumption: the regenerable zone grew to roughly
225 MB across about 44,000 files, dominated by verbatim JD text, and it
churns broadly on rebuild.

## Decision

Do not git-track `data/*/derived/`. Continue tracking the small `index/`,
`annotations/`, and `state/` zones in the private overlay; continue
ignoring `raw/`.

## Consequences

- Git history stays small and does not preserve wholesale cache rewrites.
- Human judgments and operational state still have offsite history.
- Recovering `derived/` requires rebuilding it from locally available raw;
  the existing `not-synced-here` behavior remains important on machines
  without every blob.
- The already-active private `.gitignore` policy is ratified; no runtime
  implementation change is required.
