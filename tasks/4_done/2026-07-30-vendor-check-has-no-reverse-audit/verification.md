# Verification — 2026-07-30-vendor-check-has-no-reverse-audit

Branch `fix/vendor-reverse-audit`, worktree off `main` at `f360aec`. Every command was
run from the worktree's own copy of the script (they resolve their root from `__file__`,
so the main checkout's copy would have audited main's tree). Exit codes were read from a
redirect, never through a pipe.

## 1. Clean tree — the check stays green

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
EXIT=0
```

## 2. Planted defect — the check goes red and names the file

A real shared module copied into a skill that does not declare it: exactly the mistake
the gate exists to catch.

```
$ cp automation/shared/location.py \
     skills/behavioral-interview-prep/scripts/_vendor/location.py
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
UNDECLARED VENDORED FILE: skills/behavioral-interview-prep/scripts/_vendor/location.py
Nothing in automation/vendoring/sync_vendored.py names the file(s) above, so this check
compares them to no canonical source and they drift silently. Fix EACH one: either
declare it — add its canonical source -> this path to TARGETS (or its directory to
DIR_TARGETS) in automation/vendoring/sync_vendored.py, then re-run the script to
regenerate it — or delete the file if nothing needs it. Re-running sync_vendored.py
alone will NOT clear this.
EXIT=1
```

## 2b. The same defect against `main`'s pre-fix `check()` — fails OPEN

`main`'s version of the script, loaded by path with `REPO_ROOT` pointed at this worktree,
so it sees the identical planted tree. This is the bug, reproduced:

```
$ git show main:automation/vendoring/sync_vendored.py > /tmp/old_sync_vendored.py
$ .venv/bin/python -c "<load /tmp/old_sync_vendored.py, REPO_ROOT=<worktree>, sys.exit(check())>"
vendored copies in sync
EXIT_OLD_CHECK=0
```

## 3. Defect removed — green again

```
$ rm skills/behavioral-interview-prep/scripts/_vendor/location.py
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
EXIT=0

$ git status --porcelain            # nothing left behind by the plant
 M automation/vendoring/sync_vendored.py
```

## What the exemption list is actually buying (audit re-run with it disabled)

Independent re-confirmation of the sizing, not taken on trust — exactly 7 files, all
structure, no code:

```
$ .venv/bin/python -c "<load sync_vendored, print undeclared_vendored_files();
                        then _VENDOR_ROOT_EXEMPT = frozenset() and print again>"
--- with exemptions (production) ---
(none)
--- exemptions DISABLED: what the exemption list is buying ---
skills/application-tracker/scripts/_vendor/README.md
skills/behavioral-interview-prep/scripts/_vendor/README.md
skills/email-assistant/scripts/_vendor/README.md
skills/email-assistant/scripts/_vendor/__init__.py
skills/job-search/scripts/_vendor/README.md
skills/job-search/scripts/_vendor/__init__.py
skills/resume-writer/scripts/_vendor/README.md
EXIT=0
```

## New unit test — and proof it is not vacuous

```
$ .venv/bin/python -m unittest discover automation/shared/tests \
      -p 'test_vendor_reverse_audit.py' -v
[12 tests listed]
Ran 12 tests in 0.217s
OK
EXIT=0
```

Mutation: `check()`'s `if drift or dir_drift or undeclared:` reverted to
`if drift or dir_drift:` — i.e. the audit computed but ignored, the precise way this
gate could regress to fail-open:

```
$ .venv/bin/python -m unittest discover automation/shared/tests \
      -p 'test_vendor_reverse_audit.py'
AssertionError: 0 != 1
Ran 12 tests in 0.200s
FAILED (failures=1)
EXIT_MUTATED=1
```

The mutation was reverted from a byte copy taken before it and re-confirmed by grep.

## Full gate block — all at `f360aec` + this branch's working tree

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check   EXIT=0
$ .venv/bin/python -m unittest discover automation/shared/tests    EXIT=0   (OK)
$ .venv/bin/python automation/gates/run_gates.py                   EXIT=0
ALL GREEN (29 gates, 2 skipped: reconciler-require-roots, verify-links-require-roots)
```

Both skips are the standard "private/ is not mounted" skips that CI also takes; neither
is a gate this change touches. `example-render` rewrote the tracked example DOCX/PDF
binaries as it always does; reverted with `git checkout -- examples/` since those bytes
are not the point of this change, and `git status` was re-read afterwards to confirm.
