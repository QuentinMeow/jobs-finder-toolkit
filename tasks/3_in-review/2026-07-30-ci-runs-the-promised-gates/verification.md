# Verification — 2026-07-30-ci-runs-the-promised-gates

Every added CI step was run in a detached worktree that reproduces CI's
environment — **no `config.yaml`, no `private/` overlay** — driven by the primary
checkout's venv. Home paths redacted to `<repo-root>` / `<scratch>`. The full
gate run at the bottom is from the primary checkout.

## The worktree really is config-less and overlay-less

```
$ git worktree add --detach <scratch>/ci_wt HEAD
HEAD is now at 9931993 Measure every AGENTS.md in the tree, not just root and skills
$ ls -a <scratch>/ci_wt | grep -E '^(private|config)'
config.example.yaml
```

Only the tracked example config is there: no `config.yaml`, no `private/`.

## Step 2a — mail send-less policy (the pre-commit invocation)

```
$ .venv/bin/python automation/shared/mail/check_mail_safety.py \
    --consumer skills/email-assistant/scripts
mail safety policy: PASS
rc=0
```

## Step 2e — instruction-file budget (strict)

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
Instruction-file budget (lines; est. tokens = bytes / 4):
FILE                                           LINES  BYTES  ~TOKENS     BUDGET  STATUS
---------------------------------------------  -----  -----  -------  ---------  ------
AGENTS.md                                        314  24927     6231        500      ok
docs/designs/AGENTS.md                             8    514      128  100+4096B      ok
...
OK: all instruction files within budget.
rc=0
```

`docs/designs/AGENTS.md` is the row that did not exist before: the leaf tier,
8 lines / 514 bytes against 100 lines + 4096 bytes. It is the only leaf in the
tree, so extending the glob fails nothing that used to pass. The private
overlay's rows are absent here, as they are in CI — they are measured only when
an overlay is mounted.

## Step 2c — the budget gate's own unit tests (new)

```
$ .venv/bin/python -m unittest discover automation/metrics/tests
----------------------------------------------------------------------
Ran 8 tests in 0.077s

OK
```

## Step 6b — the four suites that never ran in CI

```
$ JOBHUNT_CONFIG=<scratch>/ci_wt/config.example.yaml \
    .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests
Ran 77 tests in 63.227s
OK

$ .venv/bin/python -m unittest discover -s skills/email-assistant/scripts/tests
Ran 67 tests in 2.020s
OK

$ .venv/bin/python -m unittest discover -s skills/behavioral-interview-prep/scripts/tests
Ran 12 tests in 6.487s
OK

$ .venv/bin/python -m unittest discover -s skills/github-workflow/scripts/tests
Ran 15 tests in 1.418s
OK
```

171 tests, no failures, no suite needing the overlay. Which suites need
`JOBHUNT_CONFIG` was settled by reading them, then confirmed by running each
both with and without it: only application-tracker imports `config` (six of its
seven modules do), and all four pass either way in a checkout with no
`config.yaml`, because the loader falls back to `config.example.yaml`.

Local cost: about **73 s**, ~63 s of it the application-tracker suite. On the
GitHub runner the same four take **15 s** — measured on the PR's own run, below.

## Measured on CI, not predicted from local timings

```
$ gh api repos/<owner>/<repo>/actions/runs/<run-id>/jobs --jq \
    '.jobs[] | select(.name=="build") | .steps[] | ...'
Mail send-less policy (blocking): 1s
Reconciler + gardener + overlay-hook + recall-audit + metrics unit tests: 4s
Instruction-file budget (strict): 0s
Application-tracker, email-assistant, behavioral-prep, github-workflow tests: 15s
```

Every step of the `build` job reported `success`, including all four added ones;
whole job 1 m 59 s. The local worktree over-estimated the added cost by ~4x, so
the honest figure for the PR description is the CI one.

## The workflow file still parses, and the new steps are where they should be

```
$ .venv/bin/python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml'));
  names=[s['name'] for s in d['jobs']['build']['steps'] if 'run' in s];
  print(len(names),'run steps'); [print(' -',n) for n in names]"
18 run steps
 - Install Python dependencies
 - Install LibreOffice (DOCX -> PDF for the example render)
 - Vendored-copy drift check
 - Compile all Python
 - Mail send-less policy (blocking)
 - Reconciler (process-layer schemas)
 - References + markdown links
 - Reconciler + gardener + overlay-hook + recall-audit + metrics unit tests
 - Public review gate (unreviewed public changes)
 - Instruction-file budget (strict)
 - Example render + validate (fake "Jordan Rivers" config)
 - Resume-writer unit tests + multi-experience E2E
 - Shared-module unit tests
 - Validate example store + fixture size
 - Job-search unit tests + filter variant corpus
 - Application-tracker, email-assistant, behavioral-prep, github-workflow tests
 - Leak-guard + exporter unit tests
 - Public leak guard (blocking; must be clean on this public repo)
```

## Full local gate (primary checkout, with the overlay mounted)

Run at commit 2 of 3, before the ledger row acknowledging it existed:

```
$ zsh <scratch>/gate.sh
===== gates =====
PASS  vendor-drift
PASS  byte-compile
PASS  reconcile
PASS  leak-guard
FAIL  review-gate (exit 1)
PASS  instruction-budget
PASS  verify-links
PASS  mail-safety
===== unit suites =====
PASS  tests:reconcile
PASS  tests:gardener
PASS  tests:hooks
PASS  tests:shared
PASS  tests:publish
PASS  tests:store-example
PASS  tests:resume-writer
PASS  tests:job-search
PASS  filter-variants
PASS  tests:app-tracker
PASS  tests:github-wf
===== export dry-run =====
PASS  export-strict
1 STEP(S) FAILED
```

The one failure is the review gate's one-commit lag — it was asking for the row
that this commit carries. Re-run after the branch's closing ledger commit is
ALL GREEN.

