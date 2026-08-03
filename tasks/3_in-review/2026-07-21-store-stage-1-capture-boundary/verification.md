# Verification — 2026-07-21-store-stage-1-capture-boundary

Written 2026-08-02 as part of moving this task out of `1_in-progress/`, where it
had sat for 12 days with the code already merged. Four of five DoD bullets were
already ticked in `task.md`; this file records what is checkable in the tree
today and names the one bullet that is not.

## The stage is shipped, by the roadmap's own account

`docs/roadmap/current-state.md:47-49`:

```
- **Job store**: raw-data-layer stages 0–4 shipped (PRs #49–#53) — library,
  capture boundary, builder, pipeline integration, retention/gardener.
```

"capture boundary" is this stage. `task.md`'s own `Claimed-by` line says the same:
*"prior sessions (shipped in PR #50; only the multi-day measurement remains before
review)"*.

## The code and its tests are in the tree and green

```
$ ls automation/store/
gc_store.py  generate_fixture_store.py  store_show.py  validate_store.py

$ .venv/bin/python automation/gates/run_gates.py
  PASS   tests-shared  exit 0    20.0s
  PASS   validate-example-store  exit 0     0.3s
  PASS   tests-job-search  exit 0    78.0s
ALL GREEN (29 gates, 2 skipped: reconciler-require-roots, verify-links-require-roots)
```

## The one bullet that is NOT discharged

```
- [ ] Several days of real runs measured: growth/run, capture overhead <1 s, dedup ratio.
```

It needs the owner to run real searches across several days; no agent can produce
it, and nothing in this closure fabricates it. That is precisely the shape of the
four siblings already sitting in `3_in-review/` — `docs/roadmap/current-state.md:39-41`
describes them as *"held for missing definition-of-done evidence"*.

## Why `3_in-review/` and not `4_done/`

`tasks/README.md`: `3_in-review` is "work done, awaiting review/merge";
`4_done` is "merged/verified". The work is done and merged, the verification is
not complete, and `1_in-progress` ("claimed and being worked") was false — nobody
has worked it since 2026-07-21. `3_in-review` is the only folder whose definition
is true of this task today.
