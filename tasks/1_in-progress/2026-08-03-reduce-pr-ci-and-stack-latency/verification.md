# Verification — 2026-08-03-reduce-pr-ci-and-stack-latency

## Historical hosted baseline

```
$ gh run list --repo <PUBLIC_REPO> --event pull_request --limit 100 --json createdAt,updatedAt,conclusion
60 successful runs: median 184 seconds; p90 207 seconds
Representative run 30799648925: dependency install 18 seconds; LibreOffice install 31 seconds; serial test tail 127 seconds
```

## Fail-closed selector and gate orchestration

```
$ python -m unittest discover automation/ci/tests
........................
Ran 24 tests

OK
```

```
$ python automation/gates/tests/test_run_gates.py
...................................................................
Ran 67 tests in 0.589s

OK
```

The selector coverage includes documentation-only, targeted-code, shared-foundation, workflow, unknown-path, rename/deletion, and unreadable-range cases. Unknown or foundational inputs select the full lane set.

## Stack driver

```
$ python -m unittest discover skills/github-workflow/scripts/tests
Ran 115 tests

OK
```

```
$ python skills/github-workflow/scripts/merge_stack.py --repo <PUBLIC_REPO> 266 270
merge_stack.py: <PUBLIC_REPO> -- DRY RUN (nothing merges without --execute)
#266  B  OPEN  no  -  main                 812524f1  MERGEABLE
#270  B  OPEN  no  -  codex/ci-pr-latency  cfecfa61  MERGEABLE
Dry run: stopping here. Re-run with --execute to merge.
```

The execute path was intentionally not run: merging into the default branch is irreversible and needs explicit owner authorization.

## Hosted rollout

```
$ gh run view 30805311849 --repo <PUBLIC_REPO>
PR #266 full matrix: success; 88 seconds wall time
policy: 28 seconds; slowest selected lane: job-search, 70 seconds
Ubuntu render and resume/PDF lanes: pass
```

```
$ gh run list --repo <PUBLIC_REPO> --branch codex/ci-pr-latency --workflow "PR body"
30805537781  success  15 seconds wall time
No CI workflow was created by the body-only edit.
```

```
$ gh run view 30806602419 --repo <PUBLIC_REPO> --json createdAt,updatedAt,status,conclusion,headSha
{"conclusion":"success","createdAt":"2026-08-03T10:42:10Z","headSha":"cfecfa61fa50ed0571b48b45f1b5dbcc0fafe1e3","status":"completed","updatedAt":"2026-08-03T10:43:59Z"}
```

PR #270's full matrix took 109 seconds. Policy took 27 seconds, the slowest selected lane took 61 seconds, and the separate required `pr-body` job passed in 8 seconds.

`<PUBLIC_REPO>` redacts the identity-derived public owner segment; the arguments and outputs are otherwise the commands and evidence observed in this session.

## Required checks and local limitations

GitHub ruleset `19191121` requires the stable `build` and `pr-body` contexts without strict base synchronization. This keeps checks mandatory while avoiding a redundant child rebuild after a reviewed stack parent merges.

The local full-impact run selected all 29 gates; 27 passed. `example-render` and resume end-to-end PDF validation could not launch LibreOffice because the Codex macOS sandbox denies the LaunchServices lookup. The corresponding hosted Ubuntu render and resume lanes passed, so this is an environment limitation rather than a product regression.
