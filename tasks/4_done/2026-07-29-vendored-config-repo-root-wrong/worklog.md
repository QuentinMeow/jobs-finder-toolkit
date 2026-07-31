# Worklog — 2026-07-29-vendored-config-repo-root-wrong

## 2026-07-29 — session 1 (agent)

- Reproduced both consequences before touching anything. Through the vendored
  `skills/job-search/scripts/_vendor/config.py`, `REPO_ROOT` was
  `skills/job-search/` and `EXAMPLE_CONFIG` a file that cannot exist, so
  `search_jobs._config_layer_present()` answered `True` on a run forced onto
  `config.example.yaml`. Second consequence, not in the task text: in a
  genuinely config-less checkout the example fallback pointed at that
  nonexistent path, so `_load()` printed "continuing with an EMPTY
  configuration" and `candidate_name()` came back `''` — the Jordan Rivers
  example never loaded through any vendored import.
- Replaced the parent count with an upward walk. Extracted `_git_boundary()`
  so `_search_up()` and the new `_repo_root()` share ONE `.git` walk, then
  `REPO_ROOT = _repo_root(_HERE)`.
- No-`.git` case decided as: `config.example.yaml` as a secondary root marker,
  then the module's own directory. The secondary marker turned out to be
  load-bearing, not defensive — `test_export_arming` runs the leak guard inside
  an exported tree that has no `.git`, and a `_HERE`-only fallback would have
  flipped its "fictional example config" report to "real config".
- Verified the leak guard is untouched: it imports the canonical module, whose
  `REPO_ROOT` was already correct and is byte-for-byte the same value after the
  change. Arming tests green, no leak-guard edit needed.
- Tests added: five-copy `REPO_ROOT`/`EXAMPLE_CONFIG` invariant plus
  `_repo_root` marker precedence in `automation/shared/tests/`, and an
  unpatched subprocess `_config_layer_present()` test in job-search. The two
  pre-existing notice tests stub `config_path` to return `EXAMPLE_CONFIG`
  itself, so they compare the constant with itself and could never see this.
- Next: review. Nothing is blocked; no queue items filed.
