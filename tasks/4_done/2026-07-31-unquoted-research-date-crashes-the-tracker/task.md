# An unquoted `research_date:` crashes the status table and the company search log

- **Priority**: P1 (this round)
- **Area**: tracker
- **Source**: found while building fixtures for the corrupt-`meta.yaml` fix (PR "the
  tracker stops guessing at a `meta.yaml` it could not read"); reproduced at `47a15d4`,
  so it predates that PR and is out of its scope.
- **Claimed-by**: agent (branch `wip/35-pipeline-parse-defects`)

## Goal

A `meta.yaml` that is perfectly valid YAML but writes `research_date: 2026-07-02`
without quotes must not crash `status.py`. Today it does, in two places, with a
`TypeError`/`AttributeError` traceback rather than a diagnosis.

## Context

`yaml.safe_load` resolves an unquoted `YYYY-MM-DD` scalar to a `datetime.date`, not a
string. `load_application` then does `info["date"] = info["research_date"]`, so that
one application's `date` is a `date` object while every other application's is a
`str` (theirs comes from the slug parse, or from a quoted value). Two consumers break:

* `print_table` — `sorted(apps, key=lambda x: x["date"])` raises
  `TypeError: '<' not supported between instances of 'str' and 'datetime.date'`, so
  the bare `status.py` fleet view dies after printing its header.
* `build_created_search_entries` — `(a.get("date") or "").strip()` raises
  `AttributeError: 'datetime.date' object has no attribute 'strip'`, which aborts
  `--sync-log` *after* it has already appended to the append-only skip-log. The
  company search log is then never updated for that run.

The team already knows about this class of value in one place and only one:
`_log_row`'s docstring in `skills/application-tracker/scripts/status.py` explains
that it stringifies non-string scalars precisely because "an unquoted
`research_date:` in `meta.yaml` loads as a `datetime.date`, which `json.dumps`
refuses outright". The same coercion was never applied where `date` is read.

Reproduction (throwaway tree, no private data — this is the fixture the
corrupt-`meta.yaml` work used before the date was quoted to stay in scope):

```
apps/6_drafted/globex-backend-engineer-20260702/meta.yaml:
    company: Globex
    research_date: 2026-07-02        # NOTE: unquoted
    jobs:
      - {role: Backend Engineer, status: drafted, location: "Springfield, ST",
         url: "https://boards.example.test/globex/backend"}

JOBHUNT_CONFIG=<that tree>/config.yaml .venv/bin/python \
    skills/application-tracker/scripts/status.py            # TypeError
JOBHUNT_CONFIG=<that tree>/config.yaml .venv/bin/python \
    skills/application-tracker/scripts/status.py --sync-log # AttributeError
```

Likely fix: normalize once, in `load_application`, where `research_date` is copied
onto `info["date"]` — coerce a `date`/`datetime` to its ISO string there, so every
consumer keeps seeing the `str` it already assumes. Check whether
`job_metadata.validate_meta` should also call an unquoted date an error, or whether
accepting both spellings is the friendlier contract; the fix is cheap either way and
they are not mutually exclusive.

## Definition of done

- [ ] `status.py` (default table) and `status.py --sync-log` both succeed against a
      tree containing an unquoted `research_date:`, with the date rendered as
      `YYYY-MM-DD`.
- [ ] A regression test in `skills/application-tracker/scripts/tests/` covers both
      commands against that fixture and fails against the current code.
- [ ] `.venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests`
      passes.
