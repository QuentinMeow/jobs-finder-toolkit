# Workspace phase 6 — make the skip-log authoritative, not derived

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Stop regenerating the applications log from the folders, so deleting an application
cannot re-open the posting.

## Context

Detail in [the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) under "Phase 6". `skills/application-tracker/scripts/status.py:1954`
`sync_log()` still does a wholesale `write_text()` at line 1967 from a scan of the application
folders, so deleting a rejected application and re-syncing drops its rows and job-search
re-surfaces the posting as fresh.

Phase 0 changed *where* the log is found — `status.py:152` is now
`config.applications_log_path()` instead of a `0_profile` literal — but not *how* it is written.
The regeneration is untouched.

**Not optional after phase 5** — phase 5 makes deletion look safe while this is outstanding.

Must stay **one URL-keyed file**, not per-company markdown: `already_considered()` matches
normalized URL first and is deliberately key-independent, so sharding by company key would
turn every alias split into a re-drafted application (and measured +25% tokens per draft leg).

Two consumers read the old file and must move together: `search_jobs.load_considered` and
`handoff._posting_keys`.

**Check what phase 5 left you.** `search_jobs.profile_dir()`
(`skills/job-search/scripts/search_jobs.py:158-181`) returns its first candidate when no probe
holds a log; phase 5 was supposed to point it at `config.applications_log_path()` /
`config.company_search_log_path()` directly. If phase 5 deferred that, fix it **before**
changing the file format — otherwise the skips are already off and this task's proof passes for
the wrong reason.

Rule 4 of the execution plan applies: a review-ledger row per commit, plus a closing ledger-only
commit.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phase 5 merged. **Met as of 2026-07-30, pending merge** — phase 5 is done and in review, and
`market/logs/` exists: both skip-logs now live at `private/market/logs/` behind
`config.applications_log_path()` and `config.company_search_log_path()`.

**Phase 5 already did this task's second bullet, and did it properly.** `profile_dir()` is
gone, not repointed — it searched for *a directory containing a log* and returned its first
guess when none matched, which is a shape that cannot be made safe. Both call sites read the
accessors directly, and the skip was proved live after the move: 367 URLs, 369 (company, role)
pairs. So this task inherits a working accessor and can go straight at the file format.

**One thing got more urgent, not less.** Phase 5 moved applications' durable knowledge out
into `companies/`, which is what makes an application look disposable — while `sync_log()`
still regenerates the log from the folders. Deleting a rejected application and re-syncing
still re-opens the posting. The gap between "looks safe" and "is safe" is now wide open.

## Definition of done

- [ ] `market/logs/applications.jsonl` append-only, URL-keyed, never regenerated
- [ ] `--sync-log` demoted to a union-only upsert that cannot truncate
- [ ] `search_jobs.profile_dir()` reads the log accessors directly (verify; phase 5 may have done it)
- [ ] One-time backfill from the 242 folders plus the existing log, verified row-count
- [ ] **The proof:** the user deletes a rejected application, search re-runs, the posting does
      **not** resurface
- [ ] Gate command clean

## Held in `3_in-review`, 2026-07-31 — what is missing

A bookkeeping pass promoted six finished in-review folders to `4_done` and deliberately left this
one behind. PRs #114 and #115 are merged and the evidence in this folder is otherwise excellent —
an `ALL GREEN` block, two mutation checks, an acceptance proof with a non-vacuity control. But
**all six definition-of-done boxes are `- [ ]`**, so the folder asserts in checkbox form that
nothing was done.

**The one substantive gap — the backfill — is closed, and here is the number.** Re-measured
2026-07-31 against the append-only skip-log resolved through `config.applications_jsonl_path()`:

```
events: 369
distinct urls: 367
```

That is exactly the 369-event backfill the phase specified, and it matches the 367-URL figure in
`docs/roadmap/current-state.md`. So this is a records gap, not a data gap, and it is **not**
urgent. What it needs is somebody with the branch in front of them ticking six boxes against
evidence that is already in `verification.md` — which is a claim this bookkeeping pass is not
entitled to make on the implementer's behalf.
