# Worklog — a gardener test reads the owner's real profile

## 2026-07-31 — session 1 (agent)

- Reproduced live: a bare `unittest discover` over `automation/gardener/tests` with the overlay
  mounted resolved and printed the owner's real baseline and profile.
- Pinned `JOBHUNT_CONFIG` at a fixture config inside `test_skill_drift.py` and asserted the
  resolved accessor paths, per the task's "proved, not inspected" requirement.
- Added `test_fixture_isolation.py`: a subprocess audit-hook guard over the whole folder, plus a
  canary that proves the recorder works where no overlay exists.
- Confirmed the suite's single `@unittest.expectedFailure` is still correct (indented code
  blocks are not masked by `_mask_fences()`), so it stays.
- Next: none. The guard doubles the folder's runtime; the cheaper follow-up is speeding up
  `test_verify_links`, which is ~45s of git-init work.
