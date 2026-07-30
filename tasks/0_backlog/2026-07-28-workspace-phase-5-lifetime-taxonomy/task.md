# Workspace phase 5 — reorganise private/ by lifetime

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Give the private overlay its me/ · companies/ · applications/ split so durable
knowledge outlives any application.

## Context

Target tree in [the design](../../../docs/designs/workspace-restructure/README.md); the full move table is in
[the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) under "Phase 5".
805 tracked private files move; `applications/<status>/<slug>/` keeps its path.

**Start by asking "is this a config edit?"** Phase 0 added eleven config accessors, eight of
which read a `paths.*` key. Most rows in the move table are now a `config.yaml` edit and nothing
more: profile, baseline, reference DOCX, company-levels, `calendar.md`, discoveries, blacklist,
story bank, search profiles, per-skill private references, the company research tree, and the
`data/` → `store/` store root all have a key.

**Four code changes this phase cannot avoid:**

1. **The tailoring card and the two skip-logs must stop sharing one parent.**
   `tailoring_card_path()`, `applications_log_path()` and `company_search_log_path()` are
   hard-derived as `candidate_dir() / <FILENAME>` with no `paths.*` key of their own
   (`automation/shared/config.py:444-456`). This phase sends the card to `me/` and the logs to
   `market/logs/` — one `candidate_dir` cannot express that. Give each its own key, then
   re-vendor: every `config.py` change is a 5-file change plus `sync_vendored.py --check`.
2. **`search_jobs.profile_dir()`** (`skills/job-search/scripts/search_jobs.py:158-181`) still
   returns its first candidate when no probe holds a log. Phase 0 taught it
   `config.candidate_dir()`, but it still hunts for a *directory containing a log file*, and
   after this move no probe contains one — both the already-considered and recently-searched
   skips would switch off in silence. Point it at `config.applications_log_path()` /
   `config.company_search_log_path()` directly.
3. **The story bank has a display key as well as a location.**
   `skills/resume-writer/scripts/build_tailoring_card.py:78` and
   `automation/gardener/card_staleness.py:41` both carry
   `STORY_BANK_REL = "interviews/behavioral/story-bank"` — the literal a card's header records
   beside the directory's sha256. The location already comes from `config.story_bank_path()`, so
   the hash will be right; change one display key and not the other and every card reads
   permanently stale. Change both in one commit, or neither.
4. **`history/` leaving the tracked tree re-points the reconciler.** The `handover-present`
   check keys on `history/conversations` and `CHECK_ROOTS` maps it there
   (`automation/reconcile/reconcile.py:281`); the maintainer `pre-commit` runs
   `--require-roots`, so moving it without both edits fails every later commit.

Also new structure, not just a move: `market/scans/` needs an `archive/` tier that
`paths.discoveries_dir` does not cover, and per-company behavioral answers become build outputs
at `companies/<key>/derived/behavioral.md`, which
`skills/behavioral-interview-prep/scripts/answer_bank.py` must learn to emit. (The plan used to
warn that `test_answer_sources.py` hardcodes `parents[5]` — that file no longer exists; the
suite is `skills/behavioral-interview-prep/scripts/tests/test_answer_bank.py` and its only depth
constant is move-invariant.)

**Hazards, re-measured 2026-07-29:**
- Renaming `data/` → `store/` without simultaneously rewriting all **9** ignore patterns in
  `private/.gitignore` un-ignores **83,491 files / 450 MB**, 37,614 of them under `data/email/`.
  Same commit, mechanical sed, verified with `git -C private check-ignore`.
- `company-levels.yaml` uses 27 YAML anchors and **cannot** be sharded per company.

**The leak guard needs no edit for this phase.** `check_public._DENY_TREES` already denies
`store/`, `me/`, `companies/` and `market/` at the public root, and
`test_deny_trees_are_append_only` keeps them there. The `.gitignore` coupling test reads the
**public** repo's `.gitignore`; the nine store patterns live in `private/.gitignore` and are out
of its reach. It only bites if this phase also adds a root-anchored `/x/` rule to the public
`.gitignore` — which it should not need to, since `private/` is ignored wholesale.

**Roughly four dozen of the 535 `interviews/` files are judgment calls, not mechanical moves.**
Route each through the owner; do not guess. An interview-running firm is a company, not a vendor
— there is no `vendors/` root. (That count was estimated when the plan was written and has not
been re-derived; recount before promising a date.)

**244 relative links inside `interviews/` are covered by no checker**; fix them here and drop
the `interviews/` and `private/interviews/` entries from `verify_links.py`'s `SKIP_PREFIXES`.
Note what that exposes: the new roots `me/`, `companies/`, `market/`, `store/` are not skipped,
so once they exist every doc naming `private/me/…` **is** verified whenever the overlay is
mounted.

**Never name a real company, employer or application in a public file.** This phase's subject
matter is the owner's application tree; the review gate caught exactly this leak once already
(commit `ef2d0a3`). Describe shapes — `<Name>` / `<Name> Ltd.` — never instances. Rule 4 of the
execution plan applies per commit: a review-ledger row each, plus a closing ledger-only commit.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

None outstanding — phases 0 and 4 both merged 2026-07-29 (PRs #81–#84 and #86), and Q5/Q6 were
answered 2026-07-28 (rendered artifacts stay in the application folder and only the USER deletes
one; handovers are local-only). This phase is ready to start.

## Definition of done

- [ ] `private/{me,companies,applications,market,store,skills,memory,message-queue,tasks,evals,docs,local}/`
- [ ] `git -C private check-ignore` returns IGNORED for a canary list covering all 9 store patterns
- [ ] `config.yaml` `paths.*` re-pointed; the three keyless accessors given their own keys and
      re-vendored (`sync_vendored.py --check` clean); every gardener routine runs
- [ ] `search_jobs.profile_dir()` reads the log accessors directly; both skips proven still live
- [ ] `status.py` reports the same pipeline as before the move
- [ ] The tailoring card rebuilds **with its stories**; level enrichment exercised
- [ ] `verify_links.py` `SKIP_PREFIXES` no longer skips `interviews/`, and the 244 relative links resolve
- [ ] The judgment-call files placed with recorded owner answers
- [ ] Review-ledger rows for every commit; no company name in any public file
- [ ] Gate command clean
