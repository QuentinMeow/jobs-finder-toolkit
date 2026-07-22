# Verification — 2026-07-22-email-provider-contract

Commands actually run on branch `email/stage-1-provider-contract`
(2026-07-22, macOS, repo venv Python 3.13; worktree without the private
overlay). Output trimmed to the result lines; nothing fabricated.

## Vendored-copy drift

```console
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## Byte-compile

```console
$ .venv/bin/python -m compileall -q automation skills/job-search/scripts \
    skills/resume-writer/scripts skills/application-tracker/scripts \
    skills/email-assistant/scripts
(exit 0)
```

## Unit suites

```console
$ .venv/bin/python -m unittest discover -s skills/email-assistant/scripts/tests
Ran 24 tests in 0.030s
OK

$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 246 tests in 16.040s
OK

$ .venv/bin/python -m unittest discover automation/publish/tests
Ran 30 tests in 8.257s
OK
```

The 24 skill tests include every pre-existing Outlook draft-only test
(route rejection, false-`isDraft` fail-closed, Sent-reply and existing-draft
duplicate preflights, pagination preflight, scope pin, CLI surface) plus the
new synthetic-conformance test. The 246 shared tests include 12 new
conformance/contract tests and 10 new checker tests with the planted
send-capable provider fixtures.

## Folder-walking mail-safety checker (replaces check_draft_only.py)

```console
$ .venv/bin/python automation/shared/mail/check_mail_safety.py \
    --consumer skills/email-assistant/scripts
mail safety policy: PASS
```

Planted-fixture proof (fixture materialized inside the test, never shipped):

```console
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p "test_mail*" -v
test_planted_send_capable_provider_fails ... ok   # sendMail route allowed by policy -> caught
test_send_named_function_fails ... ok
test_sdk_import_fails ... ok                      # googleapiclient import -> caught
test_transport_bypass_import_fails ... ok         # requests import -> caught
test_cross_provider_import_fails ... ok
test_missing_route_policy_fails ... ok
test_outlook_scope_drift_fails ... ok
Ran 22 tests in 0.212s
OK
```

## Provider conformance (synthetic; canonical + vendored entry points)

```console
$ .venv/bin/python automation/shared/mail/contract/conformance.py
mail conformance [outlook_graph synthetic]: PASS (19 passed, 0 failed)

$ .venv/bin/python skills/email-assistant/scripts/_vendor/mail/contract/conformance.py
mail conformance [outlook_graph synthetic]: PASS (19 passed, 0 failed)
```

The read-only `--live` mode is implemented (`--provider outlook_graph
--live`; asserts a GET-only audit log) but NOT run here — it needs the real
keyring login and is the documented owner action.

## Instruction budget / reconciler / leak guard

```console
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.

$ .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (6 checks clean)

$ .venv/bin/python automation/publish/check_public.py
OK: no public-repo leaks detected. Safe to publish.
```

## verify-links

```console
$ .venv/bin/python automation/maintenance/gardener/gardener.py verify-links
  BROKEN references: 1
    AGENTS.md:98  ->  skills/coding-interview/
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync
```

The single finding is caused ONLY by the missing private overlay in this
worktree: `skills/coding-interview` is the gitignored symlink
`bootstrap_overlay.py` creates when `private/` is mounted. It pre-exists this
change and resolves in any overlay-mounted checkout.

## CLI smoke (behavior unchanged)

```console
$ JOBHUNT_CONFIG="$PWD/config.example.yaml" \
    .venv/bin/python skills/email-assistant/scripts/outlook_email.py doctor
{ "draft_only": true, ... "oauth_scopes": ["https://graph.microsoft.com/User.Read",
  "https://graph.microsoft.com/Mail.ReadWrite"], "tenant": "consumers" }
(exit 2 — account unset in the example config, same as before the refactor)
```
