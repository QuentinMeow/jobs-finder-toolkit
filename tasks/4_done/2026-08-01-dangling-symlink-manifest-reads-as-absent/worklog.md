# Worklog — 2026-08-01-dangling-symlink-manifest-reads-as-absent

## 2026-08-02 — session 1 (agent)

- Reproduced the filed defect end to end before touching anything: a `manifest.json`
  that is a dangling symlink answers `is_symlink() == True`, `os.path.lexists() ==
  True`, `Path.exists() == False`; `_read_manifest` returned `(None, None)` (TRULY
  ABSENT), `find_damaged_manifests` returned `[]`, the audit called the blob an
  orphan, and `gc_store --dry-run` exited 0 reporting `orphaned blobs … 1`.
- **The filed scope missed half the blast radius.** `retention.py::find_debris_dirs`
  has the same blind spot — `(fetch_dir / "manifest.json").exists()` — so a LIVE
  fetch dir reads as crash debris, and `execute_sweep` `rmtree`s debris older than
  24h under `--execute`. One broken symlink lost the observation record as well as
  the blob. Reproduced at a 48h dir age.
- **The task's one-line closure would not have fixed the repo floor.** It asserts
  that `raw.glob("*/**/manifest.json")` lists a dangling symlink "so the path does
  reach `_read_manifest` — the bug is only in the classification". That is
  interpreter-dependent, and false on 3.11 (measured): 3.11 matches a literal path
  component with `pathlib._PreciseSelector`, which tests `Path.exists()` and drops
  the link, so `_iter_manifest_paths` never yielded it and a `_read_manifest`-only
  fix would have been dead code on the documented floor. 3.12 (what CI pins) and
  3.13 do list it. `_iter_manifest_paths` now walks with `os.walk` +
  `os.path.lexists`, which removes the version dependence entirely.
- Fix is three sites, all in `automation/shared/store/`: `_iter_manifest_paths`
  (traversal), `_read_manifest` (classification), `find_debris_dirs` (presence);
  re-vendored into the two `_vendor/store` directory copies.
- Both new tests were confirmed FAILING against the unfixed source (stashed) and
  PASSING after, on 3.11.15, 3.12.13 and 3.13.13 — see `verification.md`.
- Left alone deliberately: `automation/shared/mail/store_review.py:213` uses the same
  `raw.glob("*/**/manifest.json")` pattern, but it is a read-only reporting path that
  deletes nothing, so its symlink blind spot cannot lose data. Not in this fix.
- Next: review. Nothing pending on this task.
