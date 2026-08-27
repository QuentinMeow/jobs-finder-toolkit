# Handover — issue-234-manager-product-corpus

- **Date**: 2026-08-26
- **Task(s)**: 2026-08-26-label-manager-product-filter-variant

## What happened

- Nothing is half-done or broken: issue #234 has a focused local fix ready for review.
- The filter-variant corpus now recognizes the existing manager-product review family, and the
  snapshot-audit regression proves `Software Engineer, Ads Manager` no longer appears as unknown.

## Where things stand

- Local branch `codex/issue-234-manager-product-corpus` is ready for independent review and PR
  creation; no GitHub state was mutated.

## Decisions made for you

- Kept production classification unchanged and taught only the audit corpus about the known
  signature; undoing this is a three-fixture rollback with no data migration.
- Pinned `Software Engineer (Manager Tools)` as an exclusion boundary and reused the existing true
  manager controls instead of adding duplicate cases.

## If X then Y

- If a future classifier change alters either boundary, the corpus check fails before the audit can
  silently accept the broader manager family.

## Dead ends

- A classifier change and a signature-hash whitelist were rejected because the defect is missing
  audit vocabulary, not runtime classification.

## Needs your attention

- No new issue-#234 owner decision. Existing repository-wide needs-human items were unchanged.
