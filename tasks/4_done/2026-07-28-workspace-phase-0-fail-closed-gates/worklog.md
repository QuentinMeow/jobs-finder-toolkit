# Worklog — 2026-07-28-workspace-phase-0-fail-closed-gates

<Append-only, newest at bottom, one entry per session. Keep entries short:
what moved, what's next, what surprised you.>

## 2026-07-29 — session 1 (agent)

- Bookkeeping only: the four commits this task's Definition of done maps to
  were already implemented and pushed as open PRs before this session
  started. Moved the task from `0_backlog/` to `3_in-review/` (work done,
  PRs open, nothing merged yet) and set `Claimed-by`.
- Confirmed the four branches are a clean stack off `main`, one commit each:
  - `phase-0a/leak-guard-fails-closed` — `72d45e2` "Make the leak guard fail
    closed, and run it at commit time" (PR #81). Splits the token union into
    an `identity_tokens()` arming set and a `supplementary_tokens()` set that
    can widen but never arm; an empty identity set is now exit 2 before any
    scan; pre-commit scans the staged index and rejects `git add -f
    private/`; pre-push no longer passes `--allow-unarmed`.
  - `phase-0b/config-accessors` — `2d20f34` "Stop config discovery and its
    consumers from failing open" (PR #82). Discovery now raises
    `ConfigNotFound`/`ConfigError` instead of silently defaulting; adds ten
    path accessors (`overlay_root`, `candidate_dir`, `blacklist_path`,
    `story_bank_path`, etc.); fixes the job-search blacklist preflight, which
    previously swallowed a missing/overlay blacklist file with `except
    Exception: pass`.
  - `phase-0c/skill-visibility-ssot` — `8df3847` "Make SKILL.md frontmatter
    the only source of skill visibility" (PR #83). New
    `automation/publish/sync_skill_manifests.py` derives the exporter's
    skill list, `marketplace.json`, and both `.claude/skills`/`.cursor/skills`
    symlink trees from `SKILL.md` frontmatter; adds reconciler check
    `skill-manifests` (6 → 7 checks); fixes `search-recall-audit` never
    having shipped in any of the previously-drifted lists.
  - `phase-0d/link-checker-and-hooks` — `eb345e7` "Widen the link checker,
    add --require-roots, give the overlay hooks" (PR #84). `verify_links`
    now sources every tracked `.md` (252 files, was 23); adds
    `--require-roots` to the reconciler (7 → 8 checks); adds two hooks to
    the public tree that `bootstrap_overlay.py` installs into
    `private/.git/hooks/`.
- Surprise: PR #84's commit message notes it left a follow-up,
  `tasks/0_backlog/2026-07-29-vendored-config-repo-root-wrong`, filed by
  later phase-4 work, not this task — left untouched per this session's
  scope.
- Verified the stack (all four commits) on
  `chore/workspace-phase-bookkeeping`, which is based on
  `phase-4/remove-inbound-symlinks` and therefore carries phases 0, 3, and 4
  together — see `verification.md`. Did not check out the individual
  `phase-0*` branches since the bookkeeping branch already carries their
  work and the checks are not phase-specific.

**2026-07-29 (later session)** — moved `3_in-review/` → `4_done/`: PRs #81–#84
(commits `72d45e2`…`eb345e7`) are merged into `main`. No content change.
