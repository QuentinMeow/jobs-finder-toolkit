# Verification — 2026-08-02-pin-the-never-delete-an-application-folder-premise

Branch `fix/never-delete-application-folder`. Output redirected, never piped, so every exit
code below is the command's own.

## 1. The premise, re-verified before it was pinned

```
$ grep -rl 'applications_root' --include='*.py' automation skills   # then, per module:
$ grep -n 'rmtree|\.unlink\(|os\.remove|os\.rmdir' <each non-test module>
automation/publish/export_public.py:465,618   export destination + generated symlink
automation/reconcile/reconcile.py:672         the reconciler's own retries queue file
skills/job-search/scripts/build_postings.py   postings cache / store debris (7 sites)
skills/job-search/scripts/search_jobs.py:1157 gitignored filter-review scratch file
skills/application-tracker/scripts/status.py:1349  shutil.move — status transition, NOT a removal
```

No non-test module removes a path beneath `config.applications_root()`. The premise the ADR
rests on holds today, which is why pinning it now is cheap.

## 2. The guard is green on the real tree

```
$ python -m unittest discover -s automation/shared/tests -p 'test_application_folder_never_deleted.py'
Ran 8 tests in 9.569s
OK
EXIT=0
```

## 3. Planted violation — the guard actually fails

A test nobody has watched fail is not a test. Two plants, each removed afterwards.

**Plant A — a folder derived from the root** (inserted into
`skills/application-tracker/scripts/status.py`):

```python
def _planted_violation(slug: str) -> None:
    app_dir = find_application(slug)
    if app_dir is not None:
        shutil.rmtree(app_dir)
```

```
$ python -m unittest discover -s automation/shared/tests -p 'test_application_folder_never_deleted.py'
FAIL: test_no_shipped_module_removes_a_path_under_the_applications_root
AssertionError: Lists differ: [...] != []
First extra element 0:
'  skills/application-tracker/scripts/status.py:944  shutil.rmtree(app_dir) — argument is a
 path under the applications root'
: A module now removes a path under config.applications_root():
  ...
This invalidates the premise of memory/decisions/handoff-records-every-folder-it-creates.md:
  ...
  Do not delete this assertion to go green: revisit the decision (it says how), or keep the
  removal out of the applications tree.
EXIT_RED=1
```

Plant reverted (`git diff --stat` back to the branch's own 31/6 change in that file):

```
$ python -m unittest discover -s automation/shared/tests -p 'test_application_folder_never_deleted.py'
Ran 8 tests in 29.671s
OK
EXIT_GREEN=0
```

**Plant B — the folder arrives as a parameter**, so the taint pass structurally cannot see
where it came from and only the name backstop can (appended to
`skills/job-search/scripts/handoff.py`):

```python
def _planted_param_violation(application_dir):
    shutil.rmtree(application_dir)
```

```
First extra element 0:
'  skills/job-search/scripts/handoff.py:1533  shutil.rmtree(application_dir) — argument names
 an application folder'
EXIT_RED2=1
```

Plant reverted:

```
Ran 8 tests in 9.352s
OK
EXIT_GREEN2=0
```

## 4. The guard's own teeth, permanently

Six in-file cases so it cannot rot into always-green after this session: it must catch a
removal of a root-derived path, a removal through a helper that returns the path, a removal
while walking the tree, and a folder arriving as a parameter; it must leave cache/store
removals and a status-transition `shutil.move` alone. A seventh asserts the scan still
reaches `status.py` and `handoff.py`, so a scan that quietly stopped matching anything cannot
pass as green.

## 5. Failure message names the decision

`DECISION_DOC = "memory/decisions/handoff-records-every-folder-it-creates.md"` is interpolated
into the assertion message — visible in the plant output in section 3 above.
