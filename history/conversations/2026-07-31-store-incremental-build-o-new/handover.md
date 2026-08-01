# Handover — store incremental build goes O(new)

- **Date**: 2026-07-31
- **Task(s)**: 2026-07-21-store-incremental-build-o-new

## What happened

The store build that runs at the end of every search used to re-derive the whole
store each time — 3 minutes 13 seconds on a 15,000-posting store, growing
forever. It now folds only the manifests it has not seen: about 6.5 seconds for
the same three new board fetches.

The hard part was not the speed, it was proving the output is still byte-for-byte
identical to a full rebuild. The fold turned out to have exactly one
order-sensitive piece of carried state, and exactly one reduction that is not a
per-entity partition (the duplicate/ATS-migration hint pass, which can change an
entity that no new manifest mentions). Both are handled explicitly and pinned by
tests. Byte-identity was confirmed twice: the existing equivalence test, and a
real 15,000-entity store built both ways and compared file by file — 45,000
derived files, zero differences.

Two judgement calls were decided by measurement rather than taste and written
down: the index zone is still rewritten whole (every index file's header moves on
every ingesting run, so partitioning would save nothing), and the pre-sanctioned
SQLite cache is deferred (neither of its triggers has fired, and it would not
have touched the actual bottleneck).

## Where things stand

- Work is complete and staged on `wip/05-store-incremental-build`, not committed
  — the orchestrator assembles the stack.
- Task moved to `tasks/3_in-review/` with its definition of done ticked, a
  worklog, and a `verification.md` carrying real command output.
- Design recorded at `docs/designs/raw-data-layer/05-incremental-build.md` and
  linked from the family index and the job-postings design.
- One thing worth knowing: a build no longer silently repairs a hand-edited or
  damaged `posting.yaml` it did not re-fold. Code changes still reach the whole
  store automatically (they change a fingerprint that forces a full fold);
  content damage is repaired by `build_postings.py --rebuild`.

## Needs your attention

- Nothing. No `message-queue/needs-human/` items were filed — every choice was
  reversible or settled by measurement.
