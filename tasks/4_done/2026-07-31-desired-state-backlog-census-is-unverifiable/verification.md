# Verification — 2026-07-31-desired-state-backlog-census-is-unverifiable

## The commands the roadmap now names, run on 2026-08-02

```
$ ls tasks/0_backlog | wc -l
      62      # at session start
      60      # after this session closed two tasks

$ grep -rh '^- \*\*Area\*\*:' tasks/0_backlog/*/task.md | sort | uniq -c | sort -rn
  17 - **Area**: job-search
  16 - **Area**: harness
  12 - **Area**: repo
   4 - **Area**: resume-writer
   4 - **Area**: email
   4 - **Area**: benchmarks
   3 - **Area**: tracker
```

The rows sum to 60, so every open task carries the `Area` field the split relies on — the
mechanical collapse the task asked for is available with no new code.

Both commands are public-tree only and print counts, not task identity: `wc -l` emits a
number, and `uniq -c` emits the `Area` values, which are a fixed vocabulary from
`templates/task/task.md` and never contain a slug or a company. The leak rule holds.

## Why no number was written as the load-bearing figure

The count's own history, from the task file plus this session:

```
15   47a15d4 (main, when the task was filed)
18   0f7ce4d (the commit that filed it)
38   40871e6 (that stack's tip)
62   this session, start
60   this session, end — closing a task changes the census
```

A figure written into `desired-state.md` on 2026-08-02 would have been wrong before the
session that wrote it finished. The paragraph therefore records the command and keeps one
parenthetical, dated measurement.

## The re-derived split does not support the original prose, and the doc says so

The paragraph claimed "19 concern the harness … and 5 concern the job hunt" — a roughly 4:1
inversion. Grouping the measured `Area` values the same way gives `harness` 16 + `repo` 12 +
`benchmarks` 4 = 32 against `job-search` 17 + `resume-writer` 4 + `email` 4 + `tracker` 3 =
28, i.e. about 1.1:1. The shape (harness-heavy) survives; the magnitude does not. That is
written into the document, along with the caveat that the `Area` field draws the boundary
differently from the original hand judgement.

## Correction to this session's brief

The brief stated that `docs/roadmap/desired-state.md` carries a `Last-updated` line the
reconciler parses. It does not:

```
$ grep -rn 'Last-updated' docs/roadmap/
docs/roadmap/current-state.md:3:- **Last-updated**: 2026-08-01
docs/roadmap/current-state.md:24:  `Last-updated` line is a real, non-future date, and the gardener's
docs/roadmap/README.md:6:- `current-state.md` — what is true today, with a `Last-updated` date.
docs/roadmap/README.md:15:  `desired-state.md`, no `Last-updated` line, a line that is not an ISO date, or
```

`reconcile.roadmap_current_state()` returns `docs/roadmap/current-state.md`, and
`docs/roadmap/README.md` names `desired-state.md` as the file that deliberately has no such
line. No date was added or changed in either file.

## Gate

```
$ .venv/bin/python automation/reconcile/reconcile.py --check   # EXIT=0
reconcile: OK (9 checks clean)
```
