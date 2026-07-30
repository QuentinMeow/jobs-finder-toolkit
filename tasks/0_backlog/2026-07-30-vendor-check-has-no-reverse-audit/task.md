# The vendor gate cannot see a `_vendor/` file nobody declared

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: workspace phase 6 adversarial design review, 2026-07-30

## Goal

Make an undeclared vendored copy a failure instead of an invisible one.

## Context

`automation/vendoring/sync_vendored.py` `check()` (~lines 170-192) iterates `TARGETS` and
`DIR_TARGETS` and verifies each declared copy against its canonical source. `_check_dir`
(~155-167) also notices files *added to or removed from* a mirrored **directory**.

The flat `TARGETS` path has no equivalent. Nothing ever enumerates a skill's `_vendor/`
and asks "is every file here declared?" — so copying a module into
`skills/<skill>/scripts/_vendor/` and forgetting the `TARGETS` entry leaves the
pre-commit vendor gate green **forever** while the copy silently drifts from its source.
No other gate covers it either: `automation/reconcile/`, `automation/publish/` and
`automation/gardener/skill_drift.py` never mention `_vendor`.

This is a gate that fails open, which is the class of bug the workspace-restructure design
exists to remove. Phase 6 worked around it for one file by asserting the declaration and
the byte-identity directly in
`automation/shared/tests/test_skip_log.py::VendoringTests` — a per-file guard, not a fix.

The fix is a reverse audit in `check()`: walk every `scripts/_vendor/` directory, and fail
on any file that is neither a declared `TARGETS` copy nor inside a declared `DIR_TARGETS`
tree. **Expect it to fire on existing undeclared files on the first run** — enumerate what
it finds and decide each one (declare it, or delete it) rather than adding a blanket
exemption.

## Definition of done

- [ ] `sync_vendored.py --check` fails on an undeclared file under any `scripts/_vendor/`
- [ ] Proved on a planted defect: copy a file into a `_vendor/` dir without declaring it,
      confirm the check goes red, remove it, confirm green
- [ ] Whatever the first run surfaces is resolved file by file, not exempted
- [ ] The per-file guard in `test_skip_log.py::VendoringTests` can stay or go — say which
      and why
