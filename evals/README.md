# Evals — canary regression + matched-pair A/B for the skill harness

Operating manual for the eval scaffolding that keeps this repo's real product — the
`SKILL.md` / `LESSONS.md` corpus — from silently degrading. This is **Phase 2 (Evals)** of
the harness-engineering roadmap; the design and statistics live in the maintainer-only,
overlay-mounted design doc (absent in contributor checkouts)
[`private/docs/05-harness-engineering-methodology.md`](../private/docs/05-harness-engineering-methodology.md)
(§1 skill-creator harness, §2 matched-pair A/B, Phase 2/3 plan, the quality-gates checklist).

## Purpose

Two jobs, one frozen set of prompts:

1. **Regression detection.** Every SKILL/LESSONS edit — and every model upgrade — can quietly
   break a skill's core workflow or drop a hard-won edge case (the ACE "brevity bias" failure).
   A small **canary set** per skill (a test prompt + a plain-language rubric) catches that
   before it ships.
2. **Matched-pair A/B for efficiency.** Token count and wall-clock are near-deterministic per
   fixed task (design doc §2), so a harness edit that cuts tokens/latency shows clearly at
   **n = 5–10 paired runs**. We A/B **efficiency quantitatively, quality only directionally**
   (blind comparator; no significance claims — the ~300-sample quality math is unreachable at
   this repo's volume). See [`protocols/ab-protocol.md`](protocols/ab-protocol.md).

## The eval-gated-merge rule (risk-based)

From the self-evolution quality-control box (repo design README) and design doc §"quality gates"
#5 — **Eval-gated merge:**

> The canaries of an affected skill must PASS before a SKILL/LESSONS edit merges; model-pin the
> eval run.

**Relaxed to risk-based on 2026-07-20 (maintainer decision).** The mandatory per-edit canary run
above proved too time-consuming, so canary runs are now **optional and agent-judged**. For any
edit to `skills/<skill>/{SKILL.md,LESSONS.md,reference.md}`, the editing agent decides
whether to run that skill's canaries by weighing the edit's **intention** (does it change what an
agent *does*?) and **size**. The PASS-before-merge discipline above is unchanged for every edit
that still triggers a run.

**MUST run** the affected skill's canaries when the edit:

- adds, removes, weakens, or reroutes any hard gate, guardrail, or preflight;
- changes step semantics, protocols, verdict definitions, or deliverables;
- restructures or retiers a file (moving content between the SKILL and reference tiers); or
- is large — guideline: more than ~20 changed instruction lines in a skill, or edits touching 3+
  instruction files of one skill.

Also run when merging would create a combined **un-gated state** of multiple behavioral edits (the
individually small pieces add up to a behavioral change at head).

**MAY skip** when the edit is mechanical/small and leaves behavior unchanged:

- typos, formatting, grammar;
- correcting paths, flags, or labels to match code reality;
- clarity rewording with unchanged semantics;
- small additive factual notes (≲20 lines).

**Skills with no canary set skip by definition.** `evals/canaries/` does not cover every public
skill — `gardener` and `search-recall-audit` have no file there today. A behavioral edit to one of
them cannot "pass canaries", so it records the skip with the missing set named as the reason
(`Eval gate: skipped — no canary set for <skill>`). This is the carve-out that `AGENTS.md`'s
"must pass canaries" clause defers to; it is a gap to fill, not a permanent exemption, and writing
the set is the right fix the first time such an edit is substantial.

**Every skip must be recorded** — one line in the PR description (or the commit body for a direct
commit): `Eval gate: skipped — <intention + size rationale>`. A run is recorded as before, in
`evals/results/`. Skips are not permanent exemptions: the **next** behavioral gate run at head
always covers the accumulated state, not just its own triggering diff — so a later gated edit
re-tests everything that skipped ahead of it.

### Stacked PRs: the run happens once, at the tip

An intermediate PR of a stack is a rung, not a shipping state — the branches above it rebase onto
it, and canaries run on that rung measure something that never merges as it stands. So an
intermediate PR may defer its run to the stack tip, with a line that **names that tip**:

```
Eval gate: stack — <why this one is intermediate>; tip: <#PR number or branch name>
```

Worked example, on PR 2 of a four-branch stack:

```
Eval gate: stack — intermediate rung; the job-search canaries run once on the whole stack; tip: #137
```

The tip must be a PR number (`#137`), a pull URL, or a branch name (`feat/04-jd-renderer`), and it
must sit **on the same line** as the verdict. A `stack` line that names nothing is a form every PR
can type, so `check_pr_body.py` rejects it, and rejects a file path (`tip: evals/README.md`) as a
name.

Three things this form does **not** do — which is why it names a target at all:

- **It verifies nothing.** At the intermediate PR's CI time the tip's run does not exist yet, and
  CI never reads another PR's body. The line is a *declaration*; the obligation moves to the tip.
- **The tip is not automatically bound.** A stacked PR's diff is measured against its own base, so
  the tip's `pr-body` job sees only the tip's own commits — it carries the gate only when the tip's
  OWN diff touches a `SKILL.md` / `LESSONS.md` / `reference.md`. When it does not, use the `stack`
  form only alongside a `tasks/0_backlog/` item for the tip run: **one item per stack** (not per
  PR), naming every skill the stack touched.
- **Detection is an audit, not a gate.** A stack whose tip never ran is found by grepping merged PR
  bodies for `Eval gate: stack` and checking each named tip — which is exactly what the name buys.
  No check can do it at merge time.

At the tip, discharge normally: `ran`, with results covering **every skill the stack touched**, not
only the tip's own diff — or `skipped` / `debt` on the usual terms. The tip has nothing above it to
name, so the `stack` form is never its answer.

When a run is required, the mechanics are unchanged. For any PR that edits
`skills/<skill>/{SKILL.md,LESSONS.md,reference.md}`:

1. Identify the affected skill(s) from the diff.
2. Run that skill's canaries (`evals/canaries/<skill>.yaml`) on the branch head.
3. Every canary's `primary_metric` (`rubric_pass`) must pass, and no efficiency metric may blow
   up (a large `total_tokens` / `tool_calls` regression is a fail even if the rubric passes).
4. Record the run in `evals/results/` from the [`results/TEMPLATE.md`](results/TEMPLATE.md).
5. Only then merge. This gate sits **on top of**, never replaces, the other inviolable gates
   (delta edits only; MEMORY→LESSONS→SKILL promotion needs a separate human-reviewed commit;
   consolidation may never delete a domain edge case; everything reverts via small commits).

**This gate is enforced, not advisory.** `AGENTS.md` states it as a hard behavioral invariant, and
`skills/github-workflow/scripts/check_pr_body.py` checks that a PR touching a skill's instruction
files carries one of four things: a canary-run record, the one-line skip rationale, a `stack` line
naming the tip that runs them (above), or tracked debt — an `Eval gate: debt — …` line plus a
`tasks/0_backlog/` item named in the body and added by the same diff. What stays agent-judged is
the *run-or-skip* call above — never whether to record the outcome.

## How to run a canary

A canary is `{id, prompt, setup, expected_behavior (rubric), failure_modes, primary_metric,
efficiency_metrics}`. Two ways to execute it.

### (a) Anthropic's skill-creator harness (preferred — evals + A/B in one)

The skill-creator harness is purpose-built for Claude Code skills (which are literally this
repo's product): evals as **test-prompt + plain-language rubric**, a **benchmark mode** that
tracks eval pass rate + elapsed time + token usage, multi-agent parallel eval in clean contexts,
and **blind comparator agents** for A/B ("two skill versions, or skill vs. no skill — judge
without knowing which is which"). Map each `evals/canaries/<skill>.yaml` entry onto a skill-creator eval:
`prompt` → the test prompt, `expected_behavior` → the rubric, `efficiency_metrics` → benchmark
mode's time/token columns. Run in benchmark mode for pass-rate/time/tokens; use comparator mode
for the directional quality half of an A/B.

- https://claude.com/blog/improving-skill-creator-test-measure-and-refine-agent-skills
- https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md

### (b) Manually in Claude Code (no extra tooling)

1. **Fresh session per canary** — a clean context, so nothing leaks between runs.
2. Apply the canary's `setup` (usually: leave `config.yaml` unset so paths fall back to
   `config.example.yaml` + `examples/**` — the fictional "Jordan Rivers" candidate). Canaries
   marked `requires_overlay: true` need a mounted `private/` overlay; prefer their examples-based
   variant when you have none.
3. **Paste the `prompt` verbatim.** Do not coach the model past what a real user would type.
4. **Judge the transcript against `expected_behavior`** using the shared discipline in
   [`rubrics/judging.md`](rubrics/judging.md): every bullet is a pass/fail check; the canary
   passes only if all checks hold (`rubric_pass`). Watch for the listed `failure_modes`.
5. **Record efficiency** from the metrics log (Phase 3 hooks write `logs/metrics.jsonl`, keyed by
   git SHA):
   ```bash
   .venv/bin/python automation/metrics/report.py --by-sha
   ```
   Read `total_tokens` and `wall_clock_s` for the run's SHA; note `tool_calls`. Copy the
   pass/fail + numbers into a `evals/results/` file from the template.

   **The metrics hooks are OPT-IN and are not wired in a fresh checkout.** `logs/` is
   gitignored and absent until you wire the SessionStart / PostToolUse / Stop hooks from your
   own `.claude/settings.local.json` — see [`../docs/handbook/metrics.md`](../docs/handbook/metrics.md)
   for the wiring and the metric set. Unwired, `report.py --by-sha` prints nothing; that is
   the expected state, not a bug. When it does, **write down where your numbers came from**
   (the harness's own per-session counters are the usual fallback, and several records under
   `evals/results/` do exactly that) or write `not measured` — never a number you inferred.
   Subagent runs are a standing case of this: no per-SHA metric fires for them.

## Matched-pair A/B protocol (summary — full steps in `evals/protocols/ab-protocol.md`)

- **Frozen canary set.** Use the same `evals/canaries/<skill>.yaml` prompts for both variants; never edit a
  canary mid-comparison (job boards drift weekly — freeze the task set).
- **Same prompts, both variants, paired.** Run variant A and variant B on each prompt; analyze
  per-prompt deltas (matched-pair buys 1–2 orders of magnitude variance reduction).
- **n = 5–10 paired runs** is enough to resolve a token/latency delta; it is NOT enough for a
  quality delta (that needs ~300+ — don't claim significance on quality).
- **ONE pre-registered primary metric** + a read date, written down *before* running (5-metric
  scorecards run a ~23% false-positive rate). Efficiency (`total_tokens` or `wall_clock_s`) is
  the usual primary; quality is a secondary, directional read only.
- **Pin the model version.** Every A/B result is valid within one model version only.
- **Quality judged blind + directional.** Hide variant labels; use the blind pairwise comparator
  in `evals/rubrics/judging.md`; report a direction, not a p-value.

## Stage benchmarks (measuring one pipeline stage instead of a whole leg)

A full end-to-end run costs ~450k tokens and mixes every mechanism together, so a single lever's
effect drowns in network and render noise. The stage protocol decomposes the search and draft legs
into stages, pins an input fixture per stage, and measures the one stage a lever touches at n = 1–2
pairs: [`protocols/stage-benchmarks.md`](protocols/stage-benchmarks.md) is the procedure (fixtures,
subject-agent prompt rules, stage-specific A/B rules), and
[`protocols/stage-map.md`](protocols/stage-map.md) is the stage decomposition it pins — per-stage
cost shares plus each stage's isolating fixture and observable boundary. Stage rows are recorded in
`evals/results/` from the template's stage section, and compare only against other rows of the
**same** stage, fixture version and model id.

## Baseline capture

Before changing anything, capture the current numbers so a later run has something to regress
against (design doc Phase 1 "know the numbers before changing anything"):

1. Check out the SHA you want as baseline; confirm `config.yaml` is unset (examples fallback) so
   the baseline is reproducible on any machine.
2. Run every canary for the skill (or all skills) via method (a) or (b).
3. Record, per canary: `rubric_pass` (0/1) and the three efficiency metrics, tagged with the git
   SHA (`report.py --by-sha` groups by SHA automatically).
4. File it in `evals/results/` (from the template) as the named baseline for that skill + SHA +
   model. This row is what the eval-gated-merge check and any A/B compares against.

## Re-baseline on model upgrade

**Every eval and A/B result is valid only within one model version** (design doc §2 pitfalls).
On a model upgrade (a new Claude Code default model, or a pinned-model bump):

1. Treat all existing baselines as stale — they no longer bound "expected" behavior.
2. Re-run the full frozen canary set on the new model, unchanged prompts/rubrics.
3. File fresh baselines tagged with the new model id. Evals here are precisely the
   **regression detector for model upgrades** — a canary that newly fails on the upgrade is the
   signal to investigate before adopting the model.

## Layout

Everything measurement-related lives under this one root: the procedures in `protocols/`, the
frozen prompt sets in `canaries/`, the judging discipline in `rubrics/`, the dated runs in
`results/`.

```
evals/
  README.md                     # this file — the operating manual
  protocols/
    ab-protocol.md              # step-by-step matched-pair A/B procedure (design doc §2)
    stage-benchmarks.md         # fine-grained, fixture-pinned per-stage measurement (v1)
    stage-map.md                # the stage decomposition stage-benchmarks.md pins (fixtures + boundaries)
    reconciliation-stages.md    # the R-leg map: post-merge two-repository reconciliation (R1–R4)
  canaries/
    <skill>.yaml                # 4–9 canaries per skill, 9 skills (see below)
  rubrics/
    judging.md                  # shared pass/fail discipline + blind pairwise A/B judging + κ note
    artifact-quality.md         # rubric for the artifacts a skill produces (resume, letter, dossier)
  results/
    .gitkeep                    # results are per-machine; tracked for now, may be gitignored later
    TEMPLATE.md                 # one-page result-recording template
```

The nine skills with a canary set are `application-tracker` (6), `ask-me-anything` (4),
`behavioral-interview-prep` (5), `company-research` (6), `email-assistant` (8),
`github-workflow` (4), `interview-calendar` (4), `job-search` (5) and `resume-writer` (9). Two
public skills deliberately have none: `gardener` and `search-recall-audit`, whose routines are
deterministic scripts covered by unit tests. An edit to either is therefore always a
"skip with a recorded one-line rationale" under the risk-based gate above — there is no canary
run to fall back on.

All canaries are **fully public**: only the "Jordan Rivers" fixture identity + fictional or
real-public companies with fictional postings. Zero personal data (the leak guard must be
completely clean — `automation/publish/check_public.py` exits 0 with zero findings in this repo;
ANY finding is a regression). Overlay-only skills are deliberately out of scope
— evals must be runnable on a public-only checkout.
