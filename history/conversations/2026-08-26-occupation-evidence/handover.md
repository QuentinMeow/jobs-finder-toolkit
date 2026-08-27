# Handover — occupation-evidence

- **Date**: 2026-08-27
- **Task(s)**: 2026-08-26-issues-267-274-occupation-evidence

## What happened

- Nothing is blocked and no code is half-finished. Issues #267 and #274 now share one review-ready classifier change repaired after independent review.
- A specialized search profile can declare `titles.primary`, the title phrases that establish its occupation. Before, broad include words could put adjacent occupations on the main shortlist; now an include-only title stays recoverable in bounded review.
- The expanded frozen public matrix has 29 titles. It retains all 12 target-family matches, routes all 17 adjacent controls to review, and introduces no hard drop. Mobile Mechanic and Mobile Sales Representative are now explicit negative controls; Android and React Native are explicit recall controls.
- Every successful primary match now records which primary phrase admitted it. Absent/empty primary configuration remains behavior-compatible, and the full pipeline's explicit word-filter rescue remains review-only.

## Where things stand

- The branch is ready for fresh independent review and has not been pushed. All 827 job-search tests, the 185-case corpus validator, and all 12 config-less impact-selected gates passed after the repair.

## Decisions made for you

- Primary evidence is profile-owned and opt-in; guessing from a global keyword list was rejected because the same word can be broad for one occupation and primary for another.
- Primary declarations use occupation-bearing phrases rather than raw domain tokens. A broad declaration can still be misconfigured; enforcing semantics in generic code would recreate the rejected taxonomy.
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
