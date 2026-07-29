# Where should the overlay's BENCHMARK search profile live, now that a bare label resolves only from `config.search_profiles_dir()`?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-29
- **Source**: [workspace-restructure phase 4](../../../design/workspace-restructure/execution-plan.md)
- **Blocking**: nothing in the public toolkit. The private benchmark harness's search leg cannot resolve its profile by bare label until this is settled.
- **Default path**: no public code change. `search_jobs.py --profile` still accepts an absolute path, so the harness works today by passing one; agents do not add a second private literal to the public search path.

## Background

Phase 4 deleted the four inbound symlinks that put personal job-search profiles at
`skills/job-search/profiles/<personal-name>.yaml`. A bare `--profile <label>` now resolves
through `config.search_profiles_dir()` (default `private/job-search-profiles/`) first and the
tracked public `skills/job-search/profiles/` folder second.

Three of the four deleted links pointed into `private/job-search-profiles/`, so those labels
still resolve unchanged. **The fourth pointed into `private/benchmark/job-search-profiles/`** —
a directory `config.search_profiles_dir()` does not cover and that `bootstrap_overlay` never
scanned either (the execution plan already flagged that link as un-bootstrappable, pre-existing
breakage). Ten files in the overlay reference that benchmark label, fifteen of those references
as a bare label rather than a path, so those invocations now exit with "Profile not found"
instead of silently resolving through a hand-made symlink.

No public file references it (verified: zero matches outside `private/`), so this is entirely an
overlay-side arrangement question.

## Options

### Option A — move the benchmark profile into `config.search_profiles_dir()`
One file moves from `private/benchmark/job-search-profiles/` to `private/job-search-profiles/`.
Every bare-label reference then resolves with no code change anywhere. Cost: the benchmark's
profile no longer sits beside the rest of the benchmark fixtures, so `private/benchmark/` is no
longer self-contained. Phase 5 relocates `job-search-profiles/` to `market/searches/` and
`benchmark/` to `evals/fixtures/` anyway, which is the moment to decide adjacency for good.

### Option B — the benchmark harness passes an absolute path
`resolve_profile` already returns any existing path unchanged, so the harness substitutes
`--profile "$OVERLAY/benchmark/job-search-profiles/<label>.yaml"`. Cost: fifteen call sites to
edit in the overlay, and the benchmark stops exercising the same label-resolution code path the
real runs use — a small fidelity loss for a harness whose job is to measure the real pipeline.

### Option C — a `paths.benchmark_profiles_dir` config key appended to the search path
`profile_search_dirs()` grows a third entry. Cost: a `config.py` change is a five-file vendored
change plus a drift check, and it adds a public accessor whose only purpose is one private
fixture directory. It also makes label collisions between the benchmark and the real profiles
resolvable in an order nobody will remember.

## Recommendation

**Option A.** It is one file move in the overlay, needs no public code and no config key, keeps
the benchmark exercising the exact resolution path production uses, and leaves phase 5 free to
place the file wherever the new taxonomy wants it. Option C in particular buys a permanent
public-surface cost for a temporary private-layout problem.

Only the owner can perform it: agents never write under `private/`.

**Your answer:** ______
