# Move the coding interview screenshot inbox into personal practice

- **Status**: decided
- **Date**: 2026-07-30
- **Decided by**: owner
- **Supersedes / Superseded-by**: resolves the screenshot-inbox row in
  [the workspace-restructure execution plan](../../docs/designs/workspace-restructure/execution-plan.md#phase-5--the-lifetime-taxonomy-inside-private)

## Context

The workspace restructure moved durable interview material into either personal
interview knowledge or company-owned folders. Its untracked screenshot inbox
temporarily remained under the retired interview tree to preserve the owner's
drag-and-drop habit during the migration. That exception left a two-level legacy
husk and made the old taxonomy appear partly active.

Two private consumers poll the inbox before routing processed evidence into a
durable problem folder. Both consumers were already maintained together, so
changing their polling path was small and directly verifiable.

## Decision

Move the inbox to `private/me/interviews/practice/TODO/`. This is the personal,
pre-routing home for coding interview screenshots; company-specific durable
material continues to live under `private/companies/<key>/coding/`.

The existing inbox moved intact, and both private consumers now poll the new
location.

## Alternatives considered

- **Keep the inbox under the retired interview tree.** Lost because it preserved
  a misleading legacy root solely for one untracked folder.
- **Leave a compatibility symlink at the old location.** Lost because the
  restructure deliberately removed inbound symlinks; a shortcut would make the
  authoritative location ambiguous again.

## Consequences

- New screenshots go to `private/me/interviews/practice/TODO/`.
- Processing can still route durable output to a company coding folder without
  treating unclassified input as company-owned.
- Existing Finder shortcuts or shell aliases to the former inbox must be updated.
- Revisit only if the personal practice taxonomy changes or the inbox becomes a
  configured path shared by more consumers.
