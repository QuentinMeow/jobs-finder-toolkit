# Verification — 2026-07-31-leak-guard-silently-skips-an-unreadable-file

**Corrected 2026-07-31 on the stack tip `40871e6`.** The two suite counts were right;
the four tracked-file counts and the two adjacent-gate figures were not. Every block
below has been re-run — the planted-symlink probe included — and now shows both the
figure at this change's own commit `b5b917b` and the figure at the tip.

## Test suites

```
$ .venv/bin/python -m unittest discover automation/publish/tests -b
Ran 171 tests in 106.144s
OK (skipped=1)                          # 157 before; +14 for this change

$ .venv/bin/python -m unittest discover automation/shared/tests -b
Ran 455 tests in 14.820s
OK
```

Both re-measured at `b5b917b` and at its parent `d03a4c1`: publish 157 → **171**,
shared 455 → **455** (this change adds no shared tests). Accurate as published. At the
tip `40871e6` the same suites give publish **188**, shared **559**.

## Whole tree, clean — the guard now states its own coverage

```
$ .venv/bin/python automation/publish/check_public.py --allow-unarmed    # at b5b917b
  tracked files:  846
  content read:   839 of 846 file(s)
  not inspected:  7 (binary-sniff: 3, extract-failed: 1, guard-self: 1, no-text-extractor: 2)
                  — opened, no text to scan
OK: no public-repo leaks detected. Safe to publish.
EXIT=0
```

**Originally recorded as `843` / `836 of 843`.** Those are `main`'s counts; `git ls-files
| wc -l` at `b5b917b` is 846, and this change itself adds three tracked files. The
`not inspected: 7` breakdown and the accounting invariant were right: 839 + 7 + 0 = 846.

Re-run at the tip:

```
$ .venv/bin/python automation/publish/check_public.py --allow-unarmed    # at 40871e6
  tracked files:  921
  content read:   914 of 921 file(s)
  not inspected:  7 (binary-sniff: 3, extract-failed: 1, guard-self: 1, no-text-extractor: 2)
OK: no public-repo leaks detected. Safe to publish.
EXIT=0
```

Before this change the same run printed a clean result with no statement of how
many files it had actually read.

## Planted defect — a dangling symlink now fails closed

Re-planted and re-run at the tip 2026-07-31, in a throwaway clone; the owner's checkout
was never touched. The behaviour reproduces exactly; only the counts moved (originally
recorded as `844` / `836 of 844`, which are `main`-based — at `b5b917b` the planted run
gives 847 / 839).

```
$ ln -s ../nowhere/missing.md docs/dangling-probe.md && git add docs/dangling-probe.md
$ .venv/bin/python automation/publish/check_public.py --allow-unarmed    # at 40871e6
  tracked files:  922
  content read:   914 of 922 file(s)
  UNREADABLE:     1 file(s) could not be opened — see [8] below
FAIL: 1 violation(s) found.

[8] Unreadable tracked files (fail closed — the guard could not open them, so
    NOTHING in them was inspected) (1):
  - BROKEN-SYMLINK  docs/dangling-probe.md  (-> ../nowhere/missing.md)
EXIT=1
```

The probe was removed afterwards; `git status --porcelain` returned 0 entries.

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

Re-run at the tip with the same probe staged: byte-identical output, exit 0.

## Classification actually applied

| Condition | Verdict | Why |
|---|---|---|
| Dangling symlink | FAIL | Broken published output, and the stored target string can name a private tree |
| `OSError` on open (permission, I/O, is-a-directory) | FAIL | The allowlists claim un-extractability, never un-openability |
| NUL-bearing blob, no known extension | counted | Three tracked `.json.zst` payloads; no text to scan |
| Non-UTF-8 text | counted | The task's DoD names this path as one not to regress |
| Corrupt `.docx` | unchanged (check 7) | A tracked fixture is exactly this; escalating would fail the repo's own fixture and red-light a bare CI image |

## Adjacent gates

Re-run 2026-07-31. The reference count published here was wrong at `b5b917b` too — 1697
is `main`'s figure; this change's own commit gives 1701.

```
                                                                # at b5b917b   # at 40871e6
$ .venv/bin/python automation/vendoring/sync_vendored.py --check  in sync        in sync
$ .venv/bin/python automation/reconcile/reconcile.py --check      8 checks       9 checks
$ .venv/bin/python automation/gardener/verify_links.py            1701 refs      2552 refs
$ .venv/bin/python automation/metrics/instruction_budget.py --strict  within budget  within budget
```

Eight checks at `b5b917b` is correct, not stale — `public-registry-blacklist` is added by
`8a1321a`, four commits above this one. The reference count is the one that was false at
both ends.

## Left open, filed separately

A non-UTF-8, NUL-free text file (a latin-1 `.md`) is still counted rather than
decoded and scanned — the one remaining way a real name can sit in a tracked text
file unseen. Filed as
`tasks/0_backlog/2026-07-31-leak-guard-cannot-read-non-utf8-text/`.
