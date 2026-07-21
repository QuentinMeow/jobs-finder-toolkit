# Evals — canary regression + matched-pair A/B for the skill harness

Operating manual for the eval scaffolding that keeps this repo's real product — the
`SKILL.md` / `LESSONS.md` corpus — from silently degrading. This is **Phase 2 (Evals)** of
the harness-engineering roadmap; the design and statistics live in the maintainer-only,
overlay-mounted design doc (absent in contributor checkouts)
[`private/docs/harness-engineering-and-repo-evolution/05-harness-engineering-methodology.md`](../private/docs/harness-engineering-and-repo-evolution/05-harness-engineering-methodology.md)
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
   this repo's volume). See [`ab-protocol.md`](ab-protocol.md).

## The eval-gated-merge rule (risk-based)

From the self-evolution quality-control box (repo design README) and design doc §"quality gates"
#5 — **Eval-gated merge:**

> The canaries of an affected skill must PASS before a SKILL/LESSONS edit merges; model-pin the
> eval run.

**Relaxed to risk-based on 2026-07-20 (maintainer decision).** The mandatory per-edit canary run
above proved too time-consuming, so canary runs are now **optional and agent-judged**. For any
edit to `.agents/skills/<skill>/{SKILL.md,LESSONS.md,reference.md}`, the editing agent decides
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

**Every skip must be recorded** — one line in the PR description (or the commit body for a direct
commit): `Eval gate: skipped — <intention + size rationale>`. A run is recorded as before, in
`evals/results/`. Skips are not permanent exemptions: the **next** behavioral gate run at head
always covers the accumulated state, not just its own triggering diff — so a later gated edit
re-tests everything that skipped ahead of it.

When a run is required, the mechanics are unchanged. For any PR that edits
`.agents/skills/<skill>/{SKILL.md,LESSONS.md,reference.md}`:

1. Identify the affected skill(s) from the diff.
2. Run that skill's canaries (`evals/<skill>/canaries.yaml`) on the branch head.
3. Every canary's `primary_metric` (`rubric_pass`) must pass, and no efficiency metric may blow
   up (a large `total_tokens` / `tool_calls` regression is a fail even if the rubric passes).
4. Record the run in `evals/results/` from the [`results/TEMPLATE.md`](results/TEMPLATE.md).
5. Only then merge. This gate sits **on top of**, never replaces, the other inviolable gates
   (delta edits only; MEMORY→LESSONS→SKILL promotion needs a separate human-reviewed commit;
   consolidation may never delete a domain edge case; everything reverts via small commits).

This gate is advisory tooling today (a human or the editing agent runs it before merge); a future
CI hook can enforce it — see the repo AGENTS.md proposal in the P4 hand-off report.

## How to run a canary

A canary is `{id, prompt, setup, expected_behavior (rubric), failure_modes, primary_metric,
efficiency_metrics}`. Two ways to execute it.

### (a) Anthropic's skill-creator harness (preferred — evals + A/B in one)

The skill-creator harness is purpose-built for Claude Code skills (which are literally this
repo's product): evals as **test-prompt + plain-language rubric**, a **benchmark mode** that
tracks eval pass rate + elapsed time + token usage, multi-agent parallel eval in clean contexts,
and **blind comparator agents** for A/B ("two skill versions, or skill vs. no skill — judge
without knowing which is which"). Map each `canaries.yaml` entry onto a skill-creator eval:
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
   .venv/bin/python scripts/metrics/report.py --by-sha
   ```
   Read `total_tokens` and `wall_clock_s` for the run's SHA; note `tool_calls`. Copy the
   pass/fail + numbers into a `evals/results/` file from the template.

## Matched-pair A/B protocol (summary — full steps in `ab-protocol.md`)

- **Frozen canary set.** Use the same `canaries.yaml` prompts for both variants; never edit a
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
  in `rubrics/judging.md`; report a direction, not a p-value.

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

```
evals/
  README.md                     # this file — the operating manual
  ab-protocol.md                # step-by-step matched-pair A/B procedure (design doc §2)
  rubrics/
    judging.md                  # shared pass/fail discipline + blind pairwise A/B judging + κ note
  results/
    .gitkeep                    # results are per-machine; tracked for now, may be gitignored later
    TEMPLATE.md                 # one-page result-recording template
  <skill>/canaries.yaml         # 3–6 canaries per public skill (6 skills; gardener excluded — its routines are deterministic scripts)
```

All canaries are **fully public**: only the "Jordan Rivers" fixture identity + fictional or
real-public companies with fictional postings. Zero personal data (the leak guard must be
completely clean — `scripts/publish/check_public.py` exits 0 with zero findings in this repo;
ANY finding is a regression). The private `coding-interview` skill is
deliberately out of scope — evals must be runnable on a public-only checkout.
