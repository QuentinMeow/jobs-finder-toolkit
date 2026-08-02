# A dangling-symlink manifest.json reads as absent, so its blobs are deleted

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: disclosed by the store-guard stack's landing plan; no PR in that
  stack fixes it. Re-confirmed while fixing the location residency regression
  (branch `fix/45-us-remote-residency`).
- **Claimed-by**: agent, 2026-08-02 (branch `fix/21-store-dangling-symlink`; work complete, in review)

## Goal

Make `automation/shared/store/manifest.py::_read_manifest` classify a
`manifest.json` that is a DANGLING SYMLINK as damaged rather than absent, so the
store's delete path refuses to run instead of deleting and tombstoning blobs that
manifest still references.

## Context

`_read_manifest` separates three outcomes: readable, damaged (present but
unreadable), and truly absent. The absent test is:

```python
if isinstance(exc, FileNotFoundError) and not path.exists():
    return None, None  # truly absent now — not damage
```

`Path.exists()` FOLLOWS symlinks, so a `manifest.json` that is a symlink to a
missing target raises `FileNotFoundError` on read AND answers `False` to
`exists()`. The pair reads as "the file genuinely is not there any more", which is
the one classification with no consequences.

The consequence chain is the damaging part. Because the manifest is called absent
rather than damaged:

- `find_damaged_manifests` does not report it, so the guard that makes every
  delete-on-no-reference consumer refuse to run stays clear;
- `iter_manifests` skips it, so the blob-reference scan never sees the shas that
  manifest references;
- those blobs then look unreferenced, and the GC deletes and tombstones them.

The distinction the dataclass docstring draws — "a damaged manifest's references
are unknowable, so every consumer that deletes on the strength of 'nothing
references this' must refuse to run while any exist" — is exactly the case here.
A dangling symlink is a file that IS on disk (the link is a directory entry) whose
contents cannot be read.

The one-line closure is to make the absent test not follow the link:

```python
if isinstance(exc, FileNotFoundError) and not path.exists() \
        and not path.is_symlink():
```

`Path.is_symlink()` does not follow the link, so a dangling symlink answers `True`
and the branch falls through to the damage return. A genuinely vanished file
answers `False` and keeps its absent reading. Note `_iter_manifest_paths` uses
`raw.glob(...)`, which does list a dangling symlink, so the path does reach
`_read_manifest` — the bug is only in the classification.

Not fixed on the branch that found it: that branch is a location-classifier fix
and touching the store's delete path needs its own tests and its own review.

## Definition of done

- `_read_manifest` returns a damage error for a `manifest.json` that is a dangling
  symlink, and still returns the absent reading for a file that truly vanished.
- A test in `automation/shared/tests/test_store_gc.py::DamagedManifestTests`
  (beside `test_truncated_manifest_is_damage_and_its_blob_is_not_an_orphan`)
  creates a dangling-symlink manifest and asserts BOTH that
  `find_damaged_manifests` reports it and that the GC refuses to delete the blobs
  it would otherwise collect.
- `python -m unittest discover automation/shared/tests` passes.
- Vendored copies re-synced with `automation/vendoring/sync_vendored.py`.

## Scope correction (found while fixing, 2026-08-02)

Two things above are wrong; both are covered by the fix and recorded in
`verification.md`.

1. **The blast radius is wider than the manifest.** `retention.py::find_debris_dirs`
   tests `(fetch_dir / "manifest.json").exists()` with the identical blind spot, so a
   LIVE fetch directory is classified as crash debris and `execute_sweep` removes it
   with `shutil.rmtree(..., ignore_errors=True)` once it is >24h old. One broken
   symlink loses the observation record as well as the blob.
2. **"The bug is only in the classification" is interpreter-dependent.** Whether
   `raw.glob("*/**/manifest.json")` even LISTS a dangling symlink was measured as:
   3.11.15 no (a literal component goes through `pathlib._PreciseSelector`, which
   tests `Path.exists()`), 3.12.13 yes, 3.13.13 yes. The repo floor is 3.11, so a
   `_read_manifest`-only fix would have been dead code there. `_iter_manifest_paths`
   now walks with `os.walk` + `os.path.lexists`, removing the version dependence.
