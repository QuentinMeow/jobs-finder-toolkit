# Worklog — 2026-07-31-tracker-location-rollup-is-any-matches

## 2026-07-31 — session 1 (agent, branch `wip/35-pipeline-parse-defects`)

- Reproduced both halves from fixtures at the branch tip: a folder with one
  Springfield and one London posting reported `ok / metro` and exited 0, and a
  blank-`location` posting whose own JD said "Berlin, Germany" was invisible in
  both the LOCATIONS column and the verdict.
- `app_location_assessment` now assesses each posting from its own
  `location`/`jd_file`/`workplace` and takes the WORST verdict
  (`no_match` < `review` < `match`), mirroring `handoff.check_location_policy`.
  `review` still never fails the command; `unreadable` still does.
- `app_locations` and the new `job_location_strings` mirror
  `handoff.job_locations`: own `location`, else own `jd_file`. **No fall-back to
  the folder's top-level `location`** — for a posting that says nothing about
  where it is, the folder summary is a guess, and handoff already refuses it. The
  cost is a `review` row, which never blocks.
- `check_locations` now names the offending posting by role in the row and in
  `--json` (`postings` / `offending` / `unclassified`), so a mixed folder no
  longer reads as wholly out of policy.
- **The task's before/after counts over `config.applications_root()` were not
  produced and could not be**: that root is under `private/` and this branch is
  forbidden to read it. The task itself says "ship it with a measurement, not on
  inference", so this is the one bullet in its definition of done that is left
  open on purpose. The PR body carries the plain-words expectation instead, and
  the owner's own first `--check-locations` run is the measurement.
