# Verification — 2026-08-03-bootstrap-repair-dangling-hooks

All output below is real, taken on this branch. Absolute home paths are redacted to
`<repo-root>`; nothing else is edited.

## The incident's exact shape, reproduced and repaired

A throwaway repo wired the way every pre-move checkout was
(`.git/hooks/pre-commit -> ../../hooks/pre-commit`, dangling):

```
$ .venv/bin/python -m unittest discover -s automation/hooks/tests -t . \
      -k TestBootstrapRepairsBrokenHookInstalls        # EXIT=0
Ran 7 tests in 0.197s
OK
```

The same 7 tests against the pre-change `bootstrap_overlay.py`
(`git stash push -- automation/bootstrap_overlay.py`):

```
Ran 7 tests in 0.196s
FAILED (failures=6)
```

The one that still passes is the guard on the behaviour that must NOT change: a foreign
symlink resolving outside `automation/hooks/` is left alone.

## The hooks suite as CI runs it

```
$ .venv/bin/python -m unittest discover automation/hooks/tests   # EXIT=0
Ran 33 tests in 6.009s
OK
```

Delta caused by this task: 26 → 33 tests in that suite (+7), +0 files.

## `--check` on a real, correctly wired checkout

```
$ .venv/bin/python automation/bootstrap_overlay.py --check   # EXIT=0
bootstrap_overlay [CHECK (no changes)]  root=<repo-root>
  [    ok] [toolkit] .git/hooks/pre-commit -> ../../automation/hooks/pre-commit (already correct)
  [    ok] [toolkit] .git/hooks/pre-push -> ../../automation/hooks/pre-push (already correct)
  [    ok] [overlay] private/.git/hooks/pre-commit -> ../../../automation/hooks/overlay-pre-commit (already correct)
  [    ok] [overlay] private/.git/hooks/pre-push -> ../../../automation/hooks/overlay-pre-push (already correct)
check complete.
```

(Overlay skill-adapter lines omitted — they name private skills.)

## Gate lanes

`automation/bootstrap_overlay.py` has no lane owner in `automation/ci/classify_changes.py`, so
CI expands this diff to the full matrix. The two lanes this change can actually affect:

```
$ .venv/bin/python automation/gates/run_gates.py --lane maintenance,policy --jobs 4
ALL GREEN (16 gates)
```

First run of that command was RED on `tests-gardener`, for a reason outside this change:
`automation/gardener/tests/test_verify_links.py::TestRetiredRoots::test_the_map_is_still_true_of_the_real_repo`
reads the real tree, and `automation/maintenance/` (retired at 031e05d) still existed locally as
untracked `__pycache__` dated 2026-07-22 — `git ls-files automation/maintenance` was empty. Deleted
the stale bytecode; nothing tracked was touched and nothing was filed, because the tracked tree
holds no defect. A fresh CI clone carries no bytecode, so CI never saw it.

```
$ .venv/bin/python automation/gates/run_gates.py --only tests-gardener   # EXIT=0
ALL GREEN (1 gates)
```
