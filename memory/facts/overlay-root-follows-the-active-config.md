# `overlay_root()` follows whichever config is active, so an isolated config gets an isolated overlay

- **Filed**: 2026-07-29
- **Source**: investigating whether phase 4's symlink removal broke the benchmark search leg (it did not) — session 2026-07-29

`config.overlay_root()` defaults to `applications_root().parent`. Because
`applications_root()` is read from the *active* config, and paths in a config resolve relative
to that config file's own directory, pointing `$JOBHUNT_CONFIG` at an alternate config
relocates the entire overlay-derived path family at once.

Concretely, the benchmark config sets `applications_root: "benchmark/applications"` relative to
its own directory. That makes:

| Accessor | Under the real config | Under the benchmark config |
|---|---|---|
| `applications_root()` | `private/applications` | `private/benchmark/applications` |
| `overlay_root()` | `private/` | `private/benchmark/` |
| `search_profiles_dir()` | `private/job-search-profiles/` | `private/benchmark/job-search-profiles/` |
| `blacklist_path()`, `story_bank_path()`, `companies_root()`, `candidate_dir()` | under `private/` | under `private/benchmark/` |

This is why a pinned benchmark fixture placed beside the benchmark's applications root is found
automatically by a bare `--profile <label>`, with no symlink and no extra config key: the
isolation the benchmark config already establishes for *writes* extends to profile *reads* for
free.

**What would falsify it:** setting `paths.overlay_root` explicitly in a config, which pins the
overlay root independently of `applications_root`. The derivation is a default, not a law. Also
note the two are only coupled while the benchmark tree sits *inside* the overlay: phase 5 of
[the workspace-restructure execution plan](../../docs/designs/workspace-restructure/execution-plan.md)
moves the benchmark tree into the overlay's eval-fixtures folder, and the fixture profile has to
move with it or gain an explicit `paths.search_profiles_dir`.
