# Document the search-JSON provenance fields and the refilter store lookup

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: PR for issues #244 / #245 / #284 (branch `fix/search-json-identity`),
  which was scoped to scripts + tests only; harness files were off limits because a
  separate agent held the skill's instruction surface.

## Goal

The job-search skill's own docs describe the machine handoff as it was before the
provenance fields existed. Bring `skills/job-search/SKILL.md` and
`skills/job-search/reference.md` in line with what the scripts now emit, so a reader
learns the full-JD retrieval path from the skill rather than by inspecting a JSON row.

## Context

Two writers changed in `skills/job-search/scripts/search_jobs.py`:

- `write_json_output` / `_json_rows_with_store_key` — every `--json-out` row now
  carries `run_id`, `source_snapshot`, `source_snapshot_row`,
  `description_is_preview`, `description_full_chars`, and, on clipped rows only,
  `full_description_command` (a copy-pasteable command that prints the untruncated
  JD out of the snapshot). The payload is still a bare list of rows, because
  `handoff.py` consumes it that way.
- `review_payload` / `write_review_report` — the filter-review body moved to
  `schema: 3`, gained `run_id`, and each row gained `description_full_chars` and
  `source_snapshot_row`. Its `instruction` string now carries the retrieval command
  as well as the validator command.

Two behavioral notes worth a documented line:

- `--refilter` now reads the store index (read-only, no build, no lock) so a replay
  emits the same `store_key` a fresh run does, and the `store: N tracked, M new`
  summary line now appears on refilter runs too when a store is configured.
- `run_id` is `<YYYYMMDDTHHMMSSZ>-<4 hex>`, not a bare timestamp; per-run artifact
  filenames (`<run_id>-<slug>.md`, `<label>-filter-review-<run_id>.json`) carry the
  tail. Anything in the docs that shows a bare-stamp filename is now stale.

Not covered by that PR and worth deciding here: `--json-out` records the run's
arguments only indirectly (the row's `run_id` names the per-run discoveries report,
whose meta block holds `max_age_days`, `visa_policy`, stage and counts). Issue #244
asked for "recorded arguments" in the artifacts; document that join, or decide the
review payload should carry the filter arguments itself.

## Definition of done

- `skills/job-search/SKILL.md` and `reference.md` describe the emitted row fields and
  the full-JD retrieval path, with no bare-timestamp run-artifact filename left.
- The eval gate is discharged per AGENTS.md (`evals/canaries/job-search.yaml` run, or
  a recorded one-line skip rationale for a mechanical doc edit).
- `automation/gates/run_gates.py --impact-from origin/main` exits 0.
