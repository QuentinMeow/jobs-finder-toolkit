# Verification — 2026-07-31-gate-documented-commands

Every block below is real output from the branch. The acceptance test is the last
one: the two commands the task file diagnosed, put back exactly as they were on
`main`, both caught.

**Corrected 2026-07-31 on the stack tip `40871e6`.** Every behavioural claim reproduces —
the acceptance test was re-planted and re-run, and the finding triage still holds
finding-for-finding. **Every count was wrong**, and not merely stale: the block was
captured on the isolated `main`-based worktree this change was authored in, so the figures
do not describe the authoring commit `adff448` either.

## The whole tree: 306 commands read, 0 broken

| | recorded | actual at `adff448` | at tip `40871e6` |
|---|---|---|---|
| tracked `.md` files | 384 | **395** | 424 |
| documented commands read | 284 | **292** | 306 |
| references verified | 2375 | **2426** | 2552 |
| advisory | 36 | **41** | 42 |
| permitted | 106 | 106 | 107 |

At the tip:

```
$ .venv/bin/python automation/gardener/verify_links.py --no-overlay
  refs + markdown links checked across 424 tracked .md files
  documented commands read from fenced code blocks: 306
  ...
  skipped refs — fenced command whose script names no repo path (bare name, <placeholder>/ dir, scratch tree): 27
  ...
  references: 0 broken of 2552 verified · 42 advisory · 107 permitted · 1201 refs NOT verified in this tree (classes above)
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync

  OK: 2552 references, the skill symlinks and the vendored copies verified.
```

**Why this number keeps moving, and how to read it.** `verify_links` counts references
across every tracked `.md`, so any commit that adds documentation moves it — including the
2026-07-31 correction pass that rewrote this block, which adds 14 references of its own
and takes the tree to **2566**. Every figure in this file therefore names the commit it was
measured at. A bare reference count with no SHA beside it is not evidence of anything.

## Every command finding it produces, triaged

8 findings, **8 true positives, 0 false positives, 0 fatal**. Each names a script
or a flag that genuinely does not exist; the tier each lands in is decided by what
its source document is for, with no special case added for commands.

Re-run at the tip: still exactly 8, still 6 advisory + 2 permitted, still 0 fatal. The
only line that moved is the fourth, whose task was promoted `0_backlog` → `3_in-review`.

```
  advisory (plans name targets that do not exist yet)
    docs/designs/filtering-variant-safeguards/execution-plan.md:348  [command]  ->  automation/maintenance/gardener/gardener.py   -> did you mean automation/gardener/gardener.py?
    docs/designs/filtering-variant-safeguards/execution-plan.md:381  [command]  ->  automation/maintenance/gardener/gardener.py   -> did you mean automation/gardener/gardener.py?
    docs/designs/skill-script-sharing/approach-3-cli-service-boundary.md:56  [command]  ->  scripts/tools/location_cli.py
    tasks/3_in-review/2026-07-31-verify-links-reads-no-fenced-command/task.md:26  [command]  ->  automation/maintenance/gardener/gardener.py   -> did you mean automation/gardener/gardener.py?
    tasks/3_in-review/2026-07-21-check-metadata-arg-error-hint/verification.md:42  [command-flag]  ->  skills/application-tracker/scripts/status.py … --bogus
    tasks/3_in-review/2026-07-22-email-provider-contract/verification.md:99  [command]  ->  automation/maintenance/gardener/gardener.py   -> did you mean automation/gardener/gardener.py?
  permitted (dated records — rewriting them would falsify the record)
    tasks/4_done/2026-07-28-workspace-phase-0-fail-closed-gates/verification.md:37  [command]  ->  automation/maintenance/gardener/verify_links.py   -> did you mean automation/gardener/verify_links.py?
    tasks/4_done/2026-07-29-vendored-config-repo-root-wrong/verification.md:212  [command]  ->  automation/maintenance/gardener/verify_links.py   -> did you mean automation/gardener/verify_links.py?
```

- The two `execution-plan.md` lines are the live instance the sibling task named.
  Both carry the successor.
- Two are deliberately wrong by design — a verification transcript demonstrating
  an "unrecognized arguments" error, and a design doc proposing a CLI that does not
  exist yet. The existing tier rule routes both to advisory with no special case.
- The two in `tasks/4_done/` are dated records of runs made while
  `automation/maintenance/` still existed. Listed with their successor, never fatal.

## Acceptance test: the two commands from the task file, replanted

Put back exactly as they were on `main` — the retired root into a REFERENCE doc
(`docs/handbook/command-cookbook.md`), and the search-recall-audit line into its
`SKILL.md`:

```diff
+.venv/bin/python automation/maintenance/gardener/gardener.py verify-links
-.venv/bin/python automation/search-recall-audit/field_fidelity.py check --key <entity-key>
+.venv/bin/python automation/search-recall-audit/field_fidelity.py check --source lever --id <native_id>
```

**Re-planted and re-run at the tip `40871e6`, 2026-07-31**, in a throwaway clone (the
owner's checkout was never touched; `git status --porcelain` → 0 entries afterwards).
Same three findings, same source lines, same exit code — including the same
`command-cookbook.md:14`. Only the reference total moved: 2554 with both probes in place
at the tip, against the 2377 originally recorded (a figure from the authoring worktree,
not from `adff448`, whose clean run is 2426).

```
$ .venv/bin/python automation/gardener/verify_links.py --no-overlay
  BROKEN references: 3
    docs/handbook/command-cookbook.md:14  [command]  ->  automation/maintenance/gardener/gardener.py   -> did you mean automation/gardener/gardener.py?
    skills/search-recall-audit/SKILL.md:170  [command-flag]  ->  automation/search-recall-audit/field_fidelity.py … --source
    skills/search-recall-audit/SKILL.md:170  [command-flag]  ->  automation/search-recall-audit/field_fidelity.py … --id
  references: 3 broken of 2554 verified · 42 advisory · 107 permitted · 1201 refs NOT verified in this tree (classes above)

  FAIL: broken references / symlinks / drift found.
exit=1
```

Both argparse errors are named separately, which is what the doc line would have
produced at runtime: `--id` is defined nowhere in the file (the loose check), and
`--source` is defined on the `sample` subparser rather than `check` (the attributed
check — only that half catches it). Reverted after the run.

## Tests

```
$ .venv/bin/python -m unittest discover -s automation/gardener/tests -t automation/gardener/tests -k TestFencedCommands
Ran 21 tests in 19.373s          # re-run at 40871e6; 21 at the authoring commit too

OK
```

The 21 pin the catch, the record exemption, and the false-positive guards: an
untagged illustrative directory tree, a `text`/`yaml`/`json`/`python`/`mermaid`
fence, `-m module` and `-c '…'`, a `<scratchpad>/` script path, a bare
`mdlinks.py`, placeholder ARGUMENTS on a real command, and a subparser built in a
loop falling back to the loose flag check.

## Gates

All four re-run at the tip `40871e6`, 2026-07-31. Only the reference count moved.

```
$ .venv/bin/python -m unittest discover -s automation/gardener/tests -t automation/gardener/tests
Ran 165 tests in 83.029s

OK (expected failures=1)

$ .venv/bin/python automation/gardener/verify_links.py          # exit 0
  OK: 2552 references, the skill symlinks and the vendored copies verified.

$ .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (9 checks clean)

$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.
```

The one expected failure is the pre-existing
`test_link_inside_an_indented_code_block_is_not_a_link`, unchanged by this branch.
