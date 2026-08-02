# Worklog — 2026-07-30-vendor-check-has-no-reverse-audit

## 2026-08-02 — session 1 (agent, branch `fix/vendor-reverse-audit`)

- Added `undeclared_vendored_files()` to `automation/vendoring/sync_vendored.py` and
  wired it into `check()`. The check now runs both directions: outward (declared copy
  still matches its source) and inward (every file under a `skills/*/scripts/_vendor/`
  root is declared somewhere).
- First run surfaced exactly 7 undeclared files — 5 `_vendor/README.md` and 2
  `_vendor/__init__.py`. Decided one by one, recorded in `task.md`: both shapes are
  structure rather than vendored code, so neither "declare it" nor "delete it" applies;
  they are the only exemptions, and only at a `_vendor/` root.
- Proved the gate is not decorative three ways: planted an undeclared real module,
  watched the check go 1 and name it, removed it, watched it go 0 — and separately ran
  `main`'s pre-fix `check()` against the SAME planted tree, which returned 0 with
  "vendored copies in sync". That is the fail-open bug, reproduced.
- New pin: `automation/shared/tests/test_vendor_reverse_audit.py` (12 tests). Mutation-
  tested it by unwiring the audit from `check()`'s return — one test failed with
  `0 != 1`, so the wiring pin bites.
- Surprise worth noting: scoping is load-bearing. A bare `rglob("_vendor")` sweeps in
  `.venv/**/site-packages/pip/_vendor` and reports thousands of third-party files, so
  the audit is scoped to `skills/*/scripts/_vendor`. There is a regression test for it.
- Corrected `test_skip_log.py::VendoringTests`' docstring, which asserted the hole as a
  standing fact. Kept the class: it pins that `skip_log.py` is vendored to exactly two
  skills, which the generic audit cannot see.
- `docs/handbook/skills-and-vendoring.md` gained a bullet for the inward direction — its
  prose already said "everything in `_vendor/` except `__init__.py`/`README.md` is
  generated", but nothing enforced it until now.
- Next: nothing. Task complete; moved to `4_done`.
