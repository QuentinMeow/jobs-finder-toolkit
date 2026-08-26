# Verification — 2026-08-25-refresh-main-and-clean-agent-branches

## Current main and local cleanup

Both repository pulls exited 0:

```
$ git pull --ff-only origin main
Already up to date.
```

The public repository had one local `codex/` branch and no `claude/` branch or extra worktree.
GitHub reported no open PR using it, and the exact-tree containment probe matched:

```
$ gh pr list --state open --json number,headRefName,baseRefName
[]
$ git rev-parse 'origin/main^{tree}'
213ffe081be301d4f70fe37ebd4db500baea4df0
$ git merge-tree --write-tree origin/main codex/install-git-ws-alias
213ffe081be301d4f70fe37ebd4db500baea4df0
$ git branch -d codex/install-git-ws-alias
Deleted branch codex/install-git-ws-alias (was 4a77db1).
```

The private repository had no local `codex/` or `claude/` branch and no extra worktree.

## Skill canaries

Five independent fresh-context runs were judged against every rubric bullet. All passed; no
efficiency metric was available, so none was inferred. The pinned record is
`evals/results/github-workflow-30769bcb59b6-20260825-refresh-cleanup.md`.

```
Pass rate: 5/5
Regression: PASS
```

The generic skill validator was also attempted. It exited 1 because it rejects this repository's
supported `visibility:` frontmatter key, so it is not evidence for or against the change. The
repository's own manifest and instruction checks below passed.

## Committed-tree gates

Commit `0ac356d` was checked in a detached, config-less worktree with no private overlay. The gate
runner selected every lane because the generated skill manifest is foundational:

```
$ <repo-root>/.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
coverage: 32 of 37 gates in the table executed (0 skipped, 5 not selected, selector: impact from: origin/main)
ALL GREEN (32 of 37 gates ran)
```

The green set included `instruction-budget`, `reconciler`, `verify-links`, `tests-evals`,
`tests-github-workflow`, `tests-shared`, both PDF gates, the publication tests, and the armed tree
leak scan.

The same command in the primary checkout first exited 1 for the known missing-config/overlay
environment and the macOS app sandbox. The two PDF lanes passed outside the sandbox, and the
shared suite passed all 871 tests with the explicit fictional config used by a config-less
checkout. The primary-checkout mismatch was already filed at
`tasks/0_backlog/2026-08-22-the-shared-suite-is-red-for-the-owner-and-green-for-every-agent/`;
this task did not alter config discovery.
