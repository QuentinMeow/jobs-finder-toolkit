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

## Full public gate suite

```
$ automation/gates/run_gates.py --impact-from origin/main --jobs 8
ALL GREEN (29 gates)
EXIT=0
```

This ran from a config-less detached worktree at `e08c2c9`. It included the full
LibreOffice DOCX/PDF example render, resume, shared, job-search, application, publish,
export, leak, link, hook, reconciler, and policy suites. GitHub subsequently reported every
public PR check passing, including `pdf-tests`, `policy`, `secret-scan`, and all test lanes.

## Private guard and baseline findings

All ten private commits passed the overlay pre-commit guard. Every staged batch stayed
within its standard 500-file / 128-MiB limits; the largest was 369 files / 115,835,881 bytes.

Read-only private tracker checks still expose existing application-status, metadata,
location-classification, generated-calendar, and isolated company-index-routing findings.
The refactor did not rewrite owner statuses or generated records to conceal those unrelated
findings; existing retry/queue records cover the status and calendar debt.

## Worktree isolation and publication

```
mounted tracked patch before = 09b4658691cb58fe9dd79aa3f5a84d55bb3317aa5189fd6b58027da8143cb022
mounted tracked patch after  = 09b4658691cb58fe9dd79aa3f5a84d55bb3317aa5189fd6b58027da8143cb022
mounted untracked handover   = 46fe50883700bfecba4405d30fdb855c8ef28ca94c34fca6ce6115d3f9a6ed3c
```

- Public toolkit: PR #321
- Private overlay: PR #93

## Post-merge local reconciliation

```
$ shasum -a 256 /private/tmp/private-local-before-reconcile.patch
09b4658691cb58fe9dd79aa3f5a84d55bb3317aa5189fd6b58027da8143cb022  /private/tmp/private-local-before-reconcile.patch

$ .venv/bin/python skills/application-tracker/scripts/status.py --check-metadata --statuses in_progress
Checked 16 applications; 0 invalid.
EXIT=0

$ .venv/bin/python skills/application-tracker/scripts/status.py --check-calendar
Calendar private/me/interviews/calendar.md: consistent; 27 entries, 27 referenced.
EXIT=0

$ .venv/bin/python skills/application-tracker/scripts/status.py --refresh-calendar --html
Calendar private/me/interviews/calendar.md: already uses the current layout.
EXIT=0

$ rsync -anic --itemize-changes private/companies/ private/me/interviews/companies/
<no output>
EXIT=0
```

The checksum-enabled `rsync` comparison ran after a non-overwriting copy. The empty result proves
that every ignored file remaining in the retired company root has the same content at the new
destination; the source remains for owner-only retirement.

Private PR #94 merged through `merge_stack.py` on track B and was independently confirmed by
`GET /pulls/94/merge -> 204`.
