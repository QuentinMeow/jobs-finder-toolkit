# Workspace phase 4 — no private path may wear a public name

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**: agent (session 2026-07-29)

## Goal

Delete all eight symlinks that put private content at a public-looking path, replacing
them with config accessors and runtime skill links.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 4". The eight are created by
`automation/bootstrap_overlay.py` `_overlay_links()`.

**Why this is the core of layer 1:** four of them are
`skills/job-search/profiles/<personal-name>.yaml` — the *filename itself is a personal token
sitting in the public tree*, protected only by a gitignore glob with two negations. After this
phase the rule has no exceptions: if a path does not start with `private/`, what you write
there is published.

Verified removable: `search_jobs.resolve_profile()` already returns an absolute path first and
documents the no-symlink case.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phases 0 and 3 merged.

## Definition of done

- [ ] `git ls-files | grep -i <each personal token>` returns nothing
- [ ] `_overlay_links()` reduced to hook installation only; the matching `.gitignore` rules removed
- [ ] The runtime lists 12 skills (10 public + 2 private) from `.claude/skills` and `.cursor/skills`
- [ ] A fresh public clone with no overlay still runs job-search on the tracked example profile
- [ ] Gate command clean
