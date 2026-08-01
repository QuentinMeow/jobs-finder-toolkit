# Re-run the job-search canaries at a commit that is actually in `main`

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: `evals/results/job-search-70a620f32968-20260731-jd-digest-gate.md` (its own
  commit-pin provenance note, and the 2026-08-01 update appended after the stack merged)
- **Claimed-by**:

## Goal

Produce a job-search canary record pinned to a commit that is an ancestor of `main`, so the
skill has gate evidence at head instead of evidence about a commit nobody can reach.

## Context

The only job-search canary record below the store rewrite is pinned to `70a620f32968`, which
is **not** an ancestor of merged history. It exists solely on `origin/wip/07-company-roles-jd-digest`
(pushed 2026-08-01 specifically so this record stays checkable — before that it was on one
unpushed local branch). The landed equivalent is `1e4b7c1` (PR #152).

That record is honest about its own limits and says to treat it as evidence about
`70a620f32968` only. The reason to act now is that the gap has grown: the instruction files
the canaries route on drifted **88 changed lines** when the note was written and
**245** as of `a4e5b3d`:

```
git diff --stat 70a620f32968 main -- skills/job-search/{SKILL,LESSONS,reference}.md
  3 files changed, 193 insertions(+), 52 deletions(-)
```

Several PRs in the merged stack edited `job-search` instruction files (#140, #149, #152 among
them), and #165/#174/#177 changed sponsorship and location classification that three of the
five canaries exercise directly. So this is not a formality — the tested surface has moved.

Two things to carry into the re-run, both from the existing record:

- Canary 5 (`js-single-company-location-verdict`) was **strengthened after** the old tested SHA
  by `9778181`. Score the re-run against the rubric in force at the new commit; do not
  reproduce the old record's split scoring, which existed only to avoid grading a run against
  a spec written after it.
- The old record's one failure — `js-recency-vs-research-window` bullet 3, "notes that posting
  age is off by default" — was never closed. Check whether it still fails; if it does, the fix
  is a one-line statement in `skills/job-search/SKILL.md` or `LESSONS.md` that posting-age
  filtering is opt-in, then a re-run of that canary alone.

Protocol and recording rules are in `evals/README.md`; the rubric is
`evals/rubrics/judging.md`. Note the old record's efficiency caveat: its numbers are not
like-for-like against the 2026-07-21 sonnet baseline (model, harness and depth all changed at
once). A future efficiency gate needs a matched protocol, so do not compare across those runs.

These are **live** runs against third-party job boards. Keep the load proportionate and expect
board state to differ from 2026-07-31 — the record already documents one company whose board
moved between runs.

## Definition of done

- A new `evals/results/job-search-<sha>-<date>-*.md` exists whose `Git SHA` field names a
  commit for which `git merge-base --is-ancestor <sha> main` exits 0.
- The record states the pass/fail for all five canaries against the rubric in force at that
  commit, and says explicitly whether `js-recency-vs-research-window` bullet 3 still fails.
- The 2026-08-01 update block in
  `evals/results/job-search-70a620f32968-20260731-jd-digest-gate.md` is amended with a pointer
  to the superseding record (append; do not rewrite the existing narrative).
