# Group the private overlay's personal artifacts below `me/`

- **Status**: decided
- **Date**: 2026-08-06
- **Decided by**: owner
- **Supersedes / Superseded-by**: supersedes the private-tree placement in [the workspace layout decision](workspace-layout-public-root-plus-review-gate.md) and [the company interview-material decision](interview-material-moves-by-company-only.md)

## Context

The private overlay was organized by lifetime: reusable candidate material under `me/`,
company knowledge under `companies/`, and per-requisition products under `applications/`.
The owner found that model harder to navigate because all three are parts of the same personal
job hunt, while profile, baseline, and tailoring files remained loose directly under `me/`.

An inventory found that the company folders contain interview and assessment preparation,
with two exceptions: the company identity index serves the entire pipeline, and one outreach
draft is application communication. It also found a re-created legacy `data/` root containing
newer unique store state, which cannot be safely archived as part of a folder-only change.

## Decision

Use a person-first private layout. Move applications to `me/applications/`, company interview
material to `me/interviews/companies/`, and loose candidate source files into `me/career/`.
Move shared and company-specific outreach copy to `me/career/communications/`. Keep only
directories immediately below `me/`.

Move the cross-workflow company identity index to `market/company-index.yaml`. Keep the
toolkit's operational, market, skill, evaluation, documentation, and process roots at the
overlay root. Preserve the divergent `data/` root in place until a separate store-aware task
reconciles it.

## Alternatives considered

- Keep the lifetime-first roots — rejected because it is the navigation problem the owner
  explicitly asked to remove.
- Move the entire company tree under interviews — rejected because the identity index and
  outreach draft have demonstrably different consumers and purposes.
- Put every private root below `me/` — rejected because stores, market scans, skills, evals,
  and process state operate the toolkit; they are not artifacts the owner reads or submits.
- Archive or nest the legacy `data/` root now — rejected because it contains unique newer
  state and moving it would disguise an unresolved split-brain writer.

## Consequences

- Personal navigation has three stable entry points: career, applications, and interviews.
- Real configs must set `overlay_root` explicitly when applications live below `me/`; benchmark
  configs retain the old derived behavior for write isolation.
- Public examples and current documentation mirror the new shape; dated records retain old
  paths as history.
- The public toolkit PR must land before the private data-move PR, with the ignored real config
  updated only at cutover.
- Revisit only if company folders begin carrying durable non-interview knowledge; that would
  justify splitting company facts from company interview prep rather than restoring a generic
  top-level company bucket.
