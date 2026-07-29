# Workspace phase 2 — split the generic bucket, consolidate docs and evals

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Merge the public tree's duplicate concepts and split its one generic bucket, updating
every path literal in the same PR.

## Context

Detail in [the execution plan](../../../design/workspace-restructure/execution-plan.md) under "Phase 2". `automation/maintenance/` splits
three ways, `docs/` absorbs `handbook`+`design`+`roadmap`, `evals/` absorbs the measurement
protocols and flattens the per-skill canary folders, `tmp/` becomes `local/`.

`automation/` holds exactly ten entries today (`bootstrap_overlay.py`, `hooks/`, `maintenance/`,
`metrics/`, `publish/`, `reconcile/`, `shared/`, `store/`, `vendoring/`, plus an untracked
`__pycache__/`) — `maintenance/` is the only generic bucket, and it holds three things.

**The depth trap, re-measured 2026-07-29:** there are **9** `parents[N]` constants under
`automation/maintenance/`, of which **5 break** on the move — `gardener/_common.py:24`,
`gardener/tests/test_store_report.py:29`, and all three under `search_recall_audit/`
(`audit.py:43`, `field_fidelity.py:45`, `store_refilter.py:14`). The three `parents[1]`
constants in the gardener tests are relative to their own directory and survive;
`import_company_levels.py:34` survives only because `automation/company-levels/` sits at the
same depth as `automation/maintenance/`. Convert all of them to the upward `.git` walk that
`automation/shared/config.py` adopted in commit `5156598` (`_git_boundary()` / `_repo_root()`)
rather than re-counting.

**`design/workspace-restructure/` moves too**, and 23 tracked files name that path — including
`automation/publish/review_gate.py`'s docstring, the header comment in
`automation/publish/review_ledger.yaml`, `automation/publish/tests/test_review_gate.py`,
`check_public.py`'s `_DENY_TREES` comment, the ADR, `roadmap/current-state.md`, and 13 task
files across `tasks/0_backlog/` and `tasks/3_in-review/` (this one included).

**Every constant that moves with `handbook/`+`design/`+`roadmap/`+`tmp/`:**
`STRICT_ROOT_PREFIXES` (`verify_links.py:54`), `PLAN_OR_RECORD_SOURCES` (`:87`),
`SKIP_PREFIXES` (`:66`, names `tmp/` and `private/tmp/`), `_FALLBACK_SKIP_DIRS` (`:137`, names
`tmp`), `ALLOWLIST_DIRS` (`export_public.py:76`), and both `check_roadmap_fresh()` and
`CHECK_ROOTS` in `automation/reconcile/reconcile.py:253,281`.

**The failure mode is a silent disarm, not a red build.** `verify_links.py`'s
`_present_strict_prefixes()` makes a prefix strict only in a tree that has that root, and the
reconciler's `CHECK_ROOTS` no-ops on a missing root by design. Rename a root without renaming
its constant and everything stays green while the check stops checking. Prove each moved check
still fails on a deliberately planted defect.

`.github/workflows/ci.yml` carries **16** executed path pins, of which exactly one moves here
(`automation/maintenance/gardener/tests`) — verify the other 15 rather than assuming.
`.github/pull_request_template.md:12` pins `automation/maintenance/gardener/gardener.py`. Same PR.

The `docs/designs/CLAUDE.md → AGENTS.md` shim is a **tracked symlink** (git mode `120000`), and
`export_public.py:238-241` deliberately *follows* it so the export ships real content. `git mv`
the link rather than deleting and re-authoring it — the exported tree looks identical either
way, which is why getting it wrong stays invisible until Claude Code stops loading the folder's
contract.

`evals/` holds nine tracked per-skill folders today, one `canaries.yaml` each
(application-tracker, ask-me-anything, behavioral-interview-prep, company-research,
email-assistant, github-workflow, interview-calendar, job-search, resume-writer), plus
`rubrics/` and `results/`. An empty untracked `evals/coding-interview-cleanup/` sits on disk;
git carries no empty directories, so it is local residue.

Consolidating `docs/` reverses a decision recorded in `handbook/file-organization.md`; write
the superseding ADR into `memory/decisions/` as part of this task.

**The review gate applies to every commit here** (execution plan, rule 4). This phase is almost
all `git mv`, so the diffs are large: one row in `automation/publish/review_ledger.yaml` per
commit, a closing ledger-only commit to land the branch green, and read the diff before pasting
the row the gate prints.

### Blocking preconditions

**STOP if any is unmet.** Do not proceed on a default or a guess: move this task to
`tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
`templates/queue/decision.md` with options and a recommendation, and end the session. Several
gates in this repo fail *open*, so a half-done phase is indistinguishable from a done one.

None outstanding — phase 0 merged 2026-07-29 (PRs #81–#84), and Q4 was answered 2026-07-28
(docs consolidation confirmed). This phase is ready to start.

## Definition of done

- [ ] `automation/{gardener,search-recall-audit,company-levels}/` exist; all 9 `parents[N]`
      constants converted to a `.git` upward walk; every gardener routine and the recall audit run
- [ ] `docs/{handbook,designs,roadmap}/` with the `CLAUDE.md → AGENTS.md` shim re-created **as a
      tracked symlink**; all 23 files naming `design/workspace-restructure/` updated
- [ ] `evals/{protocols,canaries,rubrics,results}/`; `evals/canaries/<skill>.yaml`
- [ ] `tmp/` → `local/`, root `.gitignore`, `handbook/file-organization.md`'s scratch rule and
      `AGENTS.md`'s "Scratch & Temporary Files" bullet updated
- [ ] `ci.yml`, `pull_request_template.md`, `ALLOWLIST_DIRS`, `marketplace.json`,
      `verify_links.py`'s four constants and `reconcile.py`'s two updated
- [ ] **Each moved check proven to still fail on a planted defect** — a green run is not evidence
- [ ] Superseding ADR recorded
- [ ] Review-ledger rows for every commit; branch ends with a ledger-only commit
- [ ] Gate command + export dry-run + `instruction_budget.py --strict` clean
