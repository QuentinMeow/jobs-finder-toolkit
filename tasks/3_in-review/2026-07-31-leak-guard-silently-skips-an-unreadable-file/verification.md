# Verification — 2026-07-31-leak-guard-silently-skips-an-unreadable-file

## Test suites

```
$ .venv/bin/python -m unittest discover automation/publish/tests -b
Ran 171 tests in 106.144s
OK (skipped=1)                          # 157 before; +14 for this change

$ .venv/bin/python -m unittest discover automation/shared/tests -b
Ran 455 tests in 14.820s
OK
```

## Whole tree, clean — the guard now states its own coverage

```
$ .venv/bin/python automation/publish/check_public.py --allow-unarmed
  tracked files:  843
  content read:   836 of 843 file(s)
  not inspected:  7 (binary-sniff: 3, extract-failed: 1, guard-self: 1, no-text-extractor: 2)
                  — opened, no text to scan
OK: no public-repo leaks detected. Safe to publish.
EXIT=0
```

Before this change the same run printed a clean result with no statement of how
many files it had actually read.

## Planted defect — a dangling symlink now fails closed

```
$ ln -s ../nowhere/missing.md docs/dangling-probe.md && git add docs/dangling-probe.md
$ .venv/bin/python automation/publish/check_public.py --allow-unarmed
  tracked files:  844
  content read:   836 of 844 file(s)
  UNREADABLE:     1 file(s) could not be opened — see [8] below
FAIL: 1 violation(s) found.

[8] Unreadable tracked files (fail closed — the guard could not open them, so
    NOTHING in them was inspected) (1):
  - BROKEN-SYMLINK  docs/dangling-probe.md  (-> ../nowhere/missing.md)
EXIT=1
```

The probe was removed afterwards; `git status` confirmed only the intended files
remained staged.

## `--staged` did not have this defect and does not change behaviour

`_materialize_index` writes index blobs into a scratch tree and rewrites symlinks
as their target text, so every path that mode scans is a file git just created.
A test pins that an ordinary staged dangling link produces no check-8 finding, so
pre-commit does not begin rejecting commits it used to accept.

```
$ .venv/bin/python automation/publish/check_public.py --staged --allow-unarmed   # with the probe staged
  staged files:   1
  content read:   1 of 1 file(s)
OK: no public-repo leaks detected. Safe to publish.
EXIT=0
```

## Classification actually applied

| Condition | Verdict | Why |
|---|---|---|
| Dangling symlink | FAIL | Broken published output, and the stored target string can name a private tree |
| `OSError` on open (permission, I/O, is-a-directory) | FAIL | The allowlists claim un-extractability, never un-openability |
| NUL-bearing blob, no known extension | counted | Three tracked `.json.zst` payloads; no text to scan |
| Non-UTF-8 text | counted | The task's DoD names this path as one not to regress |
| Corrupt `.docx` | unchanged (check 7) | A tracked fixture is exactly this; escalating would fail the repo's own fixture and red-light a bare CI image |

## Adjacent gates

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check   # vendored copies in sync
$ .venv/bin/python automation/reconcile/reconcile.py --check       # OK (8 checks clean)
$ .venv/bin/python automation/gardener/verify_links.py             # OK: 1697 references
$ .venv/bin/python automation/metrics/instruction_budget.py --strict  # within budget
```

## Left open, filed separately

A non-UTF-8, NUL-free text file (a latin-1 `.md`) is still counted rather than
decoded and scanned — the one remaining way a real name can sit in a tracked text
file unseen. Filed as
`tasks/0_backlog/2026-07-31-leak-guard-cannot-read-non-utf8-text/`.
