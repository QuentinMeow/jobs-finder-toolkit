# Verification — 2026-07-28-workspace-phase-4-remove-inbound-symlinks

<Only commands actually run and their real output. Never fabricated, never
paraphrased into "all tests pass" without the evidence. Required before a
task enters 3_in-review or 4_done.>

All commands run 2026-07-29 on `chore/workspace-phase-bookkeeping`, which is
based directly on `phase-4/remove-inbound-symlinks` (commits `1b837b7`,
`7809b4b`).

## DoD: `find skills -type l` returns nothing (no inbound public→private
symlinks left under the public `skills/` tree)

```
$ find skills -type l
$ find skills -type l | wc -l
       0
```

## DoD: the runtime lists 12 skills (10 public + 2 private) from
`.claude/skills` and `.cursor/skills`

```
$ find .claude/skills -maxdepth 1 -type l | wc -l
      12
$ find .cursor/skills -maxdepth 1 -type l | wc -l
      12
$ find .cursor/skills -maxdepth 1 -type d ! -type l
.cursor/skills
.cursor/skills/github-manager
```

Both trees resolve to 12 manifest-generated symlinks. `.cursor/skills/
github-manager` is a real, untracked, non-symlink directory (confirmed not
a symlink) — unrelated to `sync_skill_manifests.py`'s output and not part
of the 10-public + 2-private count this DoD bullet is about.

## Gate command clean (reconciler, which phase-0d wired `--require-roots`
into and phase-0c added the `skill-manifests` check to)

```
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (8 checks clean)
```

## Leak guard still clean with the symlinks gone (the personal-filename
leak these symlinks caused is the reason phase 4 exists)

```
$ .venv/bin/python automation/publish/check_public.py
OK: no public-repo leaks detected. Safe to publish.
```

## Job-search suite (covers `profile_search_dirs()`, the replacement for
the deleted profile symlinks, and the two fixed consumers)

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t .
----------------------------------------------------------------------
Ran 312 tests in 73.775s

OK
```

## Not independently re-derived

"A fresh public clone with no overlay still runs job-search on the tracked
example profile" was not reproduced with an actual fresh clone in this
session (that would require cloning outside this working tree, which risks
picking up or losing `private/` state) — `profile_search_dirs()`'s
config-less-fallback behavior is covered by the job-search suite above,
which is green.
