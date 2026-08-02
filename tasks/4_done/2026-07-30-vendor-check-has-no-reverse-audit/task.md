# The vendor gate cannot see a `_vendor/` file nobody declared

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: workspace phase 6 adversarial design review, 2026-07-30
- **Claimed-by**: agent session 2026-08-02 (branch `fix/vendor-reverse-audit`)

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

- [x] `sync_vendored.py --check` fails on an undeclared file under any `scripts/_vendor/`
- [x] Proved on a planted defect: copy a file into a `_vendor/` dir without declaring it,
      confirm the check goes red, remove it, confirm green
- [x] Whatever the first run surfaces is resolved file by file, not exempted
- [x] The per-file guard in `test_skip_log.py::VendoringTests` can stay or go — say which
      and why

## Outcome (2026-08-02)

The reverse audit is `undeclared_vendored_files()` in `sync_vendored.py`, wired into
`check()`. Verdicts, exemption narrowness, and the wiring are pinned by
`automation/shared/tests/test_vendor_reverse_audit.py` (12 tests) — that directory is
where the other vendoring-manifest tests live and the only one CI/`run_gates.py`
discovers for them; `automation/vendoring/` has no test dir.

**What the first run surfaced, decided one by one — 7 files, no blanket exemption:**

| File | Decision |
|------|----------|
| `README.md` in each of the 5 `_vendor/` roots | Exempt. Documentation, not vendored code — the hand-written "generated, do not edit" notice. There is no canonical source it could be byte-identical to, so neither declaring nor deleting it is correct. |
| `__init__.py` in `email-assistant/` and `job-search/` `_vendor/` roots | Exempt. Package marker that makes `_vendor` importable by that skill's own scripts. Structure, not a copy of anything. |

Exempt by exact NAME **and** POSITION (directly in a `_vendor/` root), never by glob:
the same names one level down would mean an unmirrored subtree and still fail. This is
also the rule `docs/handbook/skills-and-vendoring.md` already stated in prose
("everything in `_vendor/` except `__init__.py`/`README.md` is generated"); the audit is
the first thing to enforce it.

**`test_skip_log.py::VendoringTests` — KEPT** (docstring corrected; it asserted the hole
as a fact). It pins something neither direction of the gate does: that `skip_log.py` is
vendored to exactly those two skills. The reverse audit only proves nothing *extra* is
present — deleting a needed copy together with its `TARGETS` entry still passes it.
