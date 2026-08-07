# Verification — 2026-08-06-private-overlay-personal-taxonomy

## Private move fidelity

```
$ wc -l /private/tmp/jobs-private-layout-pre.tsv /private/tmp/jobs-private-layout-post-index.tsv
    3201 /private/tmp/jobs-private-layout-pre.tsv
    3201 /private/tmp/jobs-private-layout-post-index.tsv
    6402 total

$ cmp <(cut -f1,2,4 /private/tmp/jobs-private-layout-pre.tsv | LC_ALL=C sort) <(LC_ALL=C sort /private/tmp/jobs-private-layout-post-index.tsv)
EXIT=0

$ git diff --cached --name-status -M100%
3201 R100 renames
```

The comparison used NUL-safe source/destination maps saved outside both repositories. It
covered every tracked application, company-prep, registry, discovery, career, resume, and
communication source. Ignored recovery files exist only in the mounted checkout and are
called out separately for cutover; no Git or PR check can claim to have moved them.

## Focused public behavior

```
$ .venv/bin/python automation/shared/tests/test_config_accessors.py
Ran 27 tests in 0.129s

OK

$ .venv/bin/python automation/shared/tests/test_company_index.py
Ran 52 tests in 0.526s

OK

$ .venv/bin/python automation/reconcile/tests/test_reconcile.py
Ran 50 tests in 0.256s

OK

$ .venv/bin/python automation/ci/tests/test_classify_changes.py
Ran 25 tests in 0.336s

OK
```

The fictional application also passed metadata validation, resume validation, and a full
isolated DOCX/PDF render. The fictional company index produced no lint findings.
