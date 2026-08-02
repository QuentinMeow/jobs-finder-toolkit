# Worklog — 2026-07-31-shared-tests-import-vendored-copies

## 2026-07-30 — session 1 (agent, `fix/01-shared-tests-import-path`)

- Reproduced the shadowing and audited all ten `TARGETS`/`DIR_TARGETS` sources:
  seven resolved to a `_vendor/` copy after a discovery pass; the other three
  (`calendar_todos`, `company_index`, `mail`) were canonical only by accident of
  alphabetical order, not by design. Details in `verification.md`.
- Mechanism chosen: a `sys.meta_path` finder
  (`automation/shared/tests/_canonical_imports.py`) that pins every vendored
  top-level name to `automation/shared/`. `sys.meta_path` is consulted before
  `sys.path`, so resolution stops depending on import order instead of depending
  on a different order. The pinned set is derived from `sync_vendored.py`, so a
  newly vendored module is covered the day it is added.
- Rejected first attempt: a package `__init__.py`. `unittest discover
  automation/shared/tests` — the form CI and the gate run — sets `top_level_dir`
  equal to the start directory, imports each test module as a top-level module,
  and never imports `__init__.py`. The four sibling suites all carry an empty
  `tests/__init__.py` that, for the same reason, never runs.
- Delivery: every `test_*.py` calls `pin_shared_modules()` before its first
  repo-local import, so no single file's position in the alphabet is load-bearing.
  `test_canonical_module_resolution.py` asserts the call is present in all of
  them, plus the resolution itself, submodule resolution, survival of
  `sys.modules` eviction, and that the pin beats a `_vendor/` directory forced to
  `sys.path[0]`.
- Next: review. No follow-up filed; nothing pending in `message-queue/`.
