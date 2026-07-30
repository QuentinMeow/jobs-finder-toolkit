# handoff.py creates application folders without recording the posting in the skip-log

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: workspace phase 6 implementation, 2026-07-30 (assessed and deliberately deferred)
- **Claimed-by**:

## Goal

Close the last window in which a posting can be worked on and then vanish from the
skip-log: a folder created by `handoff.py` and deleted before any `--sync-log`.

## Context

Phase 6 made the applications skip-log append-only, and made `status.py --update` /
`--update-job` append the posting event at the moment the status changes rather than
printing a "re-run --sync-log" reminder. That covers every status *transition*.

It does not cover *creation*. `skills/job-search/scripts/handoff.py` scaffolds the
application folder and writes `meta.yaml` (around `handoff.py:734`) without touching the
log, so the sequence "draft a posting → decide against it the same day → delete the
folder → run `--sync-log`" leaves no trace: the log never saw the posting, and
job-search will re-surface it. This is the residual case the phase-6 green gate passes
only because its proof syncs first.

Three things make this more than a two-line insertion, which is why phase 6 filed it
instead of doing it:

1. **Row-shape drift — the exact hazard phase 6 was built to avoid.** Both current
   writers go through `status.py`'s `build_log`, so their row shapes cannot diverge.
   `handoff.py` cannot call it: `build_log`/`load_application` live in the
   application-tracker skill, and one skill's `scripts/` may not import another's
   (`docs/handbook/skills-and-vendoring.md`). Hand-building the row from search-JSON
   keys (`title`/`company`/`url`, not `role`/`slug`/`date`) is how the two writers start
   disagreeing silently. **The clean version extracts `build_log`'s per-posting
   flattening into a shared `automation/shared/` module vendored into both skills, and
   does that first.**
2. **The path override.** `handoff._applications_jsonl(root, override)` composes the
   `--applications-root` branch from `config.CANDIDATE_DIRNAME` +
   `config.APPLICATIONS_JSONL_FILENAME`. A creation-time append needs to honour the same
   override or it writes into the wrong tree.
3. **A policy call that belongs to the owner, not to an agent.** `_run_group` returns
   exit 3 (location-blocked) and exit 1 (incomplete / no fresh JD) *after* the folder
   exists, and `_run_groups` already registers those postings as live. Recording them is
   consistent with how the rest of the pipeline treats them — but it also means a
   `--skip-jd-fetch` scaffold the owner immediately deletes becomes a permanent skip with
   no self-healing, repairable only with `--forget-log`. File that as a decision with a
   default path rather than choosing it silently.

## Definition of done

- [ ] The per-posting flattening lives once in `automation/shared/`, vendored into both
      job-search and application-tracker, with `sync_vendored.py --check` clean
- [ ] `handoff.py` appends the creation event through that shared shape, honouring
      `--applications-root`
- [ ] The exit-3 / exit-1 recording question is decided (queue item with a default path),
      not assumed
- [ ] A test: scaffold a folder via handoff against a temp tree, delete it, run
      `--sync-log`, assert the posting is still skipped
