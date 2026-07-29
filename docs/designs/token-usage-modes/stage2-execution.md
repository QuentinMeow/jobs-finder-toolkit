# Stage 2 execution plan — instruction tiering (approved 2026-07-20)

**Status:** completed. This is the historical Stage-2 plan; it followed the Stage-1 measured result
(`evals/results/stage1-benchmark-20260720.md`: ~502k vs 437k baseline, +15%)
and the maintainer's review/go-ahead. Boot tax (~35–40% per agent) is the
measured binding constraint; this stage attacks it, plus the two defects the
Stage-1 row exposed: an unpinned benchmark scenario and the non-binding
card-first instruction (0 uptake in 4+ applicable runs).

## Targets (measured, current main)

| File | Now | Target | Mechanism |
|---|---:|---:|---|
| `AGENTS.md` | 500/500 lines, ~10.3k tok | core ≤ ~150 lines (~3k tok) | core/annex split; annex read on demand |
| resume-writer `SKILL.md` | 599/600 lines, ~9.4k tok | ~350 lines (~5.5k tok) | quickstart-first; detail → `reference.md` (unbudgeted, on-demand) |
| job-search `SKILL.md` | 459 lines, ~7.3k tok | ~280 lines (~4.5k tok) | same |
| candidate context per drafting agent | profile+baseline+story bank ~50 KB | card (8 KB) + baseline; full docs only on listed triggers | make card-first **binding** in the quickstart |

Projected effect on the pinned benchmark scenario: **−25% vs the pinned-scenario
reference row** (search + 2 drafts). Per the execution-plan gate rule, a result
≥ ~25 percentage points off this projection pauses Stage 3 and forces analysis.

## Why a reference row first

The 437k baseline and the +15% Stage-1 row ran materially different scopes
(profile count, verification depth, research per letter). Before any Stage-2
change merges, the scenario is pinned in `benchmark-scenario.md` (same
directory) and re-run once against main @ `627a393` from a worktree at that
SHA. All future rows compare against that reference, like-for-like.

## Work items

1. **Pin the benchmark scenario** — `benchmark-scenario.md`: fixed query and
   widening policy, one profile, two drafts by fixed selection rule, fixed
   verification depth and research caps, fixed deliverables, measurement
   protocol (per-subagent usage totals; append rows to the README table).
2. **Reference benchmark** — pinned scenario on main @ `627a393`.
3. **resume-writer tiering** — quickstart-first SKILL.md (~350 lines):
   routine path (card-first → tailor → render ≤2 cycles → check.py → Step 7)
   up top; moved detail lands in `reference.md` with explicit "read when X"
   triggers. Card-first becomes a MUST with listed exceptions (missing card,
   staleness warning from gardener, JD outside card coverage). Token-saving
   defaults live in the quickstart text — no config schema change in Stage 2.
4. **job-search tiering** — quickstart-first SKILL.md (~280 lines): snapshot
   cache + `--refilter` + compact stdout + `fetch_jd.py` + `handoff.py` as
   the default path; diagnostics and rare flows move to `reference.md`.
5. **AGENTS.md core/annex split** — core keeps boot-critical invariants
   (safety rules, repo map, common commands, boot sequence); the rest moves
   to `handbook/README.md` with pointers. **Merge is held** until the
   concurrent worker's in-flight AGENTS.md additions land (see coordination),
   then their additions are ported into the new structure. Budget ratchet on
   the core follows once stable.
6. **Integration + combined gate** — merge in order 3 → 4 → 5; re-run
   `instruction_budget.py --strict` after each merge (composition broke the
   budget twice in Stage 1); full combined canary gate (all 11) on the final
   integrated head; leak guard exit 0; every merge commit verified as an
   ancestor of main.
7. **Post-Stage-2 benchmark** — pinned scenario on the integrated head;
   append the row; gate decision for Stage 3.

## Gates (unchanged from Stage 1, plus composition rules)

- Any `SKILL.md`/`LESSONS.md`/`reference.md` edit: that skill's full canary
  set green on the branch head, judged per `evals/rubrics/judging.md`,
  recorded in `evals/results/`. Combined instruction states re-gated.
- Runners for canaries and benchmarks stay on the **pinned mid-tier model**
  recorded in prior results files — the eval protocol is model-pinned, and
  changing runner tier would invalidate comparison with every prior gate.
  Implementation and verification of code/doc changes use a high-capability
  tier; the orchestrator judges rubrics and never delegates verdicts.
- Eval-run hygiene (learned Stage 1): pin `JOBHUNT_CONFIG` to the worktree's
  `config.example.yaml`; runners read worktree files directly (never a skill
  loader that may serve a stale copy); `evals/` is out of bounds for subject
  agents; produce-artifact canaries run against fixtures with the
  to-be-produced artifacts absent (issue #16 workaround).

## Coordination with concurrent work

A concurrent worker holds uncommitted edits in the public tree (new
`outlook-email-assistant` skill; additive AGENTS.md/config/requirements/hook
changes). Rules for this stage:

- Never touch, stage, or revert their files; Stage-2 work happens in
  worktrees on branches off `627a393`.
- Their AGENTS.md delta is additive (8 lines, 5 sites) but fills the budget
  to exactly 500/500 — the core/annex split is also the fix for that
  pressure. The split PR merges only after their edit is committed, and
  ports their additions into core (the draft-only email invariant, skill
  table row, boot-read line) and annex (command example) as appropriate.
- Before every merge to main: re-check their tree/PR state; on textual
  conflict, resolve by porting their content, then re-run budgets + the
  affected canary sets on the combined state.
- Commits from the primary tree stay path-scoped with hooks bypassed and the
  equivalent checks run manually (their uncommitted hook edit must not run).
