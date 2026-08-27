# Require primary occupation evidence in specialized searches

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GitHub issues #267 and #274, combined because both expose the same title-gate defect
- **Claimed-by**: occupation-evidence implementation agent

## Goal

Keep broad supporting words from establishing a specialized occupation on their own. Clear target-family titles remain normal matches; generic or adjacent titles stay recoverable in the bounded review lane instead of being promoted to the main shortlist.

## Context

The title gate currently treats most candidate-authored include terms as clean occupation evidence. That lets words such as `application`, `automation`, `performance`, and `quality` promote security, backend, business-workflow, customer-support, and manufacturing roles that are outside the intended occupation. Expanding the closed `_BROAD_DOMAIN_TOKENS` list would fix only today's examples and would repeat the same failure for the next broad word.

The implementation must be generic and profile-owned: read the primary boundary from an explicit profile declaration instead of inferring an occupation taxonomy, preserve exact target-family titles, preserve the user's explicit excludes and include-only candidates, and send uncertainty to review rather than introducing a new hard drop. Freeze positive and negative controls for mobile/application-platform, SDET/QA, business automation, backend performance, customer and manufacturing quality, AI automation, gameplay/graphics, robotics/autonomy, technical writing, compiler/toolchain, database/storage, and software engineering management.

## Definition of done

- A design records the need, rejected keyword-list alternative, consequences, rollback rule, and frozen before/after matrix.
- The public corpus and focused tests prove broad supporting words cannot create a main-list occupation match by themselves.
- Explicit target-family titles declared as primary retain their main-list disposition; every candidate-authored include remains kept unless an existing harder rule rejects it.
- The full job-search suite, corpus validator, config-less impact gates, review ledger, reconciler, and pre-commit checks pass with recorded exit codes.
- The completed branch is independently reviewed before publication; issues #267 and #274 remain separate GitHub records but share one coherent code change.

## Human questions / additional tasks

None.
