# Handover — workspace-phase-2

- **Date**: 2026-07-29
- **Task(s)**: `tasks/3_in-review/2026-07-28-workspace-phase-2-public-cleanup`

## What happened

Phase 2 of the workspace restructure — the public tree's last shape change before phase 5 starts
on the overlay. Four moves, no behaviour changes: `automation/maintenance/` split into three
purpose-named directories, `handbook`+`design`+`roadmap` consolidated under `docs/`, the
measurement docs and per-skill canary folders absorbed into `evals/`, and the gitignored scratch
root renamed `tmp/` → `local/`. A fifth PR is the record. Nothing was deleted anywhere.

Each move was proved rather than assumed: the export emits the same 566 published files before
and after the `docs/` move, all nine canary sets are byte-identical across the `evals/` move, and
the scratch rename carried 102 files in and the same 102 paths out.

The phase turned up two things worth your time.

- **The plan was wrong about its own rules, in four places.** The biggest: "every `git mv` is its
  own commit" cannot be done when the moved root is named by a checker constant, because the
  pre-commit hook asserts that root exists and refuses the commit. The rule now carries the
  correction. The other three are all the same shape — a path spelled a way the sweep did not
  look for: a bare `"roadmap"` with no trailing slash in a test fixture, four docs naming the
  maintenance bucket as a bare word (one of them the handbook, holding it up as a *good* folder
  name), and nine scripts spelling the scratch root as a quoted `"tmp"` segment rather than
  `tmp/`. Missing that last one would have left every document saying `local/` while every script
  quietly recreated `tmp/` beside it, outside the new ignore rule.
- **The link checker has been reporting a clean tree it never looked at.** It only checks
  backticked references, so every `[text](path)` markdown link in the repo is unverified — 31 are
  broken right now. And a backticked reference at a root the checker does not recognise is not
  broken, not advisory, and not counted: it is dropped. I proved it by planting the same broken
  reference twice, once under `docs/handbook/` (fails, correctly) and once under `handbook/`
  (silent). 76 references sit in that hole today. Both are filed as one P1 task.

Three long-broken links were repaired on the way: a `../STYLE.md` cited by seven design docs that
has never existed, `PRIVATE_OVERLAY.md`, and an `../ARCHITECTURE.md` that only resolved because
macOS ignores filename case — it would have failed on Linux CI.

## Where things stand

- Five PRs open against `main`, unmerged. They merge bottom-up; each stands on the one below it.
- The task folder is in `tasks/3_in-review/`, not `4_done` — the README defines done as
  merged/verified and these are open. One `git mv` promotes it when the stack lands. Two
  definition-of-done boxes are deliberately unticked with their reasons written out, rather than
  ticked to make the list look finished; `verification.md` beside them has the real command output.
- Phase 5 (the private overlay's `me/` · `companies/` · `applications/` split) is the next phase
  and is unblocked. Its preconditions were already met before this phase; nothing here changed them.
- The overlay has one commit from this phase (its live queue and task items re-pointed at
  `local/`) and one pre-existing unstaged deletion from an earlier session, untouched.

## Needs your attention

- **The five open PRs merge bottom-up, in order:** the `automation/maintenance/` split, then the
  `docs/` consolidation, then the `evals/` layout, then the `tmp/` → `local/` rename, then this
  record. Merging out of order will conflict; a rebase of the whole train is cheaper than
  untangling one.
- **[`verify_links.py` misses markdown links and unknown roots](../../../tasks/0_backlog/2026-07-29-verify-links-misses-markdown-and-nonstrict-roots/task.md)**
  — newly filed, P1. This is the gate that has been telling us links are fine. 31 broken markdown
  links and 76 invisible references are the current inventory. It matters before phase 5, which
  plans to un-skip `interviews/` and fix 244 links there and would get a clean report either way.
- **[Refresh phase 8's per-skill counts](../../../tasks/0_backlog/2026-07-29-refresh-phase-8-instruction-surface-counts/task.md)**
  — newly filed, P2. Phase 2 did the work phase 8's estimate was counting, so that estimate now
  over-states the phase. Re-measure before phase 8 is scheduled, not during.
- **[Config discovery fallback](../../../message-queue/needs-human/decisions/config-discovery-example-fallback.md)**
  — still open from phase 0. Implemented on the default path (raise only when an overlay is
  mounted). Confirm, or pick the stricter option and two docs get rewritten to match.
- **[Private-scope reconciler](../../../message-queue/needs-human/decisions/private-scope-reconciler.md)**
  — still open from phase 0. None exists, so the overlay hook reports the skip. Your overlay's
  process layer has findings, so enabling it today blocks your next overlay commit until they clear.
- **[Logs as store projections](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)**
  — pre-existing, unrelated, still open. Phase 6 is the phase that will force it.
- **The scratch classification is still waiting on you.** It is a review item in the overlay's
  queue: which of the ~1.2 GB is safe to delete, which is regenerable, and which is application
  and interview material no agent will touch. Phase 2 renamed the folder underneath it and
  updated every path in the item, so it now reads `local/` throughout and nothing else about it
  changed — 102 files before and after, zero deletions. Every question in it is still open.
- **[Workspace layout review](../../../message-queue/needs-human/reviews/workspace-restructure-plan.md)**
  — answered and folded three sessions ago; safe to delete once you have confirmed nothing was
  mis-folded. Two of its own links have been broken since before this phase and are covered by
  the new link-checker task.
