# Verification — 2026-07-31-verify-links-reads-no-fenced-command

Shipped on the same branch as `2026-07-31-gate-documented-commands`; the full
transcript (whole-tree run, triage of all 8 findings, the replanted acceptance
test, the four gates) is in that task's `verification.md`. This file covers the
four DoD items specific to THIS task.

**Corrected 2026-07-31 on the stack tip `40871e6`.** Every behavioural claim reproduces.
Every count did not: this file recorded 36 advisory / 284 commands / 2375 verified, which
is neither the tip's figure nor the authoring commit `adff448`'s (**41 / 292 / 2426**) —
the block came from the isolated `main`-based worktree the change was written in. The
counts below are the tip's; `adff448`'s are in the sibling record's table.

## The two stage-gate lines are reported, in a named class, with the successor

```
$ .venv/bin/python automation/gardener/verify_links.py --no-overlay
  advisory (plans name targets that do not exist yet): 42
    docs/designs/filtering-variant-safeguards/execution-plan.md:348  [command]  ->  automation/maintenance/gardener/gardener.py   -> did you mean automation/gardener/gardener.py?
    docs/designs/filtering-variant-safeguards/execution-plan.md:381  [command]  ->  automation/maintenance/gardener/gardener.py   -> did you mean automation/gardener/gardener.py?
```

The class is `[command]`; the successor comes from `RETIRED_ROOTS` via the same
`_suggest` path every other tier already uses. Advisory rather than fatal because
`docs/designs/` is plan-tier — the DoD's own rule, applied without a special case.

## An illustrative fence produces no finding

```
$ .venv/bin/python -m unittest discover -s automation/gardener/tests \
      -t automation/gardener/tests -k TestFencedCommands
Ran 21 tests in 19.373s          # re-run at 40871e6; 21 at the authoring commit too

OK
```

Covering, among the 21:

- `test_an_illustrative_directory_tree_produces_no_finding` — an untagged
  `templates/` tree with `applications/6_drafted/<slug>/` in it: 0 findings,
  `commands-read` 0.
- `test_a_non_shell_fence_is_not_read` — the same dead command inside
  `python`/`yaml`/`json`/`text`/`mermaid`/`markdown`: 0 findings each.
- `test_placeholder_ARGUMENTS_do_not_make_a_real_command_a_finding` — a REAL
  script invoked as `--update <slug> applied`: 0 findings, and the command is
  still counted as read.

## The tier rule holds, one test each

- `test_a_dead_command_in_a_reference_doc_is_fatal` — `docs/handbook/cookbook.md`
  → `broken`, advisory and permitted both empty.
- `test_the_same_command_in_a_dated_record_is_permitted` — the identical line in
  `tasks/4_done/2026-01-01-x/verification.md` → `permitted`, broken empty.
- `test_the_same_command_in_a_plan_is_advisory` — `docs/designs/thing/README.md`
  → `advisory`, broken empty.

## The suite passes and the repo run is still 0 broken

```
$ .venv/bin/python -m unittest discover -s automation/gardener/tests -t automation/gardener/tests
Ran 165 tests in 83.029s

OK (expected failures=1)

$ .venv/bin/python automation/gardener/verify_links.py
  documented commands read from fenced code blocks: 306
  references: 0 broken of 2552 verified · 42 advisory · 107 permitted · 1201 refs NOT verified in this tree (classes above)

  OK: 2552 references, the skill symlinks and the vendored copies verified.
```

Nothing newly surfaced needed repair: of the 8 command findings, 6 are advisory
and 2 permitted, and the reference tier — the only fatal one — was already clean.

## The `.py`-docstring decision

Recorded in this task's `worklog.md` and carried forward as
`tasks/0_backlog/2026-07-31-verify-links-source-set-and-command-args/`. Short
version: the source set stays `*.md`; a docstring is not copy-pasteable text, and
widening the enumeration is an independent change with its own false-positive
surface.
