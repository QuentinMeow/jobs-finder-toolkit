# Handover — CI and PR latency

- **Date**: 2026-08-03
- **Task(s)**: 2026-08-03-reduce-pr-ci-and-stack-latency

## What happened

- Nothing is broken on `main`: PRs #266 and #270 are green, while probe PR #275 now carries a stacked-base classifier fix found by its first hosted run; merging awaits explicit owner authorization.
- Routine diffs now select owned test lanes, independent lanes run in parallel, body edits have a separate check, uncertain inputs fail closed to the full matrix, and a guarded one-request native-stack path is implemented.

## Where things stand

- The foundation and stack fast path are in review. PR #275's fix must pass its fail-closed full matrix, then a clean documentation-only tip will provide the policy-only hosted timing before the task moves to review.

## Decisions made for you

- Keep leak, credential, mail-safety, review, reconciliation, instruction-budget, and stable `build`/`pr-body` checks mandatory; weakening those guards would trade merge speed for irreversible risk.
- Route unknown and foundational changes to every lane, while known documentation/process records run policy-only; relaxing the fallback would make silent misses possible.
- Keep `unittest` for now because setup and real test work dominate discovery; switching frameworks would add churn before addressing the measured bottleneck.
- Require explicit complete prefixes, current green checks, and head pins for one-request atomic merges; ordinary stacks remain bottom-up.
- Require `build` and `pr-body` without strict base synchronization so a green stacked child does not rebuild solely because its parent reached `main`.

## If X then Y

- If the documentation-only tip exceeds 45 seconds, inspect policy dependency setup and link/review gates before changing test frameworks.
- If a stacked probe sees lower-rung files again, inspect the event base SHA and fetched base commit before changing path ownership.
- If GitHub does not treat the base-only skipped body job as satisfying the required context, keep bottom-up retargets manual and revise the workflow before merging #270.

## Dead ends

- Replacing `unittest` was rejected as the first move because hosted setup plus real suite work, not discovery, dominate the critical path.
- Executing the live merge plan was blocked because the request did not explicitly authorize irreversible merges into `main`; the dry run passed.

## Needs your attention

- Merge approval is needed for PRs #266 and #270 (and the documentation-only tip after it is green). Why this matters: live merge/retarget timing cannot be confirmed without changing `main`. If you do nothing: all improvements remain reviewable and green but unmerged.
- No new repository queue item was filed. The 32 pre-existing public items and 7 private-overlay items remain unchanged. Highest cost: [`job-search-us-only-default-asymmetry`](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md) — Why this matters: inconsistent defaults can repeatedly hide eligible remote roles. If you do nothing: the documented status quo remains and the recurring-loss risk continues.
