# Verification — 2026-07-31-unquoted-research-date-crashes-the-tracker

Every command below was run on branch `wip/35-pipeline-parse-defects`. The
"before" runs are the same tree with only
`skills/application-tracker/scripts/status.py` reverted to its committed state,
so before and after differ by this task's change and nothing else. The fixture
tree is a throwaway under `<scratch>` with its own `JOBHUNT_CONFIG`; no
`private/` overlay is reachable and every company, slug and URL is fictional.

## Fixture

Two applications, one with the date left unquoted. Two, not one: `sorted` never
invokes the comparison on a single-element list, so a one-row fleet hides the
`TypeError` behind a wrong-looking cell.

```
<scratch>/repro/apps/6_drafted/globex-backend-engineer-20260702/meta.yaml
    company: Globex
    research_date: 2026-07-02          # NOTE: unquoted
    jobs:
      - role: Backend Engineer
        status: drafted
        location: "Springfield, ST"
        url: "https://boards.example.test/globex/backend"

<scratch>/repro/apps/6_drafted/initech-frontend-engineer-20260615/meta.yaml
    company: Initech
    research_date: "2026-06-15"        # quoted, for contrast
    ...
```

## BEFORE — default table dies after its header

```
$ JOBHUNT_CONFIG=<scratch>/repro/config.yaml .venv/bin/python \
      skills/application-tracker/scripts/status.py
──────────────────────────────────────────────────────────────────────
Company  Role               Date        Status       Channel  Files
──────────────────────────────────────────────────────────────────────
Traceback (most recent call last):
  ...
  File ".../status.py", line 1947, in print_table
    for a in sorted(apps, key=lambda x: x["date"], reverse=True):
TypeError: '<' not supported between instances of 'datetime.date' and 'str'
```

With only the Globex row present the same tree printed a row instead — and the
Date cell read `<10`, which is `date.__format__` handing the column's width spec
straight to `strftime`. A wrong fact shown without any error at all:

```
Globex   Backend Engineer  <10  drafted               —
```

## BEFORE — `--sync-log` dies AFTER the permanent append

```
$ JOBHUNT_CONFIG=<scratch>/repro/config.yaml .venv/bin/python \
      skills/application-tracker/scripts/status.py --sync-log
Traceback (most recent call last):
  ...
  File ".../status.py", line 2153, in build_created_search_entries
    day = (a.get("date") or "").strip()
AttributeError: 'datetime.date' object has no attribute 'strip'

$ find <scratch>/repro/apps -type f
<scratch>/repro/apps/0_profile/applications-log.jsonl        <-- written
<scratch>/repro/apps/6_drafted/globex-.../meta.yaml
```

The append-only skip-log was already on disk when the run died; the company
search log was never written.

## AFTER — both commands complete

```
$ JOBHUNT_CONFIG=<scratch>/repro/config.yaml .venv/bin/python \
      skills/application-tracker/scripts/status.py
──────────────────────────────────────────────────────────────────────
Company  Role               Date        Status       Channel  Files
──────────────────────────────────────────────────────────────────────
Globex   Backend Engineer   2026-07-02  drafted               —
Initech  Frontend Engineer  2026-06-15  drafted               —
──────────────────────────────────────────────────────────────────────
Total: 2 applications
RC=0

$ JOBHUNT_CONFIG=<scratch>/repro/config.yaml .venv/bin/python \
      skills/application-tracker/scripts/status.py --sync-log
Appended 2 posting event(s) -> <scratch>/repro/apps/0_profile/applications-log.jsonl
Updated company search log -> <scratch>/repro/apps/0_profile/company-search-log.yaml
RC=0

$ cat <scratch>/repro/apps/0_profile/company-search-log.yaml   # tail
- name: Globex
  aliases: [globex]
  last_successful_search: '2026-07-02'
  outcome: created
- name: Initech
  aliases: [initech]
  last_successful_search: '2026-06-15'
  outcome: created
```

## The ordering, pinned independently of this crash

The same write-before-validate window is reachable without any crash:
`_load_company_search_log_raw` deliberately `sys.exit`s on a company search log
it cannot parse, and that also ran *after* the skip-log append. The third test
drives that path, so the ordering stays fixed even if the date coercion is ever
removed.

```
$ git checkout -- skills/application-tracker/scripts/status.py     # before
$ .venv/bin/python -m unittest discover \
      -s skills/application-tracker/scripts/tests \
      -t skills/application-tracker/scripts/tests -p 'test_yaml_native_dates.py' -v
test_a_failure_after_the_scan_leaves_the_skip_log_untouched ... FAIL
test_default_table_renders_an_unquoted_research_date ... FAIL
test_sync_log_completes_with_an_unquoted_research_date ... FAIL
Ran 3 tests in 0.662s
FAILED (failures=3)

AssertionError: True is not false : the append-only skip-log must not be written
by a run that then fails: nothing regenerates it and a wrong row is repaired only
by appending a --forget-log tombstone
```

After the fix:

```
$ .venv/bin/python -m unittest discover \
      -s skills/application-tracker/scripts/tests \
      -t skills/application-tracker/scripts/tests -p 'test_yaml_native_dates.py' -v
test_a_failure_after_the_scan_leaves_the_skip_log_untouched ... ok
test_default_table_renders_an_unquoted_research_date ... ok
test_sync_log_completes_with_an_unquoted_research_date ... ok
Ran 3 tests in 0.746s
OK
```

## Audit of the rest of that path

Checked every other permanent append for the same shape:

* `backfill_log` — already derives the folder rows, the retired YAML rows, the
  merge and the tombstone set before its first `append_event`. No change needed.
* `_record_log_events` (the append `--update` / `--update-job` makes) — loads,
  builds, guards on `unreadable`, then appends. Nothing runs after. No change
  needed.
* `sync_log` — the one offender. Fixed.

## Suite

```
$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests
Ran 116 tests in 43.822s
OK
```
