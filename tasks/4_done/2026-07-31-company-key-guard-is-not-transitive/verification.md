# Verification — 2026-07-31-company-key-guard-is-not-transitive

Run on 2026-07-31 against `fix/06-company-key-guard-transitive` (based on
`chore/05-process-records-true`). Every transcript below is real output, trimmed to the relevant
lines. No company name, application slug or company key from the private tree appears here; the
employer names in the fixtures are invented and ship in the public test file.

## The regression: the reproduced mutation passes the OLD guard and fails the new one

The mutation is the one the adversarial review reproduced — the company normalisation extracted out
of `build_coverage` into a module-level helper that reads `company_key or company`:

```
 def _company_identity(m: dict) -> str:
     return _norm_company(m.get("company_key") or m.get("company"))
 ...
-            base_co = _norm_company(m.get("company"))
+            base_co = _company_identity(m)
```

**OLD guard, mutation applied to the real `automation/search-recall-audit/audit.py`:**

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests \
      -p 'test_company_key_additive.py' -v
test_match_paths_do_not_mention_company_key ... ok
test_the_guard_list_is_not_vacuous ... ok
test_the_guard_would_catch_a_planted_mention ... ok
test_skip_sets_are_identical_with_and_without_company_key ... ok
test_the_fixture_actually_produces_a_skip_set ... ok
test_the_keyed_fixture_really_carries_the_key ... ok
Ran 6 tests in 0.256s
OK
```

The rest of the tree stayed green under the same mutation, which is what made it invisible:

```
$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 430 tests in 17.827s          OK
$ JOBHUNT_CONFIG=$PWD/config.example.yaml .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
Ran 333 tests in 13.772s          OK
```

**NEW guard, same mutation applied to the same real file:**

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_company_key_additive.py'
FAIL: test_match_paths_do_not_mention_company_key (function='automation/search-recall-audit/audit.py::build_coverage')
AssertionError: Lists differ: ['build_coverage -> _company_identity'] != []
  : automation/search-recall-audit/audit.py::build_coverage reaches 'company_key' through
    build_coverage -> _company_identity. That function decides a skip, dedup, filter or
    coverage outcome, [...]

FAIL: test_coverage_folders_are_identical_with_and_without_company_key
AssertionError: Tuples differ: () != ('acme-labs-international-data-engineer-20260730',)
  : build_coverage returned a different set of same-company folders once every meta.yaml
    carried a company_key. On an alias merge that suppresses a genuinely new posting.

Ran 14 tests in 0.310s
FAILED (failures=4)
```

The message names the call path, which was the point. The other two failures are the mutation
regression tests themselves: they apply the mutation to the *unmutated* source and refuse to run
against a file that already carries it — loud by design (`re-derive the mutation against the current
source`) rather than silently checking nothing.

Both halves of the new guard fire on it independently: the source walk (`build_coverage ->
_company_identity`) and the behavioural check (one same-company folder became none). The mutation
was reverted with `git checkout --` after each run; `git status --short` clean.

## The behaviour the invariant exists to protect, measured

On a fixture whose two display strings share one key — an alias *merge* — a new posting at the
merged employer:

```
keyed=False  folder identities=[['acme labs international'], ['acme labs']]
             folders_same_company for a NEW posting -> ['acme-labs-international-...']  (1 match)
keyed=True   folder identities=[['acme labs'], ['acme labs']]
             folders_same_company for a NEW posting -> []                               (0 match)
```

That is a genuinely new posting being suppressed, reproduced exactly as the review reported it.
It is now the assertion in `test_coverage_folders_are_identical_with_and_without_company_key`.

## The closure walk, measured over all 26 guarded roots

Same-module call closure, breadth-first, fixed point, `MAX_CLOSURE_DEPTH = 8` as a tripwire that
raises rather than truncating:

```
closure sizes  : 1 to 21 functions (link_message is the largest at 21)
deepest closure: 4 hops (skip_log.read_postings)
$ .venv/bin/python -m unittest ... test_no_closure_reaches_the_depth_limit ... ok
```

`test_the_walk_actually_leaves_the_function_body` pins that `build_coverage`'s closure really
reaches `canon` and `_norm_company`; without it a broken resolver would make all 26 roots pass on
an empty walk.

## The carve-out, and the search for others

The walk was run over all 26 closures and asked which reachable functions spell the field out. The
answer is **one**, and it is the one phase 7 already documented:

```
skills/email-assistant/scripts/application_context.py::find_application_matches
    HIT: find_application_matches -> _records
(25 other roots: no hit)
```

Cross-checked against the raw text of all ten guarded modules — `company_key` occurs in exactly one
of them, on one line of `_records`. (`reconciliation.py`'s `company_match_key` does not contain the
literal.) So the carve-out list is one entry, with a written reason, and no second legitimate
mention had to be discovered or argued about.

```
$ .venv/bin/python -m unittest ... TheCarveOutIsNarrow -v
test_every_carve_out_is_live_and_pinned ... ok
test_no_carve_out_exempts_a_guarded_function ... ok
```

The entry pins the exact whitespace-normalized line that may mention the field, so a *second* use
inside `_records` goes red even though `_records` is on the list, and a stale entry (the function
stopped reading the key) also goes red.

## Suite, clean tree

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_company_key_additive.py'
Ran 14 tests in 0.404s            OK      (6 before this task)
```

## Full gate

```
$ zsh <scratch>/gate.sh
===== gates =====        vendor-drift, byte-compile, reconcile, leak-guard, review-gate,
                         instruction-budget, verify-links, mail-safety
===== unit suites =====  reconcile, gardener, hooks, shared, publish, store-example,
                         resume-writer, job-search, filter-variants, app-tracker, github-wf
===== export dry-run ===== export-strict
ALL GREEN
```

CI's shape reproduced in a detached worktree with no `private/` and no `config.yaml`:

```
$ git worktree add --detach <scratch>/ci_wt HEAD
$ test -d <scratch>/ci_wt/private     -> absent
$ test -f <scratch>/ci_wt/config.yaml -> absent
$ .venv/bin/python -m unittest discover -s <scratch>/ci_wt/automation/shared/tests
Ran 438 tests             OK
$ git worktree remove <scratch>/ci_wt
```

## The correction carried into phase 7b's record

`tasks/3_in-review/2026-07-31-workspace-phase-7b-company-key-on-meta/verification.md` recorded the
stale-mapping diff as unfollowable because `meta_updates.tsv` is in neither repository. It is in the
implementing session's scratchpad, and the diff was re-run here before the line was corrected:

```
$ .venv/bin/python -c "<read the TSV; compare proposed_company_key against the committed
                        company_key in each meta.yaml>"
tsv rows: 243
agree: 242  disagree: 1  unlocatable: 0
```

The single disagreeing row is the joint-venture folder the owner's ruling moved: the TSV proposes
the joint venture's own key, the committed file carries the parent brand's. That is the expected
and only disagreement, so the mapping is the committed index's, not a stale copy. The line in that
file now says so instead of saying the check could not be made. The TSV itself is scratch, contains
real employer names, and is not copied into either repository.

## What is deliberately NOT covered

Written at length in the test module's docstring; in short: **cross-module calls are not followed**
(the cross-module hops that decide anything — `skip_log.read_postings`/`fold`/`fold_key`,
`Registry.match_keys`/`canonical`/`_entry_keys` — are guarded as roots instead), method calls on
values whose class cannot be inferred, dynamic dispatch and decorator source, and any data flow that
never spells the field out. The behavioural half is the answer to the last one, which is why both
halves exist.
