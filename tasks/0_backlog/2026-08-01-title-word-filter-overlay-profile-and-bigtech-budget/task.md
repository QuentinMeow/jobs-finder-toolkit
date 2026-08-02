# Configure `titles.word_filter` in the real search profile, and re-check the big-tech candidate budgets

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: branch `feat/11-search-recency-and-title-filter`, which implemented
  the owner's answer on the title-prefilter question, recorded as
  `memory/decisions/search-filter-vocabulary-is-profile-owned.md` (the queue item it was
  folded from was deleted in `85102cb`; git history is the archive)
  (three profile-owned title word classes). Both items below were deliberately
  left out of that PR: one is in a repository that branch may not touch, the other
  needs a measurement nobody has taken.
- **Claimed-by**:

## Goal

Give the candidate's real search profile its own `titles.word_filter` block,
settle whether the big-tech per-board candidate budgets still hold now that the
coarse prefilter drops fewer titles, and discharge the `job-search` canary run
that the profile-and-budget work leaves owed.

## Context

The coarse title prefilter used to carry a hardcoded skip tuple in
`skills/job-search/scripts/sources.py`. It is gone: the words now come from the
candidate's search profile under `titles.word_filter`, in three classes
(`hard_exclude` / `soft_exclude` / `include`), read by
`skills/job-search/scripts/title_filter.py`. The public example persona's lists
live in `skills/job-search/profiles/example.yaml`; `_TEMPLATE.yaml` documents the
shape.

**Two consequences that PR could not close.**

1. **The real profile has no `word_filter` block yet.** It lives in
   `config.search_profiles_dir()` — the private overlay, a separate repository the
   implementing branch was barred from opening. An unconfigured profile is the
   documented INERT case: nothing is dropped before the ordinary title gate, which
   is recall-safe but means a big-tech fetch now spends its candidate budget on
   titles the old tuple used to discard (interns, sales, recruiting). A search run
   prints a one-line stderr notice naming the missing key, so this is visible, not
   silent. Copy the example persona's three lists as a starting point and tune
   them — in particular decide, for the five words the decision was about
   (`principal`, `distinguished`, `fellow`, `data scientist`,
   `research scientist`), whether each belongs in `include` ("check it out") or
   `soft_exclude` ("probably not, but read the JD").

2. **The candidate budgets were sized against the old, narrower fetch.**
   `fetch_workday` caps at `max_candidates=60`; `fetch_amazon`, `fetch_apple` and
   `fetch_meta` at `80`. The cap is applied in the order the search pages return
   rows, so admitting more titles can displace wanted roles past the cap — and a
   role never fetched leaves no filtered row and no snapshot trace, which is the
   exact silent-loss shape this work exists to remove. The decision file's Option C
   proposed raising the caps (60 → 100 Workday, 80 → 120 the others) and named the
   cost: more detail fetches per board on every run, against four third-party APIs.
   Nobody has measured how much slack the caps actually have, so the PR changed
   neither the numbers nor the request volume.

**Third consequence: an owed canary run.** The same PR edited
`skills/job-search/SKILL.md` and `reference.md` with more than ~20 instruction
lines, and the Step 1 bullets change what an agent DOES with a review row, so
`evals/README.md`'s risk-based gate calls for a `job-search` canary run rather
than a skip. It was recorded as **debt**, pointing at this task, for two reasons:
the canaries are live runs against third-party job boards, and — decisively —
with no `word_filter` in the real profile they would exercise the INERT path and
measure nothing about the change. Configuring the profile (item 1) is the
precondition that makes the run worth its cost, which is why the run lives here
rather than in a task of its own.

Related: the recency half of the same branch (first search at an employer is not
age-filtered) is documented in `skills/job-search/reference.md` § Recency filter.

## Definition of done

- The overlay profile carries a `titles.word_filter` block with all three classes,
  and a search run no longer prints the "no titles.word_filter block" notice.
- A recorded measurement (not an estimate) of how full each big-tech candidate
  budget runs with the new profile — e.g. the count of prefilter-surviving titles
  per board per run — written into the task's `worklog.md`.
- Either the caps are raised with that measurement quoted as the reason, or the
  task records why the current numbers are enough.
- The owed `job-search` canary run is recorded under `evals/results/` per
  `evals/README.md`, run AFTER the profile carries its `word_filter` block so the
  canaries exercise the configured path rather than the inert one.
- `skills/job-search/scripts/tests` stays green.
