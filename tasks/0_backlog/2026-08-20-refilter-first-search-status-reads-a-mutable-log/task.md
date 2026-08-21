# Refiltering one snapshot twice returns two different review sets

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GH #243, the owner's follow-up comment; the 2026-08-20
  `fix/filter-pipeline-reports` branch fixed the explicit-bound half and left this one
- **Claimed-by**:

## Goal

Refiltering a saved snapshot with the same profile and the same flags returns the same
answer whenever it is run, so a replay is evidence rather than a second opinion.

## Context

`--refilter` exists to re-answer filter and rank questions from a captured snapshot
without re-fetching, and it anchors posting-age math to the snapshot's fetch time so
ages never drift. First-search status does NOT get that treatment: `is_first_search`
reads `config.company_search_log_path()`, which the FETCH run mutates on success. So the
snapshot is frozen and the thing it is filtered against is not.

The owner measured it. A technical-writer market snapshot of 337 rows produced 127
review rows; refiltering that exact snapshot six minutes later with the same profile,
age bound and `--include-recent` produced 118, because the first run had written the
company-search log and only four rows still read as first-search. The two main-result
JSON files were byte-identical, so the difference is confined to the uncertain set —
which is exactly the set a reviewer is asked to work through.

Two candidate fixes, both outside the files that branch owned:

1. **Capture provenance** — record each posting's first-search status (or the whole
   company-search-log token set) in the snapshot at fetch time
   (`skills/job-search/scripts/snapshot.py`), and have the refilter path read it back
   instead of the live log. Costs a snapshot schema version bump; makes a replay exact.
2. **Ignore mutable history on replay** — treat a refilter as though the log had not
   moved since the fetch. Cheaper, and it still cannot reconstruct what the log said if
   the snapshot does not carry it.

Related, do not confuse: the branch's `cli_max_age_days` change makes an explicit
`--max-age-days` suppress widening entirely, which removes the symptom only for runs
that pass that flag. A profile-window refilter still replays against a moving log.

## Definition of done

- Two refilters of one snapshot with identical flags produce identical main results AND
  identical review sets, proven by a test that mutates the company-search log between
  the two runs.
- The snapshot schema change (if taken) is versioned, and an older snapshot still
  refilters or refuses with a clear message.
- `python automation/gates/run_gates.py --impact-from origin/main` green.
