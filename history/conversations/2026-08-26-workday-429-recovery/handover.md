# Handover — workday-429-recovery

- **Date**: 2026-08-26
- **Task(s)**: 2026-08-20-workday-detail-429-recovery

The Workday recovery change is complete on an isolated branch; nothing is half-done
or known broken, and no owner action is required before review.

## What happened

- Workday detail fetching now slows one tenant at a time and retries only missing
  posting details; before, an eight-request burst could lose most of a board to 429.
- Seconds and HTTP-date retry hints are capped at 10 seconds; before, the HTTP layer
  neither honored them nor protected the run from a hostile value.
- Persistent misses remain visible as `coverage=incomplete` evidence in the snapshot;
  before, the warning was durable but recovery did not exist.
- Response-read exceptions are isolated to one posting path, retried finitely, and
  cannot erase sibling rows that were already recovered.
- All 10 recovery tests, all 28 intake tests, all 829 job-search tests, and all 12
  required impacted gates passed after the independent-review repair.

## Where things stand

- Task `2026-08-20-workday-detail-429-recovery` is in review on branch
  `codex/issue-235-workday-429-recovery` and PR #372 targets `main`.

## Decisions made for you

- One sequential detail stream per tenant was chosen over sleeping eight inner
  workers; undoing it restores faster bursts and the observed rate-limit loss.
- Two recovery rounds, a 250 ms request-start interval, and a 10-second retry ceiling
  were chosen as finite defaults; changing them is a local constant edit but needs a
  live-tenant measurement.
- Generic HTTP retry behavior and snapshot schemas were left unchanged; undoing this
  boundary would couple unrelated sources and require broader compatibility review.

## If X then Y

- If live tenants still return persistent 429s, tune the three Workday constants from
  measured response data; do not add a process-global limiter or unbounded retries.
- If the 15-second minimum for 60 details is too slow, add a small tenant-local
  concurrency budget only with a test that proves it does not recreate bursts.

## Dead ends

- Generic 429 sleeps, eight sleeping retry workers, global tenant coupling, unlimited
  provider delays, and full-source reruns were rejected in the task design because
  they either spread the behavior or repeat already-successful work.

## Needs your attention

- Nothing from this task. The top-level issue-resolution session owns any pre-existing
  repository-wide `needs-human` items.
