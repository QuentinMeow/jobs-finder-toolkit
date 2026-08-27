# Handover — occupation-evidence

- **Date**: 2026-08-27
- **Task(s)**: 2026-08-26-issues-267-274-occupation-evidence

## What happened

- Nothing is blocked and no code is half-finished. Issues #267 and #274 now share one review-ready classifier change repaired after independent review.
- A specialized search profile can declare `titles.primary`, the title phrases that establish its occupation. Before, broad include words could put adjacent occupations on the main shortlist; now an include-only title stays recoverable in bounded review.
- The expanded frozen public matrix has 31 titles. It retains all 12 target-family matches, routes all 17 adjacent controls to review, and keeps two hard drops only where an iOS-only profile explicitly excludes Android and React Native. The broad mobile profile still matches both platforms.
- Every successful primary match now records which primary phrase admitted it. Absent/empty primary configuration remains behavior-compatible, and the full pipeline's explicit word-filter rescue remains review-only.

## Where things stand

- The branch is ready for fresh independent review and has not been pushed. It depends on
  `codex/issue-234-manager-product-corpus` at
  `67a0375f012e7ef579482de5b0272d4ec13bb0b2`, the head of open PR #371. Publish
  it with that branch as its base while #371 remains open; rebase onto `main` only after #371
  merges. Verification figures below are refreshed in the task record after this repair.

## Decisions made for you

- Primary evidence is profile-owned and opt-in; guessing from a global keyword list was rejected because the same word can be broad for one occupation and primary for another.
- Primary declarations use occupation-bearing phrases rather than raw domain tokens. A broad declaration can still be misconfigured; enforcing semantics in generic code would recreate the rejected taxonomy.
- Missing primary evidence routes to review, never rejection; undoing this changes one title-gate branch and requires no data migration.
- Explicit `titles.exclude` remains decisive: the iOS-only controls drop Android and React
  Native even though the broad mobile profile deliberately retains both as target families.
- Primary evidence is title-only in this change. JD-body occupation proof needs a separate negation-aware design because one incidental mention already caused false positives.

## If X then Y

- If independent review finds target-family recall loss, remove `titles.primary` from the affected profile for immediate rollback and revert the implementation commit before publication.
- If a complete JD contradicts a target-looking title, keep it in manual review; this change does not claim title evidence proves body semantics.

## Dead ends

- Expanding `_BROAD_DOMAIN_TOKENS` was rejected because it fixes only known words and silently encodes candidate-specific intent in public code.
- Inferring primary terms from word count or the presence of `engineer` was rejected because it cannot separate the frozen positive and negative controls without becoming another hidden taxonomy.

## Needs your attention

- Nothing.
