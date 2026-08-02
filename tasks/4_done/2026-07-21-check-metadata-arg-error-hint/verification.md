# Verification — 2026-07-21-check-metadata-arg-error-hint

All output below is real, captured on 2026-07-31 from the branch
`fix/10-company-research-correctness`. Absolute paths are redacted to `<repo-root>`.

## The defect, reproduced before the fix

```
$ git stash && .venv/bin/python skills/application-tracker/scripts/status.py \
      --check-metadata applications/6_drafted/foo/ ; echo "exit=$?"
usage: status.py [-h] [--json] [--update SLUG STATUS]
                 ... (full usage block) ...
                 [--statuses STATUSES]
status.py: error: unrecognized arguments: applications/6_drafted/foo/
exit=2
```

No hint, and the parser defines zero positional arguments, so the message reads like
a bad path when the call shape is what is wrong.

## The misuse form now names the fix

```
$ .venv/bin/python skills/application-tracker/scripts/status.py \
      --check-metadata applications/6_drafted/foo/
status.py: error: unrecognized arguments: applications/6_drafted/foo/
status.py: hint: --check-metadata scans every application under the active config's applications root and takes no path argument; narrow it with --statuses <folder>, or target one application with --enrich-metadata <slug-or-path>.
exit=2
```

## A scan flag with no per-application counterpart offers only `--statuses`

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --check-locations some/slug
status.py: error: unrecognized arguments: some/slug
status.py: hint: --check-locations scans every application under the active config's applications root and takes no path argument; narrow it with --statuses <folder>.
```

## An unknown argument with no scan flag set is unchanged

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --bogus
status.py: error: unrecognized arguments: --bogus
```

## Correct forms still work

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
ok      example-corp-senior-software-engineer
Checked 1 applications; 0 invalid.
exit=0
```

## Tracker suite (82 tests before this change, 88 after)

```
$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests \
      -t skills/application-tracker/scripts/tests
----------------------------------------------------------------------
Ran 88 tests in 22.767s

OK
```
