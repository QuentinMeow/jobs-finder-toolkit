# Should the builder lock heartbeat, so a live-but-slow build is never stolen from?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [store locking](../../../automation/shared/store/locking.py)
- **Blocks**: nothing — the data-loss half of this is already fixed (`release()` now
  verifies the lock is still ours before unlinking it).
- **Default path**: leave `LOCK_STALE_SECONDS = 300` and the mtime-only staleness test
  exactly as they are. Agents do not add a heartbeat or change the constant.
- **Cost if wrong**: ratify
- **Safe to merge because**: the default is the shipped constant; changing `LOCK_STALE_SECONDS` is
  a one-line edit that persists nothing, and the data-loss half this could have caused is already
  fixed.

## Background

`DomainLock` decides a lock is abandoned by one number: the age of the lock file's
mtime, stamped once at creation and never refreshed. There is no heartbeat anywhere
in the module. So "the holder crashed" and "the holder is simply taking longer than
five minutes" are indistinguishable, and the second case gets its lock stolen while
it is still writing.

The lock wraps three operations that can plausibly exceed five minutes on a real
store: a full `build_postings.py --rebuild` over the whole raw zone, an incremental
build inside a live job search, and the entire GC plan-plus-execute (which, under
`gc_store.py`, includes however long a human spends reading the printed plan).

A separate defect in the same area is already fixed in this PR: the victim of such a
steal used to `unlink` the lock **by path** on its way out, which removed the
*stealer's* lock and let a third builder in — three concurrent writers. `release()`
now re-reads the file and unlinks only when it still carries this holder's
`owner_token`. That closes the third-writer hole. It does **not** close the original
one: after a steal, the victim and the stealer are still both writing.

## Options

### Option A — leave it (the default path)

Keep the 300s window and the mtime-only test. Cost: a build that runs longer than
five minutes can still be joined by a second builder. Benefit: the lock always
self-heals — a genuinely wedged process is never able to block builds forever, which
is the failure mode the module was written to avoid.

### Option B — heartbeat the lock while it is held

A daemon thread touches the lock file every N seconds while a build holds it, so
"stale" comes to mean "the process is gone" rather than "the process is slow"
(a SIGKILLed holder takes its thread with it, and the lock ages out correctly).
Cost: a holder that hangs rather than dies — blocked forever on a socket read, say —
now keeps its lock fresh indefinitely and every later build fails fast forever. That
is the same permanent-wedge shape the audit calls a defect in the identifier
allocation lock, traded in from the other direction.

### Option C — heartbeat with a ceiling

Refresh the mtime, but stop refreshing after a bounded total lifetime (30 minutes,
say), so a hung holder eventually goes stale anyway. Costs more machinery (two
thresholds instead of one) and needs a number nobody has measured yet.

### Option D — just raise `LOCK_STALE_SECONDS`

One-line change, no threads. Picks a number above the worst-case rebuild — but
nobody has measured the worst-case rebuild, and every second added is a second a
genuinely crashed build blocks the next one.

## Recommendation

Option A for now, and measure before choosing between B/C/D. The concurrency this
leaves is the *documented* stale-steal behaviour, not a surprise, and the fix in
this PR removes the unbounded third-writer case that made it dangerous. What is
missing to decide properly is a single number: how long a rebuild and a GC actually
take on the owner's real store. If that number is comfortably under 300s, Option A
is simply correct and nothing needs doing. If it is near or over it, Option C is the
right shape (it fixes the slow-holder case without inventing a permanent wedge).

**Your answer:** ______
