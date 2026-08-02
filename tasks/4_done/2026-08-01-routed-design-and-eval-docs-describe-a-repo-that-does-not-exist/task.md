# The design and eval-protocol docs the contract routes to describe a repo that does not exist

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**: agent, session 2026-08-02 (branch `docs/26-contract-and-record-corrections`)

## Goal

The design docs `AGENTS.md` names as authoritative, and the eval protocols `evals/README.md` pins,
describe the repo as it is — so an agent routed to them does not stall on a missing script, trust a
"not implemented" line about shipped code, or size a decision off a two-year-stale table.

## Context

Two clusters. None is a proposal-vs-reality gap (those are fine); each is a doc that a contract or
`README` names as the live authority.

### A. Design docs cited as authorities

1. **`docs/designs/workspace-restructure/README.md:3`** — "**Status:** design, owner-approved
   topology (2026-07-28). Not implemented." Its own execution plan
   (`execution-plan.md:6-8`) says "phases 0-6 are merged into `main`. Phase 7's index and public
   contract are implemented and in review", `docs/roadmap/current-state.md:114` says phase 7 is
   done, and `automation/publish/review_gate.py` — the design's Layer 2 — runs in pre-commit and CI
   today. Every phase task links this README as `[design]`, and its sibling `review-gate.md:193`
   already says "Implemented in `automation/publish/review_gate.py`". Same file, `:81`, still says
   "`skills/` # 10 public skills"; there are eleven.

2. **`docs/designs/tree-instructions/README.md:158-159`** — "The corrected validator spec lives in
   `tasks/0_backlog/2026-07-21-tree-instructions-validator/task.md`". That folder does not exist in
   any status directory, and `docs/roadmap/desired-state.md:36` says "**The tree-instructions
   validator is dropped**". `AGENTS.md:189` routes agents to this README as *the* design for leaf
   policy, so §5 points at a dead file and describes dropped work as queued. (`:3` also still says
   "validator/exporter hardening remains queued".)

3. **`docs/designs/workspace-restructure/review-gate.md:65`** — the hard "ledger is out of sync"
   error "now fires only when **no row at all** is an ancestor — the genuine 'this ledger describes
   another repository' case". `review_gate.py` splits that into four outcomes, two of which exit 0
   (`review_gate.py:174` `NotApplicable`; `:839` the published-export shape), so the case the spec
   calls the hard error is precisely one that now passes. The spec also documents only the bare
   invocation while CI depends on `--verify-all` and `--head`. `review_gate.py:5` cites this file as
   its spec and `tests/test_review_gate.py:10` says the scenarios mirror it, so it is the named
   authority, not a record.

### B. Eval protocols

4. **A required script that was never built.** `evals/protocols/stage-benchmarks.md:92-93` — "Every
   stage row and every future full row runs the transcript miner over its own session transcript and
   records: tool-call count, failure count by tool, …" (also `:66-67`). There is no transcript miner
   in `automation/`. The nearest thing, `automation/metrics/hook_collect.py:112`
   `_summarize_transcript`, totals tokens/time/tool-calls inside the Stop hook and produces none of
   the three fields the protocol and `evals/results/TEMPLATE.md:79` demand.

5. **Every recording path assumes an opt-in collector nobody wired.** `evals/README.md:108` —
   "Record efficiency from the metrics log (Phase 3 hooks write `logs/metrics.jsonl`, keyed by git
   SHA)" — echoed by `evals/protocols/ab-protocol.md:44` and `evals/rubrics/judging.md:71`. But
   `automation/metrics/hook_collect.py:5` says "Metrics are OPT-IN: wire these hooks (SessionStart,
   PostToolUse, Stop)", `.claude/` holds only `skills/`, and `logs/` is gitignored and absent — so
   `report.py --by-sha` prints nothing and step 5 leaves the agent with a number to invent.
   `docs/handbook/metrics.md` documents the wiring; nothing under `evals/` mentions that it is
   needed.

6. **Two homes for stage artifacts.** `evals/protocols/stage-benchmarks.md:69` says
   `private/evals/runs/artifacts/<row-id>/`; `evals/results/TEMPLATE.md:84` says
   `private/evals/artifacts/<row-id>/`. The overlay layout fixed by
   `docs/designs/workspace-restructure/README.md:170` is `evals/{canaries,fixtures,runs}/`, so the
   template — the file an agent copies — is the stale one and writes outside the sanctioned tree.
   `TEMPLATE.md:88` also cites a `protocol.md` that exists nowhere; the confirmation row it means is
   `docs/designs/token-usage-modes/benchmark-scenario.md`.

7. **`evals/protocols/stage-map.md:20-27`'s table is labelled "Live … file sizes" and is stale in
   every checkable row**: `AGENTS.md` 14,282 → 26,850 B; `docs/handbook/README.md` 37,645 → 1,971 B;
   job-search `SKILL.md` 18,689 → 27,395; job-search `reference.md` 25,219 → 43,509; resume-writer
   `SKILL.md` 26,950 → 32,317; `check.py` 36,824 → 46,754. `evals/README.md:138` pins this doc as
   the stage decomposition, so an agent sizing a boot-tax lever off it is out by ~2x, and by 19x on
   the handbook index.

Filed as one task because the fix in every case is the same shape — say what is true, or say the
doc is a record — and because splitting seven one-line corrections into seven backlog items is worse
for the reader than one. Item 4 may end in "delete the requirement" rather than "build the miner";
that is a legitimate outcome and should be recorded either way.

## Definition of done

- [ ] No design doc that `AGENTS.md` or a live task links as `[design]` carries a status line its
      own siblings and the code contradict.
- [ ] `docs/designs/tree-instructions/README.md` §5 no longer points at a task that does not exist.
- [ ] `review-gate.md` describes the four real outcomes and names `--verify-all`/`--head`.
- [ ] The transcript-miner requirement is either implemented or struck from
      `stage-benchmarks.md` and `evals/results/TEMPLATE.md`.
- [ ] `evals/README.md` step 5 says the metrics hooks are opt-in and links
      `docs/handbook/metrics.md`.
- [ ] One artifact path, spelled the same in the protocol and the template; `protocol.md` replaced
      with the file that exists.
- [ ] `stage-map.md`'s size table is either re-measured or relabelled as a measurement at a named SHA.
- [ ] `.venv/bin/python automation/gardener/verify_links.py --require-roots --no-overlay` clean.
