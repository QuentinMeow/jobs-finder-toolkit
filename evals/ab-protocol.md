# Matched-pair A/B protocol

Step-by-step procedure for A/B testing a harness edit (a SKILL/LESSONS change, or a model
upgrade) on the frozen canary set. Distilled from the maintainer-only,
overlay-mounted design doc (absent in contributor checkouts)
[`private/docs/harness-engineering-and-repo-evolution/05-harness-engineering-methodology.md`](../private/docs/harness-engineering-and-repo-evolution/05-harness-engineering-methodology.md)
§2 and Phase 3. This is the Phase-3 companion to the Phase-2 regression canaries in `README.md`.

## The one governing fact

Token count and wall-clock are **near-deterministic per fixed task**; a subjective quality delta
is **statistically brutal** (`n_per_arm ~= 16·sigma^2/MDE^2`; judge sigma ~= 0.18, MDE 0.04 →
~324 paired examples; below ~100 there is no credible resolution). A solo repo never reaches those
counts. Therefore:

> **A/B efficiency quantitatively (n = 5-10 paired runs). A/B quality only directionally
> (blind comparator; report a direction, never a significance claim).**

## Before you run (pre-registration — do NOT skip)

1. **Pick ONE primary metric and write it down first.** Usually `total_tokens` (lowest variance)
   or `wall_clock_s`. Five-metric scorecards run a ~23% false-positive rate — one primary metric,
   the rest secondary/descriptive.
2. **Record the read date** and the decision rule ("ship B if median `total_tokens` drops >= X%
   with no canary rubric regression"). Pre-registering the metric + read date is what stops peeking.
3. **Pin the model version.** Every A/B result is valid within one model version only. Record the
   exact model id; if it changes mid-test, the test is void — restart.
4. **Freeze the canary set.** Use the committed `evals/<skill>/canaries.yaml` prompts unchanged.
   Job boards / the live web drift weekly, so a moving task set would confound the comparison
   (task non-stationarity). For network-dependent canaries (job-search, company-research), run A
   and B **back-to-back per prompt** so both hit the same board/web state.
5. **Define the two variants.** A = baseline SHA/branch, B = the edited SHA/branch. Keep the diff
   surgical (one change), so a win ships as one revertible commit.

## Run (matched pairs)

6. **For each canary prompt, run BOTH variants on the SAME input** — a matched pair. Pairing
   analyzes per-prompt deltas and buys 1-2 orders of magnitude variance reduction vs independent
   groups (it kills the data-noise term), at 2x inference cost. Fresh session per run.
7. **n = 5-10 paired runs** across the canary set (repeat a prompt for more pairs if a skill has
   few canaries). That is enough to resolve an efficiency delta; it is NOT enough for a quality
   delta — do not try.
8. **Log every run to `logs/metrics.jsonl`** (Phase-3 hooks, keyed by git SHA). Keep the
   pairing recorded (which A run matches which B run on which prompt).

## Analyze

9. **Efficiency (quantitative) — the primary result.** Aggregate per SHA:
   ```bash
   .venv/bin/python automation/metrics/report.py --by-sha
   ```
   Report the **mean and median** of the primary metric per variant, and the **per-pair delta**
   (B − A on the same prompt). Because pairs share the task, the paired delta is the low-variance
   signal — a 30% token / 40% wall-clock cut shows clearly at n = 5-10. Also report `tool_calls`
   (a loop/thrash leading indicator) as a secondary descriptive metric.
10. **Quality (directional) — the secondary read.** Judge blind + pairwise per
    [`rubrics/judging.md`](rubrics/judging.md): hide variant labels, present outputs as
    "Output 1 / 2" in randomized order, pick which better meets each canary's `expected_behavior`,
    tally after revealing labels. Report as a direction ("B preferred 6/8, 2 ties"), never a
    p-value. Calibrate the judge first (Cohen's kappa >= 0.6).
11. **Guardrail: no rubric regression.** Every canary must still PASS its regression rubric on the
    winning variant. An efficiency win that fails a canary (e.g. dropped the MTS≠staff edge case,
    or the 5-Whys moat rigor) is not a win — it is exactly the ACE "brevity bias" failure the
    gates exist to stop.

## Decide + ship

12. **Apply the pre-registered decision rule.** If the primary metric wins by the pre-set margin,
    quality is directionally non-worse, and no canary regressed → ship B.
13. **Ship the winner as a normal single-purpose commit** (surgical, so `git revert` is clean if
    it later disappoints). Record the A/B in `evals/results/` from `results/TEMPLATE.md` (the A/B
    section): variants, model id, n, primary-metric deltas (mean/median), the directional quality
    read, and the ship decision.

## Validity scope (state it on every result)

- **One model version.** The result does not carry to a different model — re-run on any model
  upgrade (that upgrade is itself an A/B against the pinned baseline).
- **One frozen task set + (for network canaries) one capture window.** Re-running weeks later on
  drifted boards is a new experiment, not a continuation.
- **Efficiency = measured; quality = directional.** Never upgrade the quality read to a
  significance claim at this sample size.
