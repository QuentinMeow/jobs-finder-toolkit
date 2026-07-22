# Worklog — 2026-07-22-application-progress-calendar

## 2026-07-22 — session 1 (claude, branch email/stage-2-progress-calendar)

- Implemented meta.yaml **schema v5** exactly per
  `design/application-progress-calendar/README.md`: kept `jobs[].status` +
  folder rollup unchanged; replaced the free-text `stage` with the structured
  `jobs[].progress` ({phase, state, label?, calendar_item?, updated_at?,
  source?}); validation enforces the phase/state enums, `other`-requires-label,
  email-source-requires-ref, calendar-item/timestamp shapes, and the coupling
  `state closed <=> status rejected|ignored`. The retired `stage` key (per-job
  or top-level) is rejected. Canonical module: `automation/shared/job_metadata.py`
  (+ `migrate_job_progress`, `default_progress_for_status`,
  `legacy_stage_phase`).
- Added the **formatting-preserving v4->v5 migration**
  (`metadata_editor.plan_v4_to_v5_migration`: version scalar rewritten in
  place, stage lines removed, progress blocks appended; comments/quoting/order
  survive; fails closed on anything else) and the preview-first fleet CLI
  `skills/application-tracker/scripts/migrate_to_v5.py` (dry-run unified
  diffs; `--write` = checksum-guarded atomic writes). Migrated both tracked
  fixtures with the tool itself (example app + resume-writer E2E fixture).
  **The owner must run `migrate_to_v5.py` (preview, then `--write`) on the
  private overlay applications before the next tracker run — v4 is now
  rejected everywhere.**
- Added `config.calendar_path()` (default
  `<applications_root>/0_profile/calendar.md`; `paths.calendar_md` override;
  example key + example calendar file shipped) and the new pure module
  `automation/shared/calendar_todos.py`: section/marker contract, stable
  `cal-*` ids, checkbox bullets, exact time + IANA timezone required for
  `scheduled`, follow-up dates, append-only history (`superseded`/`cancelled`
  occurrences preserved), unmarked lines byte-for-byte, malformed markers /
  duplicate ids / unknown keys fail closed. Vendored into the tracker.
- `status.py`: `--update`/`--update-job` now also stamp the deterministic
  progress summary and update any linked calendar entry **in one transaction**
  (meta first, calendar commits; a calendar failure rolls the meta pre-image
  back — no one-sided writes). New commands: `--update-progress <slug>
  <role-match> --phase --state [--label]` (never moves folders; creates the
  calendar entry for scheduling states; `--state scheduled` requires the
  confirmed time on the entry), `--check-calendar` (read-only cross-check),
  `--sync-calendar [--write]` (preview-first mapping of checked boxes,
  `reschedule_to`, and `cancel: true` back to progress). Pipeline table gained
  "Action needed" + "Overdue waiting (past follow-up)" blocks. `--stage`/
  `keep` removed with the schema. `filter_jobs.py`: `--phase` /
  `--progress-state` filters + PHASE/P-STATE columns (stage removed);
  `handoff.py` scaffolds drafted progress; outlook `application_context.py`
  reports phase/state instead of stage.
- Tests: new `automation/shared/tests/test_calendar_todos.py` (parse/render,
  byte-preservation, fail-closed cases, reschedule/cancel history),
  migration tests in `test_metadata_editor.py`, progress-validation +
  mapping tests in `test_job_metadata.py`, and
  `skills/application-tracker/scripts/tests/test_progress_calendar.py`
  (update-progress + calendar transaction, scheduled guard, sync
  preview/write, reschedule keeps superseded occurrence, cancellation never
  rejects, malformed/duplicate/missing-entry fail closed, calendar checksum
  race rolls the meta write back, fleet migration preview->write, pipeline
  health). All existing tracker/resume-writer/job-search/outlook/shared/
  publish suites updated to v5 fixtures and green (651 tests total).
- Docs: tracker SKILL.md schema section rewritten to v5 (progress, calendar
  file, new commands — behavioral edit, see canary-gate note below); v4/stage
  references updated in AGENTS.md cookbook line, handbook (application-folders,
  architecture, command-cookbook, repo-map), resume-writer reference.md +
  SKILL.md, job-search SKILL.md, outlook SKILL.md, tracker canaries.yaml,
  evals/rubrics/artifact-quality.md, roadmap/current-state.md.
- **Canary gate: NOT RUN** (this environment cannot execute agent canary
  sessions). The SKILL.md/canaries edits are behavioral (new commands +
  schema), so per `evals/README.md` the application-tracker canaries must
  pass — and the run be recorded in `evals/results/` — before this branch
  merges.
- Environment note: `gardener.py verify-links` reports one pre-existing
  broken reference (`AGENTS.md -> skills/coding-interview/`) because the
  private overlay is not mounted in this worktree; unrelated to this change
  and untouched by it.

## 2026-07-22 — session 2 (claude, canary gate + fixes)

- Rebased onto `email/stage-1-provider-contract` (skill-rename merge landed
  via git rename detection; one roadmap conflict hand-merged); scrubbed an
  absolute home path from verification.md that the armed leak guard caught.
- Ran the full application-tracker canary set at head (5/5 PASS —
  `evals/results/application-tracker-efcde9a-20260722.md`). The gate
  found and this session fixed: the metadata-editor block-mapping
  end-mark overshoot (44d26fa + 3 regression tests + known-issue record)
  and the stale LESSONS v4 wording (e2ebe38).
- Full battery re-verified on the combined branch: shared 285, publish 30,
  tracker 42, email-assistant 24, job-search 210, resume-writer 86,
  example render, reconcile, verify-links, armed leak guard — all green.

## 2026-07-22 — session 3 (codex, owner calendar-UX review)

- Researched task/calendar information hierarchy and real ATS pipeline models;
  recorded the sources and resulting rules in
  `design/application-progress-calendar/ux-revision.md`.
- Reworked managed calendar rows so confirmed events lead with the local
  date/time, todos lead with a verb and optional deadline, and the company +
  role is a single link to `notes.md` or `meta.yaml`. Multi-line YAML markers
  now upgrade to one hidden compact JSON line; duplicated email evidence is
  omitted because metadata remains the provenance source.
- Added optional `action`, `due_at`, `ends_at`, and `details` calendar fields;
  direct scheduling flags on `--update-progress`; and preview-first
  `--refresh-calendar [--write]` for a display-only migration. Renamed the
  human sections to “Waiting and follow-up” and “Interview schedule”, while
  retaining parser support for the original headings.
- Expanded broad workflow coverage with assessment `in_progress`,
  `decision_required`, `follow_up_required`, and `paused` states plus
  `reference_check` and `work_authorization` phases. Employer-specific round
  names remain `label` values instead of enum growth.
- Refreshed the private calendar in place: five managed entries are consistent,
  show their event/action signal, and link to current role context. Reorganized
  unlinked events and cleanup todos without changing any application status.
- Verification: shared 295 PASS; tracker 47 PASS; job-search suite PASS;
  compile, vendor drift, 215 private metadata files, instruction budget, and
  public leak guard PASS. Resume-writer ran 85/86 with only its documented
  LibreOffice silent-PDF flake failing twice; the changed metadata logic passed.
- Canary gate: pending before merge. The behavioral SKILL.md edit requires a
  fresh-session 5-canary run; this session cannot create the required isolated
  agent sessions under its collaboration policy. The previous same-day v5 run
  was 5/5 but predates this UX revision.
