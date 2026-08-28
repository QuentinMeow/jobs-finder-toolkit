# Require primary occupation evidence in specialized searches

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GitHub issues #267 and #274, combined because both expose the same title-gate defect
- **Claimed-by**: occupation-evidence implementation agent

## Goal

Keep broad supporting words from establishing a specialized occupation on their own. Clear target-family titles remain normal matches; generic or adjacent titles stay recoverable in the bounded review lane instead of being promoted to the main shortlist.

## Context

The title gate currently treats most candidate-authored include terms as clean occupation evidence. That lets words such as `application`, `automation`, `performance`, and `quality` promote security, backend, business-workflow, customer-support, and manufacturing roles that are outside the intended occupation. Expanding the closed `_BROAD_DOMAIN_TOKENS` list would fix only today's examples and would repeat the same failure for the next broad word.

The implementation must be generic and profile-owned: read the primary boundary from an explicit profile declaration instead of inferring an occupation taxonomy, preserve occupation-bearing target-family titles, preserve the user's explicit excludes and include-only candidates, and send uncertainty to review rather than introducing a new hard drop. Freeze positive and negative controls for iOS, Android, React Native, mobile mechanics and sales, SDET/QA, business automation, backend performance, customer and manufacturing quality, AI automation, gameplay/graphics, robotics/autonomy, technical writing, compiler/toolchain, database/storage, and software engineering management.

This branch depends on the manager-product corpus branch
`codex/issue-234-manager-product-corpus` at
`67a0375f012e7ef579482de5b0272d4ec13bb0b2`, published as PR #371. While PR #371
is open, this change must publish as a stacked PR with that branch as its base. It may
rebase onto `main` only after PR #371 merges.

## Definition of done

- A design records the need, rejected keyword-list alternative, consequences, rollback rule, and frozen before/after matrix.
- The public corpus and focused tests prove broad supporting words cannot create a main-list occupation match by themselves.
- Explicit target-family titles declared as primary retain their main-list disposition; every candidate-authored include remains kept unless an existing harder rule rejects it.
- A broad mobile profile keeps Android and React Native target matches, while an iOS-only
  profile's explicit Android and React Native exclusions remain hard `no_match` decisions.
- Main-list decisions record the matched primary phrase in both their rule identifiers and structured evidence.
- The full job-search suite, corpus validator, config-less impact gates, review ledger, reconciler, and pre-commit checks pass with recorded exit codes.
- The completed branch is independently reviewed before publication; issues #267 and #274 remain separate GitHub records but share one coherent code change.

## Human questions / additional tasks

None.
