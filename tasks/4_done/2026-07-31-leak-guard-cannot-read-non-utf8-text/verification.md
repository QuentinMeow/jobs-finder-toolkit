# Verification — 2026-07-31-leak-guard-cannot-read-non-utf8-text

All runs from a git worktree of `fix/leak-guard-fail-open`, using that worktree's
own copy of every script (they resolve their root from `__file__`).

## The measurement the decision rests on: zero non-UTF-8 files tracked today

Baseline, tree at `f360aec`, full export dry-run:

```
$ automation/publish/export_public.py --dest=<scratch> --git-init
EXIT=0
  tracked files:  665
  content read:   658 of 665 file(s)
  not inspected:  7 (binary-sniff: 3, extract-failed: 1, guard-self: 1, no-text-extractor: 2) — opened, no text to scan
OK: no public-repo leaks detected. Safe to publish.
Leak guard PASSED.
```

No `not-utf8` reason in the breakdown, so decode-and-scan cannot destabilize any
currently-tracked file. After the change, the identical run:

```
$ automation/publish/export_public.py --dest=<scratch> --git-init
EXIT=0
  tracked files:  665
  content read:   658 of 665 file(s)
  not inspected:  7 (binary-sniff: 3, extract-failed: 1, guard-self: 1, no-text-extractor: 2) — opened, no text to scan
OK: no public-repo leaks detected. Safe to publish.
Leak guard PASSED.
```

Byte-identical summary. No tracked file newly trips the guard.

## The hole, planted and closed (end to end, real CLI, same planted file)

A tracked latin-1 `.md` carrying an active identity token (fictional: `Quarrenden`,
supplied via `$JOBHUNT_PERSONAL_TOKENS`), scanned by the whole-tree guard.

BEFORE — worktree at `main` (`f360aec`):

```
$ JOBHUNT_PERSONAL_TOKENS='Quarrenden' automation/publish/check_public.py
BEFORE_LATIN1_EXIT=0
  content read:   1039 of 1047 file(s)
  not inspected:  8 (binary-sniff: 3, extract-failed: 1, guard-self: 1, no-text-extractor: 2, not-utf8: 1) — opened, no text to scan
OK: no public-repo leaks detected. Safe to publish.
```

The token is in the tree, the file is counted, and the guard certifies it.

AFTER — the fix branch, same planted file:

```
$ JOBHUNT_PERSONAL_TOKENS='Quarrenden' automation/publish/check_public.py
AFTER_LATIN1_EXIT=1
  content read:   1040 of 1047 file(s)
  not inspected:  7 (binary-sniff: 3, extract-failed: 1, guard-self: 1, no-text-extractor: 2) — opened, no text to scan
  mixed encoding: docs/probe-latin1.md — undecodable byte at offset 31; read with a latin-1 fallback (SCANNED, not skipped)
FAIL: 1 violation(s) found.
  - CONTENT docs/probe-latin1.md:1  (token: 'Quarrenden')  'Reviewed by Quarrenden over café'
```

The `not-utf8` reason is gone from the breakdown, the file moved into
`content read:`, and the token is reported with a true line number. The planted
file was removed and un-staged afterwards; `git status --porcelain` confirmed it.

## Tests: watched RED before GREEN

New class `NonUtf8TextScanTests` (8 tests) run against the UNFIXED guard, together
with `TokenSourceUnreadableTests` from the sibling task:

```
$ python -m unittest ...NonUtf8TextScanTests ...TokenSourceUnreadableTests -v
EXIT=1
Ran 14 tests in 0.306s
FAILED (failures=8, errors=6)
```

Same command after the fix:

```
EXIT=0
Ran 14 tests in 0.089s
OK
```

Full publish suite (baseline 219 tests, exit 0):

```
$ python -m unittest discover automation/publish/tests
EXIT=0
Ran 233 tests in 178.214s
OK (skipped=1)
```

## Armed whole-tree guard, before and after

```
$ JOBHUNT_CONFIG=<real config> automation/publish/check_public.py     # before
EXIT=0 · tracked 1046 · content read 1039 · not inspected 7 · OK, safe to publish
$ JOBHUNT_CONFIG=<real config> automation/publish/check_public.py     # after
EXIT=0 · tracked 1046 · content read 1039 · not inspected 7 · OK, safe to publish
```
