# Verification — 2026-08-01-multiple-calendar-occurrences-per-role

## Schema migration and application metadata

The public fixture regressions cover scalar-to-list migration, all-files preflight before writes,
formatting preservation, ordered uniqueness, and calendar reference integrity. No private
application or calendar data is tracked in this repository.

```
$ python skills/application-tracker/scripts/status.py --check-metadata
Exit: 0

$ python skills/application-tracker/scripts/status.py --check-calendar
Exit: 0
```

## Regression suites

```
$ python -m unittest discover -s automation/shared/tests -p 'test_*.py'
Exit: 0

$ python -m unittest discover -s skills/application-tracker/scripts/tests -p 'test_*.py'
Exit: 0

$ python -m unittest discover -s skills/email-assistant/scripts/tests -p 'test_*.py'
Exit: 0

$ python -m unittest discover -s skills/job-search/scripts/tests -p 'test_*.py'
Exit: 0

$ python -m unittest discover -s skills/resume-writer/scripts/tests -p 'test_*.py'
Exit: 0
```

The focused three-occurrence regression creates one block, appends two independent blocks (two on
the same day), keeps aggregate progress `scheduled` after the first completion, reaches
`awaiting_result` only after the last completion, and passes calendar integrity checks throughout.

## Skill canaries

```
$ manual Sol-high regression evaluation: evals/canaries/application-tracker.yaml
Pass rate: 7/7.

$ manual Sol-high regression evaluation: evals/canaries/interview-calendar.yaml
Pass rate: 5/5.
```

Results are recorded in:

- `evals/results/application-tracker-a4e5b3d3fbd5-20260801-schema-v6.md`
- `evals/results/interview-calendar-a4e5b3d3fbd5-20260801-multiple-occurrences.md`

## Repository gates

```
$ sync_vendored.py --check
Exit: 0

$ check_mail_safety.py --consumer skills/email-assistant/scripts
Exit: 0

$ reconcile.py --check
Exit: 0

$ instruction_budget.py --strict
Exit: 0

$ verify_links.py --no-overlay
Exit: 0

$ check_public.py
Exit: 0 (armed with the private identity-token source)

$ python -m py_compile <changed Python modules>
Exit: 0
```
