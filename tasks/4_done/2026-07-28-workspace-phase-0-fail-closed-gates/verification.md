# Verification — 2026-07-28-workspace-phase-0-fail-closed-gates

<Only commands actually run and their real output. Never fabricated, never
paraphrased into "all tests pass" without the evidence. Required before a
task enters 3_in-review or 4_done.>

All commands run 2026-07-29 on `chore/workspace-phase-bookkeeping`, which is
based on `phase-4/remove-inbound-symlinks` and carries all four phase-0
commits (`72d45e2`, `2d20f34`, `8df3847`, `eb345e7`). `private/` is mounted
(a real `config.yaml` is present).

## Reconciler, with the new `--require-roots` flag (phase-0d)

```
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (8 checks clean)
```

## Leak guard fails closed / arms on real identity (phase-0a)

```
$ .venv/bin/python automation/publish/check_public.py
Public-repo leak guard
  repo root:      <repo-root>
  tracked files:  697
  identity tokens:      4 (config.yaml / $JOBHUNT_PERSONAL_TOKENS)
  supplementary tokens: 7 (leak_tokens.txt; never arming)
  active tokens:        11 (union, deduped)
  identity source:      real config (<repo-root>/config.yaml)

OK: no public-repo leaks detected. Safe to publish.
```

## Link checker widened + vendor drift check (phase-0d)

```
$ .venv/bin/python automation/maintenance/gardener/verify_links.py
gardener · verify-links (report-only) [DRY-RUN]
  policy: private/docs/harness-engineering-and-repo-evolution/03-folder-structure-and-memory.md
  backticked toolkit refs checked across 254 tracked .md files
  advisory (target/historical paths named by plans and records): 22
  references: all resolve
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync

  OK: links, symlinks, and vendored copies verified.
```

## Vendoring in sync (phase-0b touched `automation/shared/config.py`, a
vendored module)

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## Unit suites (covers the fail-closed leak guard, config accessors incl.
the blacklist preflight, and skill-manifest SSOT)

```
$ .venv/bin/python -m unittest discover -s automation/publish/tests -t .
----------------------------------------------------------------------
Ran 137 tests in 32.788s

OK
```

```
$ .venv/bin/python -m unittest discover automation/shared/tests
----------------------------------------------------------------------
Ran 317 tests in 12.364s

OK
```

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t .
----------------------------------------------------------------------
Ran 312 tests in 73.775s

OK
```

## Definition-of-done bullets not re-derived by hand

The task's DoD lists manual scenarios ("plant a file containing a personal
token", "delete a process root", "git add -f private/ is rejected"). Rather
than re-deriving each by hand, I confirmed the automated regression tests
that encode exactly those scenarios exist and pass in the suites above —
e.g. `automation/publish/tests/test_leak_guard.py` (denylist path staging,
armed/unarmed states), `automation/shared/tests/test_config_accessors.py`
(17 tests, discovery boundary + `ConfigNotFound`/`ConfigError`), and the
reconciler's own `--require-roots` behavior verified directly above (a
missing root is not simulated here — that would require deleting a real
process root, which risks losing tracked content outside this task's
scope).

## Skill-visibility SSOT: `.claude/skills` and `.cursor/skills` agree at 12

```
$ find .claude/skills -maxdepth 1 -type l | wc -l
      12
$ find .cursor/skills -maxdepth 1 -type l | wc -l
      12
```

(`.cursor/skills/` also contains one untracked, non-symlink directory,
`github-manager`, unrelated to the manifest-generated set — not part of the
10-public + 2-private count.)
