# Workday detail bursts lose postings to repeated HTTP 429

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GitHub issue #235; deferred from the C9 sources/fetchers cluster
  (branch `fix/sources-and-fetchers`) because the fix belongs in
  `skills/job-search/scripts/common.py`, which another agent owned that session.
- **Claimed-by**: Codex workstream mapper (2026-08-26, branch `codex/issue-235-workday-429-recovery`)

## Goal

A default Stage-1 Workday fetch stops losing a large share of posting details to
HTTP 429. Detail requests are paced and retried per tenant, `Retry-After` is
honoured, and a board whose details were never fetched is not reported as fully
inspected.

## Context

`sources.fetch_workday` enumerates a Workday board's listing, then fetches each
posting's detail concurrently (`ThreadPoolExecutor(max_workers=8)` over
`http_get_json`). A per-posting failure is recorded in `detail_failures` and the
posting is dropped; a total outage raises; a partial outage records a
`record_source_warning` line ("N of M detail fetches failed ... those postings
were not inspected"). That reporting is honest and already in place — the
missing piece is RECOVERY.

Issue #235 reports a single live public-registry run losing 196 postings across
five independent Workday tenants, with rates as bad as 43/45 and 47/49, all to
`HTTP 429 Too Many Requests`. This is recall loss BEFORE any gate: a role
present in the listing cannot match a profile because its JD body was never
fetched. The user's only recovery today is to re-run the whole search, which
re-triggers the same rate limit.

Relevant files:

- `skills/job-search/scripts/common.py` — `_do_request` owns the retry loop
  (`retries=2`) and returns an `HttpResult`; `http_get_json` raises on failure.
  This is where 429 handling and `Retry-After` belong, and why the issue was
  deferred: another agent held this file.
- `skills/job-search/scripts/sources.py` — `fetch_workday`'s `_detail` /
  `ThreadPoolExecutor`; the concurrency is per CALL, so two Workday tenants
  fetched in parallel by `search_jobs.run_tasks` each get their own pool and
  nothing paces a single tenant.
- `skills/job-search/scripts/search_jobs.py` — `run_tasks` and the
  `drain_source_warnings()` reporting the counts land in.

Related work already merged on `fix/sources-and-fetchers`: SmartRecruiters
listing pagination (#236) added the "a cap is not a failure" distinction to the
source-warning vocabulary; reuse that wording rather than inventing a third
phrasing.

## Definition of done

- A fixture server returning 429 then 200 is retried with bounded backoff and
  the posting is captured exactly once.
- `Retry-After` (both the delta-seconds and HTTP-date forms) is honoured, and a
  bounded ceiling stops a hostile value from stalling a run.
- Pacing/concurrency is scoped per Workday tenant, so one board cannot burst.
- Persistent failures stay visible and counted; retries are finite.
- A follow-up path recovers only the missed details without refetching every
  source.
- The search log / snapshot does not claim full-board coverage while detail
  requests remain unfetched.
- Offline regression tests in `skills/job-search/scripts/tests/` (stdlib
  `unittest`, no live network) cover each bullet above.
