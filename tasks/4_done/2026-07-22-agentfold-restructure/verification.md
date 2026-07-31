# Verification — 2026-07-22-agentfold-restructure

Written 2026-07-31 by a bookkeeping pass, not by the implementing session. The work shipped on
2026-07-22 and the folder was never moved out of `1_in-progress`, so for nine days the task tree
advertised an in-flight restructure that had finished. This file records what was checked before
closing it.

## All four stack PRs are merged

```
$ for n in 56 57 58 59; do gh pr view $n --json state,title --jq '.state+"  "+.title'; done
MERGED  refactor: message-queue/ + tasks/ + memory/ (AgentFold restructure 1/4)
MERGED  refactor: dissolve docs/ into handbook/ + design/ (AgentFold restructure 2/4)
MERGED  refactor: skills/ + automation/ renames (AgentFold restructure 3/4)
MERGED  feat: templates/ + roadmap/ + history/ + reconciler (AgentFold restructure 4/4)
```

## The artifacts exist, in both repositories

```
$ ls -d message-queue tasks memory history templates docs/roadmap
$ for d in message-queue tasks memory history; do test -d private/$d && echo "$d present"; done
message-queue present
tasks present
memory present
history present
```

The overlay mirror the task called for is real. The reconciler ships and gates:

```
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (9 checks clean)
```

and it is wired into `automation/hooks/pre-commit` and CI.

## One item was deliberately REVERSED, and that is why this closes rather than completes

The task's item 3 put `handbook/` and `design/` at the top level. **Phase 2 of the workspace
restructure undid that**, consolidating both under `docs/` — under a superseding ADR,
`memory/decisions/docs-parent-for-the-human-read-trees.md`. So this task is closed as *shipped and
partly superseded*, not as "everything in it still stands". Anyone reading the task text for the
current layout will be misled by that one item; the ADR is the authority.

## What closing it does not claim

The worklog stops at session 1. Nothing here re-derives whether every sub-item of a four-PR
restructure landed exactly as written — the evidence is the four merged PRs and the artifacts
above. The reason to close it anyway is that leaving it in `1_in-progress` asserts something
stronger and falser: that someone is working on it.
