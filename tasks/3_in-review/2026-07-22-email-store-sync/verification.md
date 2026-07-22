# Verification — 2026-07-22-email-store-sync

## Email unit suite

```
$ .venv/bin/python -m unittest discover -s skills/email-assistant/scripts/tests -p 'test_*.py'
Ran 55 tests in 0.278s
OK
```

## Live 30-day sync and bounded store review

```
$ .venv/bin/python skills/email-assistant/scripts/outlook_email.py sync-store --days 30 --full
inbox: 553; sentitems: 61; drafts: 1; total: 615

$ .venv/bin/python skills/email-assistant/scripts/outlook_email.py store-review
stored_messages: 615; hydrated_messages: 615; unavailable_messages: 0
manifests/raw_blobs/derived/index: 615/615/615/615; attachments_checked: 128
store_stale: false; review_complete: true; integrity.ok: true
```

## Safety, privacy, and vendoring

```
$ .venv/bin/python automation/shared/mail/check_mail_safety.py
mail safety policy: PASS

$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ .venv/bin/python automation/publish/check_public.py
OK: no public-repo leaks detected. Safe to publish.
```
