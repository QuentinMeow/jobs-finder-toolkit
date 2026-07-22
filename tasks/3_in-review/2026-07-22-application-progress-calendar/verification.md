# Verification — 2026-07-22-application-progress-calendar

Commands actually run on branch `email/stage-2-progress-calendar`
(worktree without the private overlay; `<venv>` =
`.venv/bin/python (repo venv, absolute path elided)`; JOBHUNT_CONFIG
pointed at `config.example.yaml` where noted). Output shown verbatim (trimmed
to the summary lines).

## Vendoring + compile

```
$ <venv> automation/vendoring/sync_vendored.py --check
vendored copies in sync
$ <venv> -m compileall -q automation skills/*/scripts
COMPILE-OK
```

## Unit suites (all green)

```
$ <venv> -m unittest discover -s automation/shared/tests -t automation/shared/tests
Ran 260 tests in 12.301s
OK
$ <venv> -m unittest discover -s automation/publish/tests -t automation/publish/tests
Ran 30 tests in 5.341s
OK
$ <venv> -m unittest discover -s skills/application-tracker/scripts/tests -t ...
Ran 42 tests in 8.426s
OK
$ <venv> -m unittest discover -s skills/job-search/scripts/tests -t ...
Ran 210 tests in 29.057s
OK
$ <venv> -m unittest discover -s skills/outlook-email-assistant/scripts/tests -t ...
Ran 23 tests in 0.022s
OK
$ JOBHUNT_CONFIG=$PWD/config.example.yaml <venv> -m unittest discover \
    -s skills/resume-writer/scripts/tests -t ...
Ran 86 tests in 17.603s
OK
```

New coverage includes: v4->v5 migration (formatting preserved, already-v5 /
pre-v4 / unretainable-facts fail closed), fleet migration preview->write with
`--check-metadata` rejecting v4 after cutover, progress transitions (closed
coupling both ways, never-guess state mapping), `--update-progress`
transactional meta+calendar with no folder move, scheduled-without-time
fail-closed, calendar byte-preservation of unmarked text, reschedule fixture
keeping the superseded occurrence, cancellation without rejection, malformed
marker / duplicate id / missing entry fail closed, calendar checksum race
rolling the meta write back (no one-sided write), `--phase`/`--progress-state`
filters, pipeline action-needed/overdue-waiting output.

## Migration of the tracked fixtures (dogfooded)

```
$ JOBHUNT_CONFIG=.../config.example.yaml <venv> skills/application-tracker/scripts/migrate_to_v5.py
meta.yaml v4 -> v5 migration (DRY RUN)
would migrate example-corp-senior-software-engineer
...unified diff shown...
Scanned 1 applications; 1 would migrate; 0 need manual attention.
$ ... migrate_to_v5.py --write --quiet-diff
Scanned 1 applications; 1 migrated; 0 need manual attention.
$ ... migrate_to_v5.py --slug examples/fixtures/resume-writer/_test_application_multi-experience/application --write
Scanned 1 applications; 1 migrated; 0 need manual attention.
$ ... status.py --check-metadata
ok      example-corp-senior-software-engineer
Checked 1 applications; 0 invalid.
$ ... status.py --check-calendar
Calendar .../examples/applications/0_profile/calendar.md: consistent; 0 entries, 0 referenced.
```

## Example render gate (with example config)

```
$ JOBHUNT_CONFIG=.../config.example.yaml <venv> skills/resume-writer/scripts/render.py \
    examples/applications/6_drafted/example-corp-senior-software-engineer/
Validating:
  ✓ all checks passed (0 warning(s))
```
(The regenerated binary artifacts were reverted afterwards — only meta.yaml
changed in this branch.)

## Process + publish gates

```
$ <venv> automation/reconcile/reconcile.py --check
reconcile: OK (6 checks clean)
$ <venv> automation/publish/check_public.py
OK: no public-repo leaks detected. Safe to publish.
$ <venv> automation/metrics/instruction_budget.py --strict
skills/application-tracker/SKILL.md   483 lines   BUDGET 600   ok   (all files ok)
$ <venv> automation/maintenance/gardener/gardener.py verify-links
  BROKEN references: 1
    AGENTS.md:98  ->  skills/coding-interview/
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync
```

The single verify-links finding is the pre-existing private-overlay pointer
(`skills/coding-interview/` exists only when `private/` is mounted; this
worktree has no overlay). It is present on the base branch and untouched by
this change; it resolves in the primary checkout.

## Canary gate (NOT RUN — must gate the merge)

The application-tracker SKILL.md schema-section edit is **behavioral** (new
commands, schema v5). Canaries (`evals/application-tracker/canaries.yaml`)
could not be executed from this environment (they require live agent
sessions). **They must be run and pass — with the run recorded in
`evals/results/` per `evals/README.md` — before this branch merges.**

## Owner follow-up (real data)

The private overlay is not reachable from this worktree. Before the next
tracker run on real data, the owner must migrate the private fleet:

```
.venv/bin/python skills/application-tracker/scripts/migrate_to_v5.py           # preview diffs
.venv/bin/python skills/application-tracker/scripts/migrate_to_v5.py --write   # apply
.venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
```
