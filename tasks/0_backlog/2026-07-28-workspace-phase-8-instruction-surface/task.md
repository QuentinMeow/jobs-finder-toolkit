# Workspace phase 8 — rewrite the instruction surface and reshape examples/

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Bring AGENTS.md, the skills, the handbook, and the public example dataset in line with
the new layout.

## Context

Detail in [the execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) under "Phase 8".

**Rewritten 2026-08-02: the tree this section described no longer exists.** It said
`examples/` *gets* reshaped and named its two violations — `examples/data/` as a generic
bucket and `examples/templates/` colliding with the root `templates/` — plus an executed
`examples/data` pin in `ci.yml`. **All three are gone.** The reshape landed on 2026-08-02
(`261b4f0` "Mirror the private tree's shape in the public examples/ dataset", `8c8112a`
"Rename the example fixture store examples/data to examples/store"):

```
$ ls examples/
applications  fixtures  market  me  screenshots  store

$ grep -n examples .github/workflows/ci.yml
229:            examples/applications/6_drafted/example-corp-senior-software-engineer/
252:        run: python automation/store/validate_store.py examples/store --check-fixture-size
```

Neither `examples/data/` nor `examples/templates/` exists, and the `ci.yml` pin names
`examples/store`. The 2026-08-06 person-first follow-up has now closed D7. What remains
is ratification of the built calls and the inherited accessor item.

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

**The hard blocker named below is gone, but the headroom it was about has mostly been spent
again.** `skills/company-research/SKILL.md` is not the 595 lines the text below claims: the
slimming task merged (PR #108, in `tasks/4_done/2026-07-28-slim-company-research-skill`) and
took it to **469 of 600**, 131 of headroom. The company-research correctness stack then added
99 lines back, and it now stands at **568 of 600 — 32 lines left** (re-measured 2026-07-31 at
the head of that stack). `instruction_budget.py --strict` still exits 0, and now prints the
file as `NEAR` with the remaining count, so whoever edits it next meets the number in the gate
output rather than discovering it at the cliff. **Treat the next substantive company-research
edit as a consolidation pass, not an addition.** `AGENTS.md` is at 318 of 500, not 307 — the
substance holds, the number does not.

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

### Status — the reshape landed 2026-08-02; what is left is ratification plus two items

**Scoped, then built.** The phase was re-measured in full on 2026-07-31: the per-skill
instruction sweep is zero work in both columns (above), the `examples/` target shape was
mapped file by file against the private tree, and every literal that had to move with it was
counted — **85 references in 42 files** naming `examples/{data,templates,profile,applications}`
outside the record trees, including `ci.yml`'s executed `examples/data` pin. That count is a
**dated measurement of work now done**, not a to-do: `261b4f0` and `8c8112a` moved the tree and
its references together, and the `ci.yml` pin now reads `examples/store`.

**Landed in that stack (no path moves, so no owner call was needed):** the four factually wrong
instructions this phase was also chartered to fix are corrected — search-profile locations in
`ask-me-anything` and `job-search`, and where company behavioural answers belong in
`behavioral-interview-prep`. That is the phase's PR 1.

**Correction, 2026-08-06: the person-first refactor builds the former D7 gap at its new
destination.** `companies_root()` now resolves to `examples/me/interviews/companies/`, backed
by one fictional company-prep fixture; the identity fixture is separately filed at
`examples/market/company-index.yaml`. The same refactor moves the fictional application and
career sources below `examples/me/`. Ratification remains open in the linked queue item.

**Was: "deliberately NOT done — the `examples/` reshape itself."** ~~Every remaining piece
renames, deletes or invents a **published** path in a public repo, or changes what a generator
writes into the owner's private tree.~~ **Superseded 2026-08-02.** The pre-registered fallback
in that item fired: the owner said "continue the work of the folder refactor", which the item's
own **Default path** had already defined to mean *build each call to its recommendation*. D1,
D2, D3 and D6 were built and are now **ratify-or-revert**, each as its own revertible commit
range. ~~**D7 was NOT built** — `examples/companies/` still does not exist.~~ That was
true on 2026-08-02; the correction above records the new person-first destination built on
2026-08-06. D5 shipped separately in `ac34371`.

The calls are still filed as one item —
[`message-queue/needs-human/decisions/examples-reshape-seven-calls.md`](../../../message-queue/needs-human/decisions/examples-reshape-seven-calls.md)
— with options, a recommendation and a default for each; no `Your answer:` line has been
filled. **This task stays in `0_backlog/` because ratification and the accessor assertion
remain open — not because the reshape is undone.** Its default path is now "the recommendations
stand as built; nothing further moves without an answer."

One correction to the plan worth carrying forward: it proposed an `examples/skills/skill-notes/`
counterpart and then argued against it, correctly. That directory would re-create the
`examples/templates/`-vs-`templates/` collision this phase exists to close, so the smoke
assertion carves `skill_references_dir()` out instead (decision D4 in the item above).

## Definition of done

- [ ] `AGENTS.md` describes the private tree and routes into it
- [ ] All 11 public `SKILL.md` files and 7 handbook docs updated
- [x] `examples/` mirrors the private tree; `data/` and `templates/` violations fixed;
      `ci.yml`'s `examples/data` pin updated in the same PR — **done 2026-08-02**
      (`261b4f0`, `8c8112a`; the later person-first move nests applications below `me/`; `ls examples/` → `fixtures market me screenshots
      store`, `ci.yml:252` → `validate_store.py examples/store`). Ratification of the calls
      it was built on is open; see the item above
- [ ] **Inherited 2026-07-31** from
      [the config-defaults task](../../4_done/2026-07-30-config-defaults-still-name-the-pre-phase-5-layout/verification.md),
      **re-measured 2026-08-02 against the reshaped tree.** The reshape closed half of it and
      not the other half. Resolving `config.*()` with `JOBHUNT_CONFIG=config.example.yaml`
      (`overlay_root()` → `examples/`):

      **Resolve now:** `profile_md_path` → `examples/me/career/profile.example.md`,
      `baseline_path` → `examples/me/career/resume/baseline.example.yaml`, `reference_docx_path` →
      `examples/me/career/resume/reference.example.docx`, `company_levels_path` →
      `examples/market/logs/company-levels.example.yaml`, `calendar_path` →
      `examples/me/interviews/calendar.md`, `candidate_dir` → `examples/market/logs`,
      plus `applications_root`, `discoveries_dir`, `overlay_root`, and `companies_root` →
      `examples/me/interviews/companies`.

      **Still resolve to nothing:** `blacklist_path` → `examples/market/blacklist.yaml`; `story_bank_path` →
      `examples/me/interviews/story-bank`; `search_profiles_dir` →
      `examples/market/searches`; `tailoring_card_path` →
      `examples/market/logs/tailoring-card.md`; `skill_references_dir(<skill>)` →
      `examples/skills/skill-notes/<skill>` (**carved out on purpose — D4**); and the three
      append-only logs `applications_log_path`, `applications_jsonl_path`,
      `company_search_log_path`, which are created on first write and are arguably not
      defects. `data_root()` returns `None` — `config.example.yaml` sets no store root.

      The smoke assertion that every `config.*()` path exists under the example config is
      still unwritten, and it must carve out `skill_references_dir` (D4) and decide whether
      the three logs count. That is the honest remainder of this bullet
- [ ] ADRs recorded for the layout and any remaining reversals
- [ ] Per-skill canaries pass and are recorded for the 9 skills that have a set; a one-line
      rationale recorded for `gardener` and `search-recall-audit`
- [ ] `instruction_budget.py --strict` clean
- [ ] Review-ledger rows for every commit; branch ends with a ledger-only commit
- [ ] Gate command + export dry-run clean
