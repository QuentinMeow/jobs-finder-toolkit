# Verification — 2026-07-22-email-progress-reconciliation

## Reconciliation and tracker suites

```
$ .venv/bin/python -m unittest discover -s skills/email-assistant/scripts/tests -p 'test_*.py'
Ran 55 tests in 0.278s
OK

$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests -p 'test_*.py'
Ran 44 tests in 9.033s
OK

$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_*.py'
Ran 288 tests in 13.769s
OK
```

## Live private-state validation

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
Checked 215 applications; 0 invalid.

$ .venv/bin/python skills/application-tracker/scripts/status.py --check-calendar
Calendar consistent; 4 entries, 4 referenced.

$ .venv/bin/python skills/email-assistant/scripts/outlook_email.py store-review
categorized_messages: 615; hydrated_messages: 615; unavailable_messages: 0
review_complete: true; store_stale: false
```

## Remaining cutover gate

```
Five consecutive zero-mismatch store/live comparisons: not yet complete.
Automatic store-first cutover: deliberately not performed.
```

## Owner-confirmed ambiguity follow-up

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
Checked 215 applications; 0 invalid.

$ .venv/bin/python skills/application-tracker/scripts/status.py --check-calendar
Calendar consistent; 5 entries, 5 referenced.

$ .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (6 checks clean)
```
