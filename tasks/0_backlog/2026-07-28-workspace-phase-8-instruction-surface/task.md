# Workspace phase 8 — rewrite the instruction surface and reshape examples/

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Bring AGENTS.md, the skills, the handbook, and the public example dataset in line with
the new layout.

## Context

Detail in [the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) under "Phase 8". `examples/` gets reshaped to mirror
the private tree and to fix its own two violations (`examples/data/` is a generic bucket,
`examples/templates/` collides with the root `templates/`). `examples/data` is an executed path
pin in `ci.yml` (`automation/store/validate_store.py examples/data --check-fixture-size`) —
same PR.

### Scope, re-measured 2026-07-31 — the per-skill table is dead in both columns

The table that used to sit here counted, per public `SKILL.md`, how many paths phase 2 moves and
how many phase 5 moves. **It has been re-measured and both columns are now zero.** That is the
whole of what
`2026-07-29-refresh-phase-8-instruction-surface-counts` asked for; the task has been deleted and
its measurement folded in here and in the execution plan in the same commit, as its own definition
of done required.

**Verify-with** (record the command, not the coordinates — line numbers rot, this does not):

```bash
# phase-2 tokens: automation/maintenance/, and bare handbook/ design/ roadmap/ tmp/
grep -cE 'automation/maintenance/|(^|[^s/])handbook/|(^|[^s/])design/|(^|[^s/])roadmap/|(^|[^/[:alnum:]])tmp/' skills/*/SKILL.md
# phase-5 tokens
grep -nE '0_profile|interviews/|job-search-profiles/' skills/*/SKILL.md
```

- **Phase-2 column: 0 across all 11 public skills.** Phase 2 retired `automation/maintenance/` and
  re-spelled `handbook|design|roadmap|tmp`; not one token survives in any `SKILL.md`. (The only
  raw `tmp/` matches anywhere are five `/tmp/*.json` examples in `skills/job-search/SKILL.md` —
  the OS temp dir, not this repo's scratch root. They are a separate, real finding against
  `AGENTS.md`'s `local/` rule, filed as its own task, and they are **not** phase-8 work.)
- **Phase-5 column: 0 stale references.** 14 raw token hits remain across four skills
  (behavioral-interview-prep 9, ask-me-anything 3, application-tracker 1, resume-writer 1), plus
  three prose false positives in company-research where "interviews/" is English
  ("founder interviews/podcasts"). **Every one of the 14 already names the post-phase-5 path**:
  `private/me/interviews/{story-bank,question-bank}` and `<applications_root>/0_profile/` all
  exist on disk today, and `verify_links` reports every reference resolving.

So the instruction-surface half of this phase is smaller than the table implied — it is
`AGENTS.md`'s private-tree map and whatever the `examples/` reshape drags with it, not a sweep of
eleven skills.

**Correction: there are THREE overlay-only skills, not two.** `private/skills/` holds three
`SKILL.md` files today. Their names are deliberately absent from the public tree.

**8 handbook docs name `private/`, not 7 and not 5**, re-measured 2026-07-31:
`private-overlay.md` (58), `public-private-split.md` (10), `repo-map.md` (6), `architecture.md`
(4), `command-cookbook.md` (4), `memory-map.md` (2), `configuration.md` (1),
`application-folders.md` (1).

**The hard blocker named below is gone.** `skills/company-research/SKILL.md` is **469 lines
against the 600-line budget**, not 595 — the slimming task merged (PR #108) and is in
`tasks/4_done/2026-07-28-slim-company-research-skill`. `instruction_budget.py --strict` reports
`OK: all instruction files within budget`, with **131 lines of headroom** where the text below
claims five. `AGENTS.md` is at 318 of 500, not 307 — the substance holds, the number does not.

> Original text, kept as the dated record of what was believed on 2026-07-29 and superseded by the
> measurement above: *"Hard blocker, re-measured 2026-07-29 and unchanged: `skills/company-research/SKILL.md`
> is at 595 lines against the hard 600-line budget ... Five lines of headroom ... The slimming task
> must land first or this phase cannot commit."*

This is a "large" edit under the risk-based eval gate — canaries run for **every touched
skill**, recorded in `evals/results/`. Nine of the 11 public skills have a canary set;
`gardener` and `search-recall-audit` have none, so edits to those two are covered by
[`evals/README.md`](../../../evals/README.md)'s recorded-rationale rule, not by a run.

Rule 4 of the execution plan applies: a review-ledger row per commit, plus a closing ledger-only
commit.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

Phases 2, 4 and 5 merged, and `2026-07-28-slim-company-research-skill` merged. **All four met
as of 2026-07-30, pending merge**: phase 4 is merged (PR #86); phases 2 and 5 are done and in
review; and the slimming landed — `skills/company-research/SKILL.md` is **469 lines against the
600 budget**, 131 of headroom where it had five.

**Re-confirmed 2026-07-31: all four preconditions are met outright, none "pending".** Phase 2's
task is now in `tasks/4_done/` (#99–#103, #105 all merged), phase 4 in `4_done` (#86), phase 5's
public side merged (#111) though its folder is held in review for missing evidence, and the
slimming is in `4_done` (#108). **Nothing blocks this phase.**

**Phase 5 already absorbed most of the phase-5 column below.** Its rule 2 (the PR that moves a
path updates every literal naming it) meant the migration had to repair every reference the
link checker could see — 126 of them, across `AGENTS.md`, seven handbook docs, five skills, the
eval protocols and both trees' notes — plus the prose and canary YAML the checker cannot see.
**Re-measure before scoping this phase**: what remains is `examples/` and whatever the sweep
missed, not the table's original estimate. The link checker is now the instrument for the part
it can see, and it reports `references: all resolve` today.

## Definition of done

- [ ] `AGENTS.md` describes the private tree and routes into it
- [ ] All 11 public `SKILL.md` files and 7 handbook docs updated
- [ ] `examples/` mirrors the private tree; `data/` and `templates/` violations fixed;
      `ci.yml`'s `examples/data` pin updated in the same PR
- [ ] **Inherited 2026-07-31** from
      [the config-defaults task](../../3_in-review/2026-07-30-config-defaults-still-name-the-pre-phase-5-layout/verification.md):
      the four accessor defaults now derive the lifetime layout, but under the example config
      `overlay_root()` is `examples/`, so `blacklist_path()`, `story_bank_path()`,
      `search_profiles_dir()` and `skill_references_dir()` still resolve to directories that do
      not exist there (as they did before). Reshaping `examples/` is what closes it — together
      with the smoke assertion that every `config.*()` path exists **under the example config**,
      which is the check a maintainer-only run cannot make
- [ ] ADRs recorded for the layout and any remaining reversals
- [ ] Per-skill canaries pass and are recorded for the 9 skills that have a set; a one-line
      rationale recorded for `gardener` and `search-recall-audit`
- [ ] `instruction_budget.py --strict` clean
- [ ] Review-ledger rows for every commit; branch ends with a ledger-only commit
- [ ] Gate command + export dry-run clean
