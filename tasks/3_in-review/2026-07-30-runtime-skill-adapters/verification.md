# Verification — 2026-07-30-runtime-skill-adapters

<Only commands actually run and their real output. Never fabricated, never
paraphrased into "all tests pass" without the evidence. Required before a
task enters 3_in-review or 4_done.>

Verification evidence will be appended after implementation.

## Runtime adapter shape

```
$ find .agents/skills -maxdepth 1 -type l | wc -l
13
$ find .claude/skills -maxdepth 1 -type l | wc -l
13
$ find .cursor/skills -maxdepth 1 -type l | wc -l
13
$ .venv/bin/python automation/bootstrap_overlay.py --check
[ok] repository-local overlay skill excludes already correct
check complete.
```

The mounted checkout has 11 tracked public adapters plus two local overlay
adapters in each runtime tree. The detailed bootstrap output is deliberately not
copied here because local output contains overlay-only identifiers.

## Focused regression suites

```
$ .venv/bin/python -m unittest automation/publish/tests/test_skill_manifests.py
Ran 23 tests in 0.344s
OK
$ .venv/bin/python -m unittest discover -s automation/hooks/tests -t automation/hooks/tests
Ran 25 tests in 6.707s
OK
$ .venv/bin/python -m unittest automation/publish/tests/test_leak_guard.py
Ran 50 tests in 25.588s
OK
$ .venv/bin/python -m unittest discover -s automation/gardener/tests -t automation/gardener/tests
Ran 83 tests in 20.050s
OK (expected failures=1)
```

## Privacy and repository gates

```
$ .venv/bin/python automation/publish/check_public.py --staged --allow-unarmed
staged files: 51
OK: no public-repo leaks detected. Safe to publish.
$ .venv/bin/python automation/publish/check_public.py
tracked files: 784
OK: no public-repo leaks detected. Safe to publish.
$ .venv/bin/python automation/publish/sync_skill_manifests.py --check
skill manifests in sync (11 public skill(s))
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
$ .venv/bin/python automation/shared/mail/check_mail_safety.py --consumer skills/email-assistant/scripts
mail safety policy: PASS
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (9 checks clean)
$ .venv/bin/python automation/gardener/verify_links.py --require-roots --no-overlay
references: all resolve
skill symlinks: all resolve
vendor drift check: OK — vendored copies in sync
OK: links, symlinks, and vendored copies verified.
$ .venv/bin/python -m compileall -q automation skills/job-search/scripts skills/resume-writer/scripts skills/application-tracker/scripts skills/email-assistant/scripts
[no output; exit 0]
```

## Config-less checkout

The staged patch was applied to a fresh local clone with no overlay and both
configuration environment variables unset.

```
$ env -u JOBHUNT_CONFIG -u JOBHUNT_PERSONAL_TOKENS <venv-python> automation/publish/check_public.py --allow-unarmed
identity tokens:      0
supplementary tokens: 0
OK: no public-repo leaks detected. Safe to publish.
$ env -u JOBHUNT_CONFIG -u JOBHUNT_PERSONAL_TOKENS <venv-python> automation/publish/sync_skill_manifests.py --check
skill manifests in sync (11 public skill(s))
$ env -u JOBHUNT_CONFIG -u JOBHUNT_PERSONAL_TOKENS <venv-python> automation/reconcile/reconcile.py --check
reconcile: OK (8 checks clean)
$ env -u JOBHUNT_CONFIG -u JOBHUNT_PERSONAL_TOKENS <venv-python> automation/gardener/verify_links.py
references: all resolve
skill symlinks: all resolve
vendor drift check: OK — vendored copies in sync
OK: links, symlinks, and vendored copies verified.
```

## Eval gate

Canaries were not run. The only public skill instruction edit is a small
privacy-only wording change in `ask-me-anything`; it changes no routing, routine,
tool use, or output contract.
