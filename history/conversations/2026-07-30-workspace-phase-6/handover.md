# Handover — workspace phase 6

- **Date**: 2026-07-30
- **Task(s)**: [2026-07-28-workspace-phase-6-skip-log-authority](../../../tasks/3_in-review/2026-07-28-workspace-phase-6-skip-log-authority/task.md)

## What happened

- The applications skip-log stopped being derived. It was regenerated wholesale from a
  scan of the application folders, so deleting a rejected application and re-syncing
  dropped its rows and job-search re-surfaced the posting as fresh. It is now an
  append-only JSONL that nothing rewrites.
- The design was attacked before implementation, and the attack paid for itself: three
  blockers, all real. The most important one would have shipped a silent regression —
  using the file's dedup identity as a *reader's* match key drops the `(company, role)`
  skip for the 367 of 369 rows that carry a URL, and no existing test could have caught it
  because the fixture wrote an empty URL on every row. Fixing that forced the shape that
  made the whole cutover safe: the fold hands back rows in the old YAML's exact shape, so
  each of the five readers changed by one line and kept its own normalizer.
- Both implementation agents found errors in my design and were right about all of them —
  including one coercion whose absence would have made `--sync-log` crash outright on an
  unquoted date in a `meta.yaml`.
- The acceptance proof ran on a copy of the real overlay: delete a rejected application,
  re-sync, confirm the posting is still skipped — **and** confirm the same check fails
  against a reconstructed copy of the old writer, so the proof is not vacuous. It also
  found two ways a command could silently undo a deliberate `--forget-log`; both are fixed
  and tested.
- Three bugs surfaced that predate this work: `store_refilter` had been reading two keys
  the log has never carried (so "covered" silently meant "still has a live folder") and
  crashed on an undefined name; and `automation/search-recall-audit/` had no test suite and
  no CI step. All three fixed here.

## Where things stand

- **Three PRs open, all CI-green, none merged.** Public stack, merge bottom-up: #113
  (re-anchors the ledger after the phase-5 stack merge — `main` is red without it) → #114
  (the module, no behaviour change) → #115 (the cutover). The overlay repo has its own PR
  seeding the log.
- **The overlay PR must merge with or before #115.** Until the seeded file exists, a search
  reads an empty skip-log and skips nothing. There is now a stderr warning in that state,
  but the warning is the only thing between an unseeded log and re-drafting every posting
  already applied to. The seed itself has already run against the live overlay and is
  committed on that branch — 369 events, fold 369, matching the corpus exactly.
- Phase 6 is the last of the three remaining workspace phases that was urgent. **Phases 7
  (one company key) and 8 (instruction surface + `examples/`) are still not started.**
- Local branches: only the three PR branches plus `main`, in each repo. Nothing stale.

## Needs your attention

- [The retired `applications-log.yaml` is now read by nothing](../../../message-queue/needs-human/decisions/retired-applications-log-yaml.md)
  — delete it or keep it. Recommendation: verify the new log looks right after merging,
  then delete; git history in the overlay is the better archive, and a stale file that
  looks authoritative is the failure mode this phase removes. While it exists it stays a
  resurrection source for rows you later un-skip.
- The four decisions already open before this session are unchanged: `history/` untracking,
  the story-bank leaf name, the coding-interview screenshot inbox, and the two you parked
  (`private-scope-reconciler`, `logs-as-store-projections`). The parked
  logs-as-projections one gained a dated note: this phase did not answer it, but it raised
  the cost of answering "yes" for the applications half, because the append-only file holds
  rows whose folders no longer exist and the store cannot reconstruct those.
- Task-tracker drift I did **not** fix, because it is your call whether to sweep it:
  `2026-07-28-slim-company-research-skill` still sits in `0_backlog` though its PR merged,
  and five folders in `3_in-review` now have merged PRs.
