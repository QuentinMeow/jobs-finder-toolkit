# Handover — job-search identity and YOE integration

- **Date**: 2026-07-22
- **Task(s)**: 2026-07-22-registry-match-keys-exact-lookup-misses-name-variants

## What happened

- Rebased the local job-search work onto the latest `main` and migrated it
  through the AgentFold path/process restructure without dropping upstream
  schema-v5 or store changes.
- Added conservative company legal-suffix identity matching for skip logs and
  bounded YOE clause classification so adjacent requirements do not contaminate
  one another.
- Restored the previously untracked regression test and migrated the old task
  note into the current task package.

## Where things stand

- In review on `fix/job-search-identity-and-yoe-20260722`; focused regressions,
  full affected suites, corpus validation, vendoring, reconciliation, and the
  public leak guard pass.

## Needs your attention

- [`logs-as-store-projections`](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  remains parked until raw-data-layer stage 3 has run for a few weeks; no action
  is needed for this PR.
