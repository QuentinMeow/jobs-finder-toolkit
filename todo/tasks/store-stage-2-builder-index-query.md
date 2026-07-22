# Store stage 2 — builder, derived postings, index, query tool

- **Status**: done (shipped in PR #51)
- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: raw-data-layer sign-off 2026-07-21; plan: docs/design/raw-data-layer/execution-plan.md

## Goal

Ship this stage green (CI + leak guard) as one focused PR (the owner's
delivery preference: small stacked PRs, one stage each). The execution plan
is the narrative source of truth; this file carries the checklist.

## Context

`build_postings.py`: ledger-ordered incremental + full rebuild
(build-aside → verify: schema, counts, 100% annotation joins,
incremental==rebuild spot equivalence → atomic swap) + `--opinions-only`
re-labeling with diff report. Identity v2 (platform-unique IDs, no board
tokens; registry `previous:` ATS-migration records; versioned URL
canonicalizer; weak-identity content keys with sorted location sets).
Observations only — first-seen/seen/changed; NO closure inference (owner
decision: on-demand polling, gap-tolerant timelines — the store never says
"closed").

`query_postings.py` (materialization-sequence cursors, advance-after-action,
`--since` override, compact output); `store_show.py` for jobs; generated
store README (map + cookbook) registered with the instruction budget; the
**suppressed review queue** `jobs/index/triage/suppressed-<yyyy-mm>.jsonl`
(one line per suppressed sweep row: partial info + raw manifest path;
write-only, optional manual review, never blocks — owner decision).

Acceptance: determinism/equivalence green against several days of REAL
stage-1 raw; classifier tweak + opinions-only rebuild re-labels history
with diff; doc §5 example queries answer with zero network; annotation
orphans enforced at zero.

## Definition of done

- [x] Determinism + incremental==rebuild equivalence green against several days of REAL stage-1 raw (byte-identical derived+index; incremental==rebuild AND rebuild==rebuild).
- [x] `--opinions-only` after a deliberate classifier tweak re-labels history and prints the diff report (demoed on the real store, reverted after).
- [x] The design doc's query examples answer with zero network (all §5 examples).
- [x] Annotation orphan count enforced at zero in rebuild verification (hard-fail proven by test). Initially `--rebuild`-only; extended in the stage-2 review-fix round to run on every build path (incl. incremental) — it runs on all paths at head.
- [x] Suppressed review queue populated on a real sweep; entries carry partial info + raw manifest path; pipeline timing unaffected.

*Done in PR #51. Delete this file in the next merged PR that touches `todo/` (per todo/tasks/README.md).*
