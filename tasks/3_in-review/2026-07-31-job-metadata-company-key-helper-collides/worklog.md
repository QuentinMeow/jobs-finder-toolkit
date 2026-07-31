# Worklog — 2026-07-31-job-metadata-company-key-helper-collides

## 2026-07-31 — session 1 (agent, PR 09)

- Claimed from `0_backlog`, done as a pure rename, moved to `3_in-review`.
- Three edits in `automation/shared/job_metadata.py`: the `def`, the local, and the set
  comprehension that used both. Re-vendored into resume-writer, application-tracker and
  job-search; `sync_vendored.py --check` clean.
- The proof, not the edit, was the work. A rename cannot be trusted on inspection when the thing
  renamed is a normalizer, so `lookup_company_level` was run over 7744 `(company, title)` cases —
  every stripped suffix in leading, medial, trailing and comma'd position, two references — and
  the canonical JSON of all 7744 answers hashed. Same sha256 before and after, and from each of
  the three vendored copies. 1004 of the cases match a level row, which is what stops the
  comparison being two piles of `null`.
- The task suggested a comment naming the three disagreeing normalizers rather than unifying
  them. Followed. Checking the numbers while writing it turned up one error in the task text:
  `registry._LEGAL_SUFFIXES` holds 15 entries, not 14. The comment names the constant and dates
  the count so the next drift is visible instead of silently wrong.
- Nothing here is a behaviour change, so there is no test that fails before and passes after —
  the identical digest IS the evidence, and a test asserting the new name would only pin the
  rename to itself.
- Next: none from this task. The open question it leaves — whether the three normalizers should
  be reconciled at all — needs its own before/after corpus over the level cache and the registry,
  and was deliberately not started here.
