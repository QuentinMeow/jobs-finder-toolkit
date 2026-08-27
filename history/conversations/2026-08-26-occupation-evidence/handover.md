# Handover — occupation-evidence

- **Date**: 2026-08-26
- **Task(s)**: 2026-08-26-issues-267-274-occupation-evidence

## What happened

- Nothing is blocked and no code is half-finished. Issues #267 and #274 now share one review-ready classifier change.
- A specialized search profile can declare `titles.primary`, the title phrases that establish its occupation. Before, broad include words could put adjacent occupations on the main shortlist; now an include-only title stays recoverable in bounded review.
- The frozen public matrix changed 14 false main-lane verdicts to review while retaining all 10 target-family matches and introducing no hard drop.

## Where things stand

- The branch is ready for independent review and has not been pushed. Full job-search tests, the corpus validator, and config-less impacted gates passed.

## Decisions made for you

- Primary evidence is profile-owned and opt-in; guessing from a global keyword list was rejected because the same word can be broad for one occupation and primary for another.
- Missing primary evidence routes to review, never rejection; undoing this changes one title-gate branch and requires no data migration.
- Primary evidence is title-only in this change. JD-body occupation proof needs a separate negation-aware design because one incidental mention already caused false positives.

## If X then Y

- If independent review finds target-family recall loss, remove `titles.primary` from the affected profile for immediate rollback and revert the implementation commit before publication.
- If a complete JD contradicts a target-looking title, keep it in manual review; this change does not claim title evidence proves body semantics.

## Dead ends

- Expanding `_BROAD_DOMAIN_TOKENS` was rejected because it fixes only known words and silently encodes candidate-specific intent in public code.
- Inferring primary terms from word count or the presence of `engineer` was rejected because it cannot separate the frozen positive and negative controls without becoming another hidden taxonomy.

## Needs your attention

- Nothing.
