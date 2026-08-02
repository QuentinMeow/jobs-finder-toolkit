# Worklog — 2026-07-31-company-key-guard-is-not-transitive

## 2026-07-31 — session 1 (agent)

- Reproduced the review's mutation on the real `audit.py` and confirmed the old body-only guard
  passed it (6/6 OK) with the shared and job-search suites green, then confirmed it changes the
  answer: one same-company folder became none on an alias-merge fixture.
- Replaced the `inspect.getsource` check with a same-module `ast` call-closure walk from each of
  the 26 guarded roots. Depth is a raising tripwire (`MAX_CLOSURE_DEPTH = 8`, deepest real closure
  is 4), and a finding reports the call path (`build_coverage -> _company_identity`).
- Designed the carve-out before the walker, because a naive walk fires on
  `application_context._records`, which is where the field is legitimately emitted. One entry, with
  a written reason and its exact mentioning line pinned, plus a test that the list can never
  overlap `MATCH_PATHS`. Swept all 26 closures for other legitimate mentions — there are none;
  `_records` is the only function in any guarded module that spells the literal out.
- `test_the_guard_list_is_not_vacuous` now checks `REQUIRED_GUARDS ⊆ MATCH_PATHS` by name instead
  of `len(...) >= 26`, so a swapped row goes red.
- Extended the behavioural half to `audit.build_coverage` in its own method (its signature takes no
  arguments, so it cannot join the `(log, root)` table) and added an alias-merge row to the fixture,
  without which every key normalizes back to its own company string and the comparison is vacuous.
- Corrected phase 7b's verification line about `meta_updates.tsv`: the file is in the session
  scratchpad, and the diff re-run here agrees on 242 of 243 rows with the one expected exception.
- Next: nothing outstanding. No queue item filed — the cross-module stopping point is reversible
  (widening the walk later costs nothing that is not already written down), so it was decided in
  the docstring rather than put in front of the owner.
