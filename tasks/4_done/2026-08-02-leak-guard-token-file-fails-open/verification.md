# Verification — 2026-08-02-leak-guard-token-file-fails-open

All runs from a git worktree of `fix/leak-guard-fail-open`, using that worktree's
own copy of every script. The token file used in every probe is a FICTIONAL one
written into the worktree's git-ignored `private/` and deleted afterwards; the real
one was never read, printed, or modified.

## The fail-open, end to end, on identical conditions

A token file that EXISTS but cannot be read (`chmod 000`), whole-tree guard, armed
from the real config.

BEFORE — worktree at `main` (`f360aec`):

```
$ automation/publish/check_public.py
BEFORE_UNREADABLE_EXIT=0
  supplementary tokens: 0 (leak_tokens.txt + mounted overlay skill names; never arming)
  active tokens:        4 (union, deduped)
OK: no public-repo leaks detected. Safe to publish.
```

Every supplementary token silently gone, and the guard certifies the tree anyway.

AFTER — the fix branch, same file, same permissions:

```
$ automation/publish/check_public.py
UNREADABLE_EXIT=1
  supplementary tokens: 0 (leak_tokens.txt + mounted overlay skill names; never arming)
  active tokens:        4 (union, deduped)
FAIL: 1 violation(s) found.
[9] Unreadable personal-token source (1) — the file EXISTS but could not be read, so the token scan above ran on a SILENTLY NARROWER token set:
  - private/leak_tokens.txt  (PermissionError: Permission denied)
```

## The readable branch still passes (no over-eager gate)

Same fictional file at mode 644, nothing else changed:

```
$ automation/publish/check_public.py
READABLE_EXIT=0
  supplementary tokens: 2 (leak_tokens.txt + mounted overlay skill names; never arming)
  active tokens:        6 (union, deduped)
OK: no public-repo leaks detected. Safe to publish.
```

## The absent branch stays legitimate

Every other whole-tree and export run in this task and its sibling ran with NO
`private/` mounted in the worktree — `supplementary tokens: 0`, exit 0, no `[9]`
section. A public clone with no overlay is unaffected.

## Tests: watched RED before GREEN

New class `TokenSourceUnreadableTests` (6 tests) run against the UNFIXED guard,
together with `NonUtf8TextScanTests` from the sibling task:

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

The six cover: unreadable (refuses to certify, `PermissionError` in the detail),
absent (legitimate), dangling symlink (a finding, not an absence), non-UTF-8 token
file (keeps every token), the report naming `[9]`, and a caller-supplied `tokens=`
scan staying inert because it never consulted the files.

Full publish suite (baseline 219 tests, exit 0):

```
$ python -m unittest discover automation/publish/tests
EXIT=0
Ran 233 tests in 178.214s
OK (skipped=1)
```
