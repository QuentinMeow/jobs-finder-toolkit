# Worklog — 2026-07-31-unquoted-research-date-crashes-the-tracker

## 2026-07-31 — session 1 (agent, branch `wip/35-pipeline-parse-defects`)

- Both halves reproduced at the branch tip, with one correction to the task's
  reproduction: the `TypeError` needs **two** applications. `sorted` never calls
  the comparison on a one-element list, so a single-row fleet printed a row whose
  Date cell read `<10` — `date.__format__` handing the column's width spec to
  `strftime`. That is worse than the crash it hides: a wrong fact, silently.
- Fixed at the read point (`load_application`) rather than in each consumer, so
  the `str` invariant holds once for every downstream reader. `_iso_day` covers
  `research_date` and `posted_date`; `datetime` is checked before `date` because
  it subclasses it.
- Decided NOT to make `validate_meta` reject the unquoted spelling. `research_date`
  has no validator today, the file is valid YAML saying exactly the right day, and
  once the reader normalizes, both spellings behave identically — a new hard error
  would fail `--check-metadata` on files that are not wrong. Recorded in the PR
  body as an owner question, since the opposite call is defensible and cheap.
  (`_validate_status_date` still requires a string for its own field; left alone —
  loosening a gate that the CLI writes into is a different risk.)
- The ordering half is the sharper one. `sync_log` appended to the append-only
  skip-log and only then built the company search log, so ANY failure in the
  second half landed after an unrepairable write. Restructured to derive
  everything first, then write, permanent write last.
- Audited the rest of that path for the same shape, as asked. `backfill_log` and
  `_record_log_events` already derive-then-write; `sync_log` was the only
  offender. `_load_company_search_log_raw`'s `sys.exit` reaches the same window
  without any crash, so the regression test drives THAT path — the ordering stays
  pinned even if the date coercion is ever removed.
