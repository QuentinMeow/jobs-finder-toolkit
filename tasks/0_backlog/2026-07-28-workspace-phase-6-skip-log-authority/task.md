# Workspace phase 6 — make the skip-log authoritative, not derived

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Stop regenerating the applications log from the folders, so deleting an application
cannot re-open the posting.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 6". `status.py` `sync_log()` does a
wholesale `write_text()` from a scan of the application folders, so deleting a rejected
application and re-syncing drops its rows and job-search re-surfaces the posting as fresh.

**Not optional after phase 5** — phase 5 makes deletion look safe while this is outstanding.

Must stay **one URL-keyed file**, not per-company markdown: `already_considered()` matches
normalized URL first and is deliberately key-independent, so sharding by company key would
turn every alias split into a re-drafted application (and measured +25% tokens per draft leg).

Two consumers read the old file and must move together: `search_jobs.load_considered` and
`handoff._posting_keys`. `search_jobs.profile_dir()` returns its first candidate when none
holds a log — fix it to use the accessors or both skips silently switch off.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phase 5 merged.

## Definition of done

- [ ] `market/logs/applications.jsonl` append-only, URL-keyed, never regenerated
- [ ] `--sync-log` demoted to a union-only upsert that cannot truncate
- [ ] One-time backfill from the 242 folders plus the existing log, verified row-count
- [ ] **The proof:** the user deletes a rejected application, search re-runs, the posting does
      **not** resurface
- [ ] Gate command clean
