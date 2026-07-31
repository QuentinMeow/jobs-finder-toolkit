# Worklog — 2026-07-31-workspace-phase-7b-company-key-on-meta

## 2026-07-30 — session 1 (agent, overlay side)

- Regenerated folder -> `company_key` for all 243 application folders from the company index as
  committed (222 keys). Spliced one `company_key:` line into each `meta.yaml` after the top-level
  `company:` line, as a byte insertion in the style of `automation/shared/metadata_editor.py`
  rather than a `safe_load`/`safe_dump` round trip, so no file was reflowed.
- Landed as PR #63 on the private overlay repo. **The public tree was untouched by that session**
  — another agent held this repo's index — so the public-side task record was handed over to be
  landed separately. That handover is what session 2 below closes.

## 2026-07-31 — session 2 (agent, public side)

- Landed the public bookkeeping: moved this folder `0_backlog` -> `3_in-review`, claimed it, and
  wrote `verification.md` and this worklog.
- **Re-ran every number before committing it** rather than copying the handover: 243 meta.yaml,
  243 carrying the field, 222 index keys, `--company-keys --strict` 243/243 keyed with 0 unkeyed
  and 0 unresolved (exit 0), `--check-metadata` 243 checked / 0 invalid, `reconcile --check
  --require-roots` 9 clean, the keying commit +1/−0 on all 243 files, and the additive-guard and
  skip-identity suites green.
- Re-measured the skip-set identity on the real tree independently, via a detached overlay
  worktree at the parent commit: 367 urls / 369 pairs, identical both ways.
- **Corrected the task file's central claim.** It said "No `meta.yaml` carries the field yet,
  which is why the check currently passes vacuously" — the inverse of reality since the overlay
  commit landed. A dated correction now sits in the Context section instead of a silent edit.
- **Two claims could not be verified and are recorded as such** in `verification.md`: the per-file
  round-trip assertion's zero-revert count (a property of the run, with no surviving artifact) and
  the diff against the proposal-era `meta_updates.tsv` (which exists in neither repository's
  history, so the task's instruction was unfollowable as written).
- Next: `handoff.py`'s scaffold dict does not emit `company_key`, so coverage decays one new
  application at a time. Filed as `2026-07-31-handoff-scaffold-omits-company-key`.
