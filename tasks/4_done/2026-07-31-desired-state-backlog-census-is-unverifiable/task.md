# The desired-state backlog census cannot be re-derived from the public tree

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: roadmap grooming session 2026-07-31 (the pass that corrected `current-state.md`); contradiction audit finding B7
- **Claimed-by**: agent, session 2026-08-02 (branch `docs/26-contract-and-record-corrections`)

## Goal

Either make `docs/roadmap/desired-state.md`'s backlog census re-derivable by a
command, or replace the hand-counted numbers with the command that produces them —
so the argument built on those numbers can be re-checked without reading `private/`.

## Context

`docs/roadmap/desired-state.md` → "The gap this list does not describe" opens with
*"Of the 24 open backlog items, 19 concern the harness that tracks the work and 5
concern the job hunt."* The paragraph is dated 2026-07-31 and the 19-vs-5 split is
the whole load-bearing argument of that section: the backlog is inverted relative to
where damage reaches the user.

The number cannot be checked from the public tree. `ls tasks/0_backlog | wc -l` was
**15** on `main` (`47a15d4`) when this task was filed, which is where the inference
"so 24 must be a public + `private/tasks/0_backlog/` total" came from — and an agent
working the public repo (or any reader of the published export, which ships no `tasks/`
at all) has no way to confirm or refute it. The grooming pass that corrected
`current-state.md` deliberately did not touch the number rather than guess at it,
because the private half was out of reach by instruction.

**Correction, 2026-07-31 (measured on the stack tip `40871e6`).** The public count moves
fast enough that the inference is already dead, and the 15 was stale before the paragraph
was finished:

```
$ ls tasks/0_backlog | wc -l
      15     # 47a15d4 (main)
      18     # 0f7ce4d, the commit that filed this task — it adds three itself
      38     # 40871e6, the stack tip
```

38 public backlog items alone now exceed the 24 the desired-state paragraph counts, so
"24 must be a public + private total" no longer holds in either direction, and the
19-vs-5 split it supports cannot be reconstructed from any tree. The fix below (derive
the number, or drop it) is now the only way to make that paragraph true.

Two shapes of fix, both fine:

1. **Derive it.** A tiny counter that reports `open backlog items, split by the
   `- **Area**:` field` across `tasks/0_backlog/` plus `private/tasks/0_backlog/`
   when mounted. `automation/metrics/` is the natural home; the gardener's
   report-only routines are the natural caller. The roadmap then names the command
   instead of a number, the way `current-state.md`'s link-check bullet now does.
2. **Re-measure and re-date, with the derivation written next to it.** Cheaper, but
   it goes stale on the next filed task and nothing will catch it — the same failure
   this session was cleaning up.

Note the census also depends on the harness/job-hunt classification, which today is
a judgement made per task, not a field. `- **Area**:` in `templates/task/task.md`
already carries a close-enough taxonomy (`job-search | resume-writer | tracker |
email | harness | benchmarks | repo`) — a split on that field is mechanical, whereas
"harness vs job hunt" is not, so option 1 should report the `Area` split and let the
prose do the collapsing.

**Leak rule**: any counter must print counts only. A private task's id, slug or title
must never reach the public roadmap or a public commit message.

## Definition of done

- `docs/roadmap/desired-state.md`'s census paragraph either names a command that
  reproduces its numbers, or carries a re-measured number with the command that
  produced it written beside it.
- If option 1: the counter runs in a config-less checkout with no overlay mounted
  (public half only, no crash), and its output contains no task ids or titles.
- `.venv/bin/python automation/reconcile/reconcile.py --check` stays green.
