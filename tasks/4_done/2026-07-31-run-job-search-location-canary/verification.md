# Verification — 2026-07-31-run-job-search-location-canary

Retro-closure, 2026-08-02. **The second contested row.** A prior audit read it as
unstarted, network-required canary work. The run happened; the record is
`evals/results/job-search-40871e6799a0-20260731-stack-head.md`.

## DoD 1 — `js-single-company-location-verdict` run at the branch head, against a real board

Record `## Per-canary results`:

```
| js-single-company-location-verdict | 1 | 139,200 | 738 | 46 | All 5 bullets hold against
the strengthened rubric; neither new failure mode observed. Kept every review row, read the
postings behind them, promoted 4 review rows to matches and rejected 3 of the tool's 4
matches after reading their JDs. |
```

Method: *"Five live runs ... Network live (Stage 1, keyless)"* — a real ATS
board, which is what the task said blocked the authoring session.

The tested SHA carries the location change this task is about:

```
$ git merge-base --is-ancestor 9778181 40871e6799a0; echo $?
0
$ git merge-base --is-ancestor 40871e6799a0 HEAD; echo $?
0
$ git log --oneline -1 9778181
9778181 Stop printing "no" for a location verdict that said "review"
```

The record's `## Rubric provenance` section confirms it was scored against the
**strengthened** bullets, which is what the task asked for: *"`js-single-company-location-verdict`
was strengthened inside this stack (commit `9778181`) ... this run is judged
against the strengthened bullets, because they are the bullets in force at the
tested SHA."* Both new rubric lines the task names (a REVIEW row is never
relayed as a no-match; no role reported US-remote on a title word) are covered —
the run rejected 3 of 4 tool matches after reading their JDs and filed Defect B
for the title-word case.

## DoD 2 — results file from TEMPLATE.md, model-pinned

`evals/results/job-search-40871e6799a0-20260731-stack-head.md`; `Model version`
row: `claude-opus-5` for the five runs and the judgement.

## DoD 3 — a failing canary goes back to the branch as a fix, not to the rubric

This canary passed. The set's one failure (`js-recency-vs-research-window`
bullet 3) is a different canary, is pre-existing at both SHAs, and the record
routes it to a `SKILL.md`/`LESSONS.md` line plus a re-run — not to the rubric.
It is out of this task's scope, which is `js-single-company-location-verdict`.

## Efficiency

Record `## Efficiency vs the previous run`: this canary 139,200 tok / 46 calls /
738 s against 125,218 / 28 / 577 at the previous SHA; set-wide median +11.2%,
judged *"not a blow-up and does not block the merge"* with the extra calls
attributed to self-inflicted probing each record discloses.
