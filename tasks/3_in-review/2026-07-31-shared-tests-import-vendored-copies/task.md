# automation/shared/tests imports the VENDORED copy, not the module it is testing

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: found while implementing workspace phase 7 PR-D, 2026-07-30
- **Claimed-by**: agent (fix/01-shared-tests-import-path), 2026-07-30

## Goal

Make the shared test suite exercise `automation/shared/` rather than a `_vendor/` copy of it, so a
green suite means the canonical module is correct.

## Context

After `unittest` discovery over `automation/shared/tests`, a bare `import job_metadata` resolves to
`skills/application-tracker/scripts/_vendor/job_metadata.py`, **not**
`automation/shared/job_metadata.py`. Reproduced:

```
$ .venv/bin/python -c "<discover automation/shared/tests, then import job_metadata>"
import job_metadata resolves to:
    <repo>/skills/application-tracker/scripts/_vendor/job_metadata.py
```

Cause: an alphabetically earlier test module in that directory inserts a skill's
`scripts/` or `_vendor/` directory onto `sys.path` at import time, and discovery imports every test
module into one process before running anything. Whichever path lands first wins for the rest of
the run.

**Why it has been harmless so far, and why that is not a reason to leave it.** The vendored copies
are kept byte-identical by `automation/vendoring/sync_vendored.py --check`, which runs in pre-commit
and CI — so today the two files are the same bytes and the tests pass either way. But:

- The suite's guarantee is wrong as stated. It reports on a copy, and the copy is only equal to the
  canonical file because a *different* gate says so. If that gate is ever bypassed, weakened, or
  outraced, the suite silently attests to the wrong file.
- A canonical-only change is untested until it is vendored — the opposite of the intended order.
- It makes any future divergence in vendoring policy (say, a module deliberately vendored to only
  some skills) quietly change which code the tests cover.

Phase 7 PR-D worked around it by loading each module under test by explicit path with a private
alias, rather than by name. That is the right technique for a single test; it is not a fix.

**Do not fix this by reordering imports or renaming test files.** The ordering is incidental and
will drift back. The fix has to make the resolution explicit — e.g. every test in this directory
loads its subject by path, or the suite runs with a `sys.path` that cannot reach a `_vendor/`
directory, or discovery happens in a process that asserts the resolved `__file__` up front.

Whatever the mechanism, it needs a **regression test that fails today**: assert
`job_metadata.__file__` resolves under `automation/shared/` after a full discovery pass. Without
that, the next `sys.path` insertion re-breaks it invisibly.

Check the other vendored modules for the same shadowing — `config`, `layout`, `location`,
`metadata_editor`, `calendar_todos`, `skip_log`, `company_index`, and the `mail/` and `store/`
package targets.

## Definition of done

- [x] After a full discovery pass over `automation/shared/tests`, every module under test resolves
      under `automation/shared/`
- [x] A regression test asserts that, and is shown to fail against the current arrangement
- [x] The other `TARGETS`/`DIR_TARGETS` modules are checked for the same shadowing and the result
      recorded (fixed, or explicitly not affected)
- [x] `sync_vendored.py --check` still clean; full gate green
