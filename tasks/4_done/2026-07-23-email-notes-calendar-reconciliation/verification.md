# Verification — 2026-07-23-email-notes-calendar-reconciliation

## Email-assistant unit and safety suite

```
$ .venv/bin/python -m unittest discover -s skills/email-assistant/scripts/tests -v
Ran 56 tests in 0.673s
OK

$ .venv/bin/python automation/shared/mail/check_mail_safety.py \
    --consumer skills/email-assistant/scripts
mail safety policy: PASS
```

## Skill forward tests

```
$ two isolated gpt-5.6-terra/high forward-test agents against mocked example data
email-assistant canaries: 7/7 rubric pass
```

Result: `evals/results/email-assistant-e3a90ec4be66-20260723-notes-calendar.md`.

The generic skill-creator `quick_validate.py` was also run. It rejected this repository's required
`visibility` frontmatter extension as an unknown key; no project field was removed to satisfy an
incompatible generic validator.

## Application and note integrity

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
236 applications checked, 0 invalid

$ private changed-note schema audit
changed_notes=58 schema_bad=0 timeline_provider_ids=0

$ rg '^### .* — (Inbound|Outbound|Sent) —' private/applications -g 'notes.md' | wc -l
131
```

`status.py --check-locations` also ran: 236 total, 187 match, 25 mismatch, 24 review. Its nonzero
result is the existing portfolio-wide location backlog; this email/status task created no posting
or location data.

## Diff integrity

```
$ git diff --check
(no output)

$ git -C private diff --check
(no output)

$ .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (6 checks clean)

$ .venv/bin/python automation/publish/check_public.py
OK: no public-repo leaks detected. Safe to publish.
```
