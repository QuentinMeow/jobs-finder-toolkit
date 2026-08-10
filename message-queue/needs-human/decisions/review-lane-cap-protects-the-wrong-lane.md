# The review cap truncates the high-quality lane and lets the low-quality one run free — reprioritise it?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [issue triage index, 2026-08-03 batch](../../../tasks/0_backlog/2026-08-09-issue-triage-2026-08-03-batch/task.md) · GitHub issues #246 and #269 · measured during a structured debate on title-gate precedence
- **Blocks**: nothing. Search runs; the effect is which review rows you see.
- **Default path**: **do not change the cap, its value, or the order it applies in.** What
  shipped alongside this is durability only: the capped-out overflow rows are now written to
  disk instead of being discarded, and the run reports `N shown of M` with the per-family
  split. The same rows are chosen as before — they are simply no longer destroyed.
- **Cost if wrong**: recurring-loss
- **Safe to merge because**: no row's disposition changed. The shipped half only persists
  rows that were previously dropped from the returned set and adds a count line; deleting the
  sidecar file and the line restores the prior output exactly.

## Background

`search_jobs.py:896-907` caps the review lane at `occupation_review_cap` (default 300). Two
things about how it does that were measured on an 11,783-posting corpus with the shipped
`example.yaml`:

**1. It caps only one family.** The cap is checked against `title_occupation_ambiguous` rows
only. The `title_word_filter_override` rescue lane is not capped at all.

**2. The capped family is the better one.** Measured by the fraction of rows whose title
carries an engineering role noun:

```
title_occupation_ambiguous   4169 rows   57% engineering   <-- CAPPED at 300
title_word_filter_override   2130 rows   22% engineering   <-- UNCAPPED
```

So in that run 1,659 rows were trimmed from the 57%-engineering lane while the
22%-engineering lane passed through whole. A sample of what the trim removed: `Senior AI
Engineer, Enterprise`, `Senior Security Engineer II, Cloud Security`, `Senior Forward Deployed
Engineer`, `Systems Architect`, `Staff Engineer, Systems`.

**3. Until this session, the overflow was destroyed.** The rows were dropped from
`review_postings` and survived only as an integer in `meta`. They were technically
recoverable by `--refilter`, but only inside a 6-hour snapshot TTL and only if you knew to
raise a cap you were never shown. That half is fixed: the overflow is now persisted and
counted. What remains open is purely the ordering question below.

## Options

The axis: how much the tool should rank your attention for you, against how much it should
just show you everything it could not confidently judge.

### Option A — leave the ordering alone *(recommended)*
The cap keeps applying to the ambiguous family only. The overflow is now on disk and counted,
so nothing is lost; the ordering stays a known-imperfect default.

***Example consequence:*** Your review file still shows 300 ambiguous rows plus every rescued
row, and a line tells you `review: 1613 shown of 3272 (residual 300 of 1977, rescue 1164)`.
When a role you wanted is in the overflow, you find it by opening the sidecar — one extra step,
but it is there.

### Option B — one cap across all review families, ordered by measured density per run
Compute each family's engineering-role-noun density for the run and cap the lanes in that
order, so the 57% lane fills before the 22% one. Total default `3 × top_k`.

***Example consequence:*** Your review file gets shorter and noticeably more relevant — the
tax and accounting managers stop crowding out the systems architects. But the ordering is now
computed from the run's own data, so the same profile can produce a differently-ordered review
file on two different days, and a lane that happens to score low one day gets trimmed first
that day.

### Option C — cap nothing; show everything
Remove the cap and render the whole review lane.

***Example consequence:*** Nothing is ever hidden and nothing needs a sidecar — and on a broad
profile you open a 3,272-row file, which is another way of hiding it.

## Recommendation

**Option A.** The genuinely harmful part of this — that the trimmed rows were *destroyed*
rather than deferred — is fixed and needed no decision. What is left is a ranking heuristic,
and Option B's density measure, while clearly better than today's arbitrary single-family cap,
introduces run-to-run instability in which rows you see. That is a real cost for a user who
compares two days' output, and it is not obviously worth paying now that nothing is being lost.

**Strongest case against this:** the density numbers are lopsided enough that "known-imperfect
default" is charitable — the tool is spending its entire review budget on the worse lane and
sending the better one to a sidecar nobody opens. If you only ever read the rendered table,
then persisting the overflow changed nothing you will actually see, and Option A is a
bookkeeping fix dressed up as a resolution.

**Confidence:** medium — the density split and the 1,659-row overflow are measured on one real
corpus with one profile. I did **not** check whether the split holds for a narrow profile or a
short date window; an earlier measurement showed that a 3-day window collapses the whole review
demand from 3,145 rows to 112, which would make this entire question nearly moot in normal use.

**Your answer:** ______
