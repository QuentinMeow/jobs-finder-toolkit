# Verification — 2026-08-02-soffice-crashes-under-codex-sandbox

## Shared macOS capability probe

```text
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_libreoffice_env.py' -v
Ran 10 tests in 0.011s
OK
```

## Converter retry and signal classification

```text
$ .venv/bin/python -m unittest discover -s skills/resume-writer/scripts/tests -p 'test_pdf_convert.py' -v
Ran 18 tests in 0.065s
OK
```

The suite includes a mocked `CompletedProcess` terminated by `SIGABRT`, positive-nonzero and
double-launch-failure cases, the existing exit-0 invalid-PDF retries, and a multi-document denial
that starts neither the thread pool nor `soffice`.

## Gate-runner fail-versus-skip behavior

```text
$ .venv/bin/python -m unittest discover -s automation/gates/tests -p 'test_run_gates.py' -v
Ran 47 tests in 0.654s
OK
```

## Full shared regression suite

```text
$ .venv/bin/python -m unittest discover -s automation/shared/tests
Ran 674 tests in 31.871s
OK
vendored copies in sync
```

## Known denied sandbox refuses before launch

```text
$ .venv/bin/python automation/gates/run_gates.py --only example-render --tail 20
FAIL   example-render  exit 1     0.0s
LOG: -
No LibreOffice process was started. PDF conversion and one-page PDF checks did not run:
this is FAIL, not SKIP or PASS.
RED: example-render (1 of 1 failed)
```

## Real PDF gates outside the inherited sandbox

The working tree was copied to `/private/tmp/soffice-fix.WZpIjX` without `.git`, `.venv`,
`private/`, `local/`, or `config.yaml`; an empty `.git/` marker let the runner resolve that isolated
public root. The repository venv ran the copied code with scoped sandbox escalation. The commands
below normalize the repository and isolated-copy prefixes; the output is otherwise verbatim.

```text
$ <repo>/.venv/bin/python \
    <isolated-public-copy>/automation/gates/run_gates.py \
    --only example-render --tail 30
PASS   example-render  exit 0    16.7s
DOCX: examples/applications/6_drafted/example-corp-senior-software-engineer/source/Jordan_Rivers_Software_Engineer_Resume.docx
PDF:  examples/applications/6_drafted/example-corp-senior-software-engineer/Jordan_Rivers_Software_Engineer_Resume.pdf
Cover PDF [Senior Software Engineer, Platform]: examples/applications/6_drafted/example-corp-senior-software-engineer/Jordan_Rivers_Cover_Letter_Senior_Software_Engineer_Platform.pdf
Validating:
  ✓ all checks passed (0 warning(s))
ALL GREEN (1 gates)
```

```text
$ <repo>/.venv/bin/python \
    <isolated-public-copy>/automation/gates/run_gates.py \
    --only tests-resume-writer --tail 40
PASS   tests-resume-writer  exit 0    24.1s
Ran 105 tests in 23.671s
OK
ALL GREEN (1 gates)
```

No real application overlay was copied or read by either run. Only the fictional public example
was rendered in the isolated directory.

## Vendoring and diff hygiene

```text
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ git diff --check
<no output>
```

Eval gate: not triggered — no `SKILL.md`, `LESSONS.md`, or `reference.md` changed.

## Process-layer and listing checks

```text
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (10 checks clean)

$ .venv/bin/python automation/gates/run_gates.py --list
LIST_EXIT=0
example-render ... FAIL HERE: ... No LibreOffice process was started. PDF conversion and
one-page PDF checks did not run: this is FAIL, not SKIP or PASS.

$ git diff --check
<no output>
```
