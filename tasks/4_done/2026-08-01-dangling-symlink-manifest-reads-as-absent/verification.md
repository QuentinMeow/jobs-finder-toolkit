# Verification — 2026-08-01-dangling-symlink-manifest-reads-as-absent

All commands run on branch `fix/21-store-dangling-symlink`, against throwaway
`tempfile.TemporaryDirectory()` stores — never the real store. Three interpreters
were used because the traversal's symlink behaviour turned out to be
version-dependent: the repo floor 3.11.15, the version CI pins in
`.github/workflows/ci.yml` (3.12.13), and the repo venv (3.13.13).

## The defect, reproduced before the fix

A scratch probe builds one `greenhouse` board fetch, then replaces its
`manifest.json` with a symlink to a target that never exists.

```
$ <3.11 | 3.12 | 3.13> local/scratch/repro_dangle.py       # identical on all three
is_symlink: True | lexists: True | exists(): False
_read_manifest      : (None, None)                 <- classified TRULY ABSENT
find_damaged        : []
audit orphans       : ['7abe18a7...'] | undetermined: False | damaged: 0
plan damaged/orphans: 0 ['7abe18a7...']
orphans_removed     : 1 | blob state: pruned (want present)
find_debris_dirs@48h: ['20260701T000000Z-000001-aaaaaa']
```

Two independent losses from one broken symlink: the GC tombstoned and deleted the
blob (`pruned`), and `find_debris_dirs` classified the LIVE fetch dir as crash
debris — which `execute_sweep` removes with `shutil.rmtree(..., ignore_errors=True)`
under `--execute` once it is past the 24h window.

`_iter_manifest_paths` differed by interpreter on the same input, which is why the
fix could not stop at `_read_manifest`:

```
3.11.15  _iter_manifest_paths: []                  <- link never reached the classifier
3.12.13  _iter_manifest_paths: ['manifest.json']
3.13.13  _iter_manifest_paths: ['manifest.json']
```

Root cause of the split, read from the stdlib: 3.11 matches a literal path component
with `pathlib._PreciseSelector`, whose test is `Path.exists()` (follows symlinks);
3.12 removed that class and matches literals against `os.scandir()` entries; 3.13
rewrote glob around `os.path.lexists`.

## The new tests FAIL before the fix

Source stashed (`git stash push -- automation/shared/store/manifest.py
automation/shared/store/retention.py`), tests kept:

```
$ <py> -m unittest discover -s automation/shared/tests -t automation/shared/tests \
      -p test_store_gc.py -k dangling -v
FAIL: test_dangling_symlink_manifest_is_damage_and_its_blob_is_not_an_orphan
  self.assertEqual([d.path for d in found], [dangling])
  AssertionError: Lists differ: [] != [PosixPath('.../manifest.json')]

FAIL: test_live_fetch_dir_with_a_dangling_manifest_is_not_crash_debris
  self.assertNotIn(fetch_dir, reported)
  AssertionError: PosixPath('.../20260701T000000Z-000001-aaaaaa') unexpectedly found

Ran 2 tests   FAILED (failures=2)          EXIT=1   on 3.11, 3.12 and 3.13
```

## …and PASS after it

```
$ <py> -m unittest discover -s automation/shared/tests -t automation/shared/tests \
      -p test_store_gc.py -k dangling -v
test_dangling_symlink_manifest_is_damage_and_its_blob_is_not_an_orphan ... ok
test_live_fetch_dir_with_a_dangling_manifest_is_not_crash_debris ... ok

Ran 2 tests   OK                            EXIT=0   on 3.11, 3.12 and 3.13
```

Same probe, post-fix, identical on all three interpreters:

```
_iter_manifest_paths: ['manifest.json']
_read_manifest      : (None, "FileNotFoundError: [Errno 2] No such file …")
find_damaged        : ['manifest.json']
audit orphans       : [] | undetermined: True | damaged: 1
orphans_removed     : 0 | blob state: present (want present)
find_debris_dirs@48h: []
```

## Through the real CLI

```
$ .venv/bin/python  (gc_store.main(["--data-root", <tmp>, "--dry-run"]))
gc_store: 1 damaged store file(s) — sweep suspended, nothing deleted.
  DAMAGED manifests (present but UNREADABLE): 1
  orphaned blobs …: UNDETERMINED — part of the reference set is unreadable
gc_store --dry-run rc = 4          (was rc = 0 with "orphaned blobs …: 1")
blob state after      = present
```

## Gate block (exit codes read from `$?` after a redirect, never a pipe)

```
$ .venv/bin/python -m unittest discover automation/shared/tests     EXIT=0  (623 tests, OK)
$ .venv/bin/python automation/vendoring/sync_vendored.py --check    EXIT=0
$ .venv/bin/python automation/reconcile/reconcile.py --check        EXIT=0  (9 checks clean)
$ .venv/bin/python automation/publish/check_public.py --staged --allow-unarmed
                                                                    EXIT=0
$ .venv/bin/python automation/gardener/verify_links.py --require-roots --no-overlay
                                                                    EXIT=0
$ .venv/bin/python automation/metrics/instruction_budget.py --strict EXIT=0
$ .venv/bin/python automation/publish/review_gate.py --verify-all    EXIT=0
$ .venv/bin/python -m unittest discover automation/gardener/tests    EXIT=0  (165 tests, OK)
```

## Definition of done

- [x] `_read_manifest` returns a damage error for a dangling-symlink `manifest.json`
      and still returns the absent reading for a file that truly vanished (the absent
      branch is now `not os.path.lexists(path)`; the existing suite's absent-path
      cases stay green).
- [x] A test beside `test_truncated_manifest_is_damage_and_its_blob_is_not_an_orphan`
      asserts BOTH that `find_damaged_manifests` reports it and that the GC refuses
      to delete the blob (`blocked_by_damaged == 1`, `orphans_removed == 0`,
      `blobs.state(...) == PRESENT`).
- [x] `python -m unittest discover automation/shared/tests` passes.
- [x] Vendored copies re-synced (`sync_vendored.py`, then `--check` green).

## Scope note — what the filed task got wrong

1. **It covered only the manifest half.** `retention.py::find_debris_dirs` shares the
   blind spot and is the more destructive of the two: it removes the whole fetch
   directory, not just the blob. Fixed here, with its own test.
2. **Its one-line closure would have been dead code on the repo floor.** The task
   states `raw.glob(...)` lists a dangling symlink "so the path does reach
   `_read_manifest` — the bug is only in the classification". Measured, that holds on
   3.12/3.13 and is false on 3.11. `_iter_manifest_paths` was changed to `os.walk` +
   `os.path.lexists` so the guarantee no longer depends on the interpreter.
3. The task's suggested `not path.exists() and not path.is_symlink()` also works;
   `not os.path.lexists(path)` was preferred as one call that states the actual
   question — is there a directory entry — and matches the new traversal and
   `find_debris_dirs`.
