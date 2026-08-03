# Verification — 2026-08-01-job-search-docs-route-the-location-policy-to-the-wrong-file

All runs on branch `docs/job-search-location-routing`, from the branch's own worktree
(`automation/gates/run_gates.py` resolves the repo root from `__file__`, so running the worktree's
copy audits the worktree). Base commit: `f360aec`.

## The three reported defects, re-verified before any edit

```
$ grep -n 'us_only' skills/job-search/scripts/scoring.py automation/shared/config.py
skills/job-search/scripts/scoring.py:316:            "us_only": loc_cfg.get("us_only", False),
automation/shared/config.py:628:        "us_only": lp.get("us_only", True),

$ grep -n 'location_ok\|location_policy' skills/job-search/scripts/search_jobs.py
72:from scoring import (  # noqa: E402
73:    ai_company_ok, date_ok, experience_ok, location_ok, posting_quality_ok,
856:        if not location_ok(p, profile):
        (no location_policy reference anywhere in search_jobs.py)

$ grep -n 'max_age_days: ' skills/job-search/profiles/_TEMPLATE.yaml skills/job-search/profiles/example.yaml
skills/job-search/profiles/_TEMPLATE.yaml:56:max_age_days: 3            # only postings from the last N days
skills/job-search/profiles/example.yaml:168:max_age_days: null
```

`scoring.location_ok` builds all four policy keys (`metro`, `allow_us_remote`, `us_only`,
`require_match`) from `profile["location"]`. `config.location_policy()` returns no `require_match`
key at all, so its callers get `automation/shared/location.py`'s own default of `True`.

## Which file the SEARCH gate actually reads — full 3x3 matrix

A scratch script set `location_policy.us_only` in `config.yaml` and `location.us_only` in the search
profile independently across `true` / `false` / absent, then classified the same posting
(`"Berlin, Germany"`) through both gates: `scoring.location_ok` (search) and
`handoff.row_location_verdict` (draft). Nine runs, one process each because the config loader caches.

```
$ for c in true false absent; do for p in true false absent; do
    .venv/bin/python prove_location_source.py $c $p; done; done

config.yaml location_policy.us_only : true     | profile location.us_only : true
  config.location_policy()['us_only'] resolves to : True
  SEARCH gate  scoring.location_ok(Berlin)        : DROP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : true     | profile location.us_only : false
  config.location_policy()['us_only'] resolves to : True
  SEARCH gate  scoring.location_ok(Berlin)        : KEEP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : true     | profile location.us_only : absent
  config.location_policy()['us_only'] resolves to : True
  SEARCH gate  scoring.location_ok(Berlin)        : KEEP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : false    | profile location.us_only : true
  config.location_policy()['us_only'] resolves to : False
  SEARCH gate  scoring.location_ok(Berlin)        : DROP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : false    | profile location.us_only : false
  config.location_policy()['us_only'] resolves to : False
  SEARCH gate  scoring.location_ok(Berlin)        : KEEP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : false    | profile location.us_only : absent
  config.location_policy()['us_only'] resolves to : False
  SEARCH gate  scoring.location_ok(Berlin)        : KEEP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : absent   | profile location.us_only : true
  config.location_policy()['us_only'] resolves to : True
  SEARCH gate  scoring.location_ok(Berlin)        : DROP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : absent   | profile location.us_only : false
  config.location_policy()['us_only'] resolves to : True
  SEARCH gate  scoring.location_ok(Berlin)        : KEEP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)

config.yaml location_policy.us_only : absent   | profile location.us_only : absent
  config.location_policy()['us_only'] resolves to : True
  SEARCH gate  scoring.location_ok(Berlin)        : KEEP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)
```

Reading the matrix:

- The SEARCH verdict is DROP in exactly the three rows where the **profile** says `us_only: true`,
  and KEEP in all six where the profile says `false` or omits the key. It is identical down each
  `config.yaml` column. **The search reads the profile and nothing else** — which is what the old
  `SKILL.md:71-72` got backwards.
- The last row is the default asymmetry with both keys absent: the search KEEPS the Berlin role
  (profile default `False`) and the draft gate calls it `mismatch (foreign)` (config default
  `True`). That is the silent behaviour this PR documents rather than changes.

## Gates (branch `docs/job-search-location-routing`, base `f360aec`)

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests   # JOBHUNT_CONFIG=config.example.yaml
Ran 557 tests in 58.245s
OK
JS_TESTS_EXIT=0

$ .venv/bin/python skills/job-search/scripts/validate_filter_variants.py --check
filter variant corpus clean: 84 cases
VARIANTS_EXIT=0

$ .venv/bin/python automation/gardener/verify_links.py
LINKS_EXIT=0

$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.
BUDGET_EXIT=0
  skills/job-search/SKILL.md   384 of 600 lines   (was 366; +18)
  skills/job-search/LESSONS.md 159 of 160 lines   (untouched)

$ .venv/bin/python automation/gates/run_gates.py
ALL GREEN (29 gates, 2 skipped: reconciler-require-roots, verify-links-require-roots)
GATES_EXIT=0
```

Both skips are the standard "private/ is not mounted" skips the runner reports in a public
checkout; CI never passes `--require-roots` either.

`run_gates.py`'s `example-render` gate rewrites the four tracked example DOCX/PDF artifacts
(binary output is not byte-reproducible). Those bytes are not part of this change, so they were
restored with `git checkout -- examples/` before staging.

## What this change did NOT do

`scoring.py`, `automation/shared/config.py`, and `automation/shared/location.py` are byte-identical
to `f360aec`; no default value moved, and `_TEMPLATE.yaml` keeps `max_age_days: 3` (only comments
were added around it). The `us_only` default asymmetry is filed for the owner at
`message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md`, default path
"change nothing".
