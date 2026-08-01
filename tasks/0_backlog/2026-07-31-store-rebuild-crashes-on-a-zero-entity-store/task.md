# `--rebuild` hard-crashes on a store with zero materialized entities

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: adversarial review of the O(new) incremental store build, 2026-07-31 —
  found while attacking `build_postings.py`; **pre-existing**, `_swap_dir` predates the
  incremental-build change, and it was ruled out of scope for that fix
- **Claimed-by**:

## Goal

`build_postings.py --rebuild` on a store with no materialized entities should exit
cleanly, not raise an uncaught `FileNotFoundError` after it has already moved
`derived/` aside.

## Context

`build_rebuild` writes each entity into `derived.building`. With zero entities nothing
is written, so the directory is never created — `_write_entity` (via `atomic_write_text`)
is what creates it. `_swap_dir` then does its two renames:

```python
if current.exists():
    current.rename(backup)      # derived -> derived.old   (already done)
new.rename(current)             # derived.building -> derived   → FileNotFoundError
```

The first rename has already happened when the second raises, so the process dies with
`derived/` renamed to `derived.old`. It is recoverable — the next build's
`_recover_swap_remnants` restores it — but the user sees a raw traceback, and the store
is momentarily missing its derived zone for reasons that have nothing to do with an error.

Reachable in two ways, both reproduced:

```
A: a completely empty store (no manifests at all)
   FileNotFoundError: … 'jobs/derived.building' -> 'jobs/derived'

B: raw exists but every captured row is suppressed (a decisively foreign scrape)
   B incremental: rc=0, entities=0, suppressed=1
   B rebuild:     FileNotFoundError (same line)
```

Case B is the realistic one: one aggregator sweep whose only row is a non-US posting.

## Definition of done

- [ ] `--rebuild` on a store with zero materialized entities exits 0 with a sane summary
      (or a clear one-line message), never a traceback
- [ ] `derived/` is not left renamed to `derived.old` by that path
- [ ] A test covers both shapes: no manifests at all, and manifests whose every row is
      suppressed
- [ ] `.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests` passes
