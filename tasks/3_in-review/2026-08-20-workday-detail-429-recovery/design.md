# Design — bounded Workday detail recovery

## Need

Workday listing searches return lightweight paths, then the fetcher reads each JD.
The current eight-thread detail burst can make one tenant reject most of those reads
with HTTP 429. A failed path disappears before filtering, so it is a recall loss,
not merely a slower request.

## Decision

1. Keep shared HTTP behavior unchanged. Add only a pure, shared parser that turns a
   `Retry-After` delta or HTTP-date into a non-negative delay capped at 10 seconds.
   Workday detail fetches opt out of the generic immediate retries and own recovery
   at the level that knows which posting path failed.
2. Remove Workday's inner eight-worker detail pool. One tenant-local pacer spaces
   request starts by 250 ms. The outer source executor can still run independent
   tenants in parallel, but no tenant creates a burst or parks eight sleeping
   workers behind the same rate limit.
3. Fetch every unique candidate path once, then run at most two recovery rounds over
   only the paths still missing. A 429 defers that tenant by its bounded
   `Retry-After`; a missing or invalid header falls back to bounded 1-second then
   2-second delays. Transport failures, response-read exceptions, and invalid
   success bodies use the same finite missed-path rounds without inventing an
   unbounded loop. Each path owns its exception boundary, so a broken response
   cannot discard sibling details already recovered for the tenant.
4. Key successes by listing path. A recovered path replaces its missed state and is
   emitted once even if it required several HTTP exchanges; a path that succeeded is
   never requested in a recovery round.
5. Persistent misses continue through the existing source-warning channel. The
   warning explicitly marks `coverage=incomplete`, gives the missing/attempted
   counts, and is copied into the run snapshot's `errors` field. A total detail
   outage still raises and becomes a source error, so neither result can look like a
   fully inspected board.

## Rejected alternatives

- Retrying 429 inside the generic HTTP loop would silently change every ATS and
  aggregator, could retry unsafe future methods, and cannot recover by posting path.
- Keeping eight detail workers and sleeping each one would consume threads while the
  tenant is asking the client to stop, then risk another synchronized burst.
- A process-global Workday limiter would couple unrelated tenants: one employer's
  429 would stall every other Workday board.
- Trusting an unbounded `Retry-After` lets a hostile or malformed provider response
  stall the full search indefinitely.
- Re-running the full board or full search after any miss repeats listing requests,
  already-successful details, and unrelated sources; it also increases the chance of
  another rate limit.
- Retrying until success hides persistent outages and makes completion time
  unknowable.

## Consequences and rollback

Large Workday tenants become deliberately slower: 60 detail candidates require at
least about 15 seconds before provider delays. Independent tenants still overlap in
the outer executor. Recovery adds at most two attempts per missing path and at most
10 seconds of provider-requested delay before an attempt, so the run remains finite.

Rollback is local: restore the old detail executor and remove the Workday recovery
helper. The shared parser has no side effects and can remain or be removed
independently. Snapshot schema and company-search-log formats do not change.
