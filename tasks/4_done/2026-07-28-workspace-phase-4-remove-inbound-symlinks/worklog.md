# Worklog — 2026-07-28-workspace-phase-4-remove-inbound-symlinks

<Append-only, newest at bottom, one entry per session. Keep entries short:
what moved, what's next, what surprised you.>

## 2026-07-29 — session 1 (agent)

- Bookkeeping only: the work was already implemented and pushed as PR #86
  (branch `phase-4/remove-inbound-symlinks`, two commits on top of
  `phase-3/review-gate`) before this session started. Moved the task from
  `0_backlog/` to `3_in-review/` and set `Claimed-by`.
- Same discrepancy as phase 3: the task's "Blocking preconditions" section
  says "Phases 0 and 3 merged" as already true, but PRs #81–#85 are all
  still open, not merged to `main`. Left the precondition text untouched
  per instructions.
- Commits on `phase-4/remove-inbound-symlinks`:
  - `1b837b7` "Delete the eight inbound symlinks: no private path wears a
    public name". Deletes all eight symlinks `bootstrap_overlay._overlay_
    links()` used to create (4 personal `skills/job-search/profiles/*.yaml`
    filenames, 2 `references_private/` folders, 2 overlay-only interview
    skill dirs). Replaces them with `config.search_profiles_dir()` /
    `config.skill_references_dir()` accessors (from phase-0b) and
    git-ignored `.claude/skills/<name>` / `.cursor/skills/<name>` links
    pointing straight at `private/skills/<name>`. Fixes two consumers the
    execution plan hadn't listed (`validate_filter_variants.py`,
    `search_recall_audit/store_refilter.py`) that had hardcoded the old
    path. Notes a follow-up filed as `tasks/0_backlog/2026-07-29-vendored-
    config-repo-root-wrong` for a wart it worked around rather than fixed.
  - `7809b4b` "Acknowledge the phase-4 review range" — ledger-only commit.
- Surprise: none beyond what the commit message already documents — the
  work matches the DoD closely. Verified independently that `.claude/
  skills` and `.cursor/skills` both resolve to exactly 12 symlinks
  (10 public + 2 private) — see verification.md — though `.cursor/skills/`
  also holds one unrelated, untracked plain directory (`github-manager`,
  not a symlink, not part of this repo's manifest-generated set).
- Verified on `chore/workspace-phase-bookkeeping` (based directly on
  `phase-4/remove-inbound-symlinks`) — see `verification.md`.

**2026-07-29 (later session)** — moved `3_in-review/` → `4_done/`: PR #86
(commits `1b837b7`…`7809b4b`) is merged into `main`. No content change.
