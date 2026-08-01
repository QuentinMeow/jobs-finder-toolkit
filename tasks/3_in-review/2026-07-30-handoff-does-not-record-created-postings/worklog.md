# Worklog — 2026-07-30-handoff-does-not-record-created-postings

## 2026-07-31 — session 1 (agent)

- Extracted the per-posting flattening out of `status.py`'s `build_log` into
  `automation/shared/skip_log.py` (`posting_row`, `posting_rows`) and moved the append
  policy there too (`record_postings`, was `status.py::_upsert_log_rows`). Both moves are
  in the module that already owns `POSTING_KEYS`, so there is no new vendoring target: the
  file was already vendored into exactly the two skills that write the log.
- `handoff._run_group` now calls `_record_created_postings` as its LAST step, after the
  folder, `meta.yaml` and the location gate. Ordering argument (crash residue asymmetry),
  idempotency and concurrency all live in that function's docstring.
- Filed the exit-3 / exit-1 policy call as
  `message-queue/needs-human/decisions/handoff-records-non-clean-scaffolds.md`. Default
  path (implemented): record every folder actually created, and print the
  `--forget-log` un-skip command with its argument filled in on a non-zero exit.
- 11 new handoff tests + 16 new shared tests. `--sync-log` appending **zero** rows over a
  folder handoff just created is the anti-drift assertion — it fails if the two writers
  disagree on any of the six stored fields.
- Surprise: `--select "Company"` over an all-mismatch group exits 1, not 3 — the bulk path
  maps `_run_group`'s 3 to a `location_mismatch` count and returns its own code. Adjusted
  the test to assert the observable facts (no folder, no log) instead of the code.
- Next: review + merge. Nothing blocked.
