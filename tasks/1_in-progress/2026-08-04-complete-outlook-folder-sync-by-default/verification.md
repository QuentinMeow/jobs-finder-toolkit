# Verification — 2026-08-04-complete-outlook-folder-sync-by-default

## Email-assistant suite

```
$ .venv/bin/python -m unittest discover -s skills/email-assistant/scripts/tests -p 'test_*.py'
.............................................................................................
----------------------------------------------------------------------
Ran 93 tests in 3.435s

OK
```

## Canonical mail tests

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_mail*.py'
...........................
----------------------------------------------------------------------
Ran 27 tests in 0.873s

OK
```

## Mail safety and vendoring

```
$ .venv/bin/python automation/shared/mail/check_mail_safety.py --consumer skills/email-assistant/scripts
mail safety policy: PASS — 1 provider folder(s) [outlook_graph], 2 consumer file(s)

$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## Live folder coverage

```
$ .venv/bin/python skills/email-assistant/scripts/outlook_email.py sync-store
mode: mixed; 11 folders; 9 messages added from newly discovered folders

$ .venv/bin/python skills/email-assistant/scripts/outlook_email.py store-staleness
review_complete: true; store_stale: false; all 11 folders sync_completed: true

$ .venv/bin/python skills/email-assistant/scripts/outlook_email.py store-search --query <job-requisition-id> --include-content
audit_complete: true; 9,860 current messages scanned; 0 unavailable; integrity ok
```
