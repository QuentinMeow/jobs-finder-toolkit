# Worklog — 2026-07-31-desired-state-backlog-census-is-unverifiable

## 2026-08-02 — session 1 (agent)

- Took **option 2 with the derivation written in**, not option 1 (a new counter in
  `automation/metrics/`). Reason: the paragraph's problem is that it stated a number nobody
  could re-derive, and a two-line shell snippet in the document fixes exactly that at zero
  maintenance cost. A counter script is a second thing to keep green, and it would still not
  make the "harness vs job hunt" collapse mechanical — the `Area` field does that, and the
  document can name it directly.
- The census paragraph now carries the two commands (`ls tasks/0_backlog | wc -l` and the
  `Area` split) plus the leak rule the task requires: counts only, never a private task's id
  or title.
- **Deliberately did not write a load-bearing figure.** The task's own history is the
  argument: 15 → 18 → 38, and this session measured 62 then 60 — the second change caused by
  this very session closing tasks. The paragraph now says the SHAPE is the claim and gives
  one dated, clearly-provisional measurement in parentheses.
- Re-derived the `Area` split honestly and found it **weaker than the original prose
  claimed** — 32 harness-ish vs 28 job-hunt-ish, not 19 vs 5. That is written into the
  paragraph rather than smoothed over, with the note that the `Area` field draws the line
  differently from the hand judgement, which is itself a reason to prefer the command.
- Also removed the two now-fixed defects from the same section's live-defect list (they were
  entries 1 and 2 of the sibling `memory` task) and corrected 7 open known-issues to 4.
- **The brief for this session said `desired-state.md` carries a `Last-updated` line the
  reconciler parses. It does not** — that line is in `current-state.md`
  (`reconcile.roadmap_current_state()`), and `docs/roadmap/README.md` documents it that way.
  Nothing was dated into the future; `reconcile --check` is green.
