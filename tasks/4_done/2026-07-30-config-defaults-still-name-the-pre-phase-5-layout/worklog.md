# Worklog — four config defaults named the retired layout

## 2026-07-31 — session 1 (agent)

- Checked the live-data hazard before touching code: all four keys are set explicitly in the
  working `config.yaml`, and a side-by-side resolution of the pre- and post-change modules
  against that config returns identical paths. No owner path moved.
- Repointed `blacklist_path()`, `story_bank_path()`, `search_profiles_dir()` and
  `skill_references_dir()` at the lifetime layout; re-vendored.
- Moved the three job-search sites and the resume-writer docstrings/fixtures with them.
  `test_overlay_blacklist.py` was a real dependency, not a comment — it plants its fixture at
  the default location and failed until the fixture moved.
- **Left open for phase 8:** the two DoD items that require `examples/` to mirror the private
  tree (defaults resolving under the example config, and the smoke assertion that every
  `config.*()` path exists there). Both were already unmet before this change; nothing regressed.
- Next: fold the remaining two DoD items into the phase-8 task.
