# Make `status.py --check-locations` a mandatory post-step of `handoff.py`

- **Status**: todo
- **Priority**: P1
- **Area**: job-search
- **Source**: `evals/results/stage2-benchmark-20260720.md:79-82`

## Goal

Have `handoff.py` refuse (or clearly flag) scaffolding an application folder that
`status.py --check-locations` would reject, so search cannot hand off a folder the
pipeline is going to bounce anyway.

## Context

In the Stage-2 pinned benchmark row, a handoff produced by `search_jobs.py` +
`handoff.py` was later rejected by the authoritative drafted-app location gate
(`status.py --check-locations` → `other_us`): an SF-hybrid role passed the
search-time heuristic via the known hybrid-counts-as-remote scoring branch (see
GH issue #21's location-heuristic family), but the JD fetched at handoff time was
silent on workplace, so the mismatch wasn't caught until later, and the
mis-handed-off folder was left in place for the owner to manually dispose of
(agents don't move status folders on their own).

Today, `handoff.py`'s `run()` (see `.agents/skills/job-search/scripts/handoff.py`,
around the `validate_meta(meta, app_dir=folder)` call near the end of `run()`)
validates the scaffolded `meta.yaml` for schema completeness but never calls
`status.py --check-locations` against the folder it just created — confirmed by
inspection, `handoff.py` contains no reference to `check_locations` or
`status.py` today. `status.py`'s `check_locations()` function (in
`.agents/skills/application-tracker/scripts/status.py`) already implements the
location-policy check standalone, keyed off `--statuses`/a status folder; the gap
is purely that `handoff.py` never invokes it for the one folder it just
scaffolded.

This is a distinct, complementary fix to GH issue #21 (the "Distributed" tag
false-`us_remote` heuristic bug itself, already fixed in
`scripts/shared/location.py`) — even with that heuristic fixed, other
location-mismatch classes (like the hybrid-counts-as-remote branch that caused
this specific mis-handoff) can still slip through search-time scoring, so a
post-handoff structural check is still worth having as a second line of defense.

Relevant files:
- `.agents/skills/job-search/scripts/handoff.py` (`run()`, where the post-scaffold
  validation happens today)
- `.agents/skills/application-tracker/scripts/status.py` (`check_locations()`,
  reusable for a single folder by passing the right `--statuses`/status-dir scope)

## Definition of done

- `handoff.py` calls the location-policy check against the just-scaffolded folder
  before returning, and surfaces a clear non-zero-exit warning (matching its
  existing pattern for incomplete `meta.yaml`) when the folder's location is a
  definite policy mismatch (not an "unknown" review row — those should stay
  non-blocking, per `check_locations()`'s existing category split).
- Verification: scaffold a handoff for a posting known to be a definite
  location-policy mismatch and confirm `handoff.py` exits non-zero and prints a
  location warning, e.g.:
  ```bash
  .venv/bin/python .agents/skills/job-search/scripts/handoff.py \
    --json <search.json> --select "rank N"
  # exit code and stderr should surface the location mismatch, not just
  # "meta.yaml: valid"
  ```
- No regression in `evals/job-search/canaries.yaml`'s existing handoff-touching
  canaries.
