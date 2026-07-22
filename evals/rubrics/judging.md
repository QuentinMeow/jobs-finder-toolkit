# Shared judging rubric

How to score a canary run and how to judge an A/B comparison. Applies to every
`evals/<skill>/canaries.yaml`. Keep the judge (model + this prompt) fixed for the whole test.

## Pass/fail discipline (regression canaries)

Each canary's `primary_metric` is `rubric_pass` — a single 0/1 verdict.

1. **Every `expected_behavior` bullet is an independent pass/fail check.** Read the transcript
   and mark each bullet met / not met. Do not average into a vibe score.
2. **The canary passes (`rubric_pass = 1`) only if ALL checks hold.** One missed check is a fail.
   This is deliberately strict — a canary exists to catch the regression its checks describe.
3. **A listed `failure_mode` observed = automatic fail**, even if the positive checks look met
   (the failure modes are the specific regressions we are guarding against).
4. **Judge behavior, not prose.** Credit the check when the run actually did the thing (ran the
   right script, produced the right file/structure, respected the guardrail), not when it merely
   claimed it. When a check is about a file/artifact, inspect the artifact.
5. **Efficiency is recorded, not scored into `rubric_pass`.** But a large `total_tokens` or
   `tool_calls` blow-up vs the baseline is a merge-blocking regression on its own (see README's
   eval-gated-merge rule) — flag it in the result even when the rubric passes.
6. **No partial credit, no coaching.** Judge the response to the prompt exactly as a real user
   typed it. If the run asked a reasonable clarifying question the skill sanctions (e.g. an
   ambiguous role), that is not a fail — note it and judge the continued run.

Borderline calls: prefer FAIL and write one line on why. A false pass hides a regression; a
false fail just prompts a re-run.

## Blind pairwise comparison (A/B quality judging)

For the directional quality half of a matched-pair A/B (`evals/ab-protocol.md`), quality is judged
**blind and pairwise**, never as an absolute score:

1. **Hide the variant labels.** For each canary prompt, collect variant A's and variant B's
   outputs, strip anything identifying which SKILL/LESSONS version produced them, and present them
   as "Output 1" / "Output 2" in a randomized order per prompt (flip a coin per prompt so position
   is not a tell).
2. **Judge which output better satisfies that canary's `expected_behavior`** — pick 1, 2, or tie.
   Use the same rubric bullets as the regression judging; the question is *comparative*
   ("which better meets the checks"), not "how good is each".
3. **Only reveal labels after all prompts are judged.** Then tally wins/losses/ties per variant.
4. **Report a direction, not a p-value.** e.g. "B preferred on 6/8 prompts, 2 ties" — this is a
   directional read only. The sample math for a *significant* quality delta needs ~300+ paired
   examples (judge sigma ~0.18, MDE 0.04), which this repo never reaches, so **never attach a
   significance claim to a quality result.** Efficiency deltas (tokens/wall-clock) are the
   quantitative channel; quality stays directional.
5. **Pairwise/arena beats absolute for subjective rubrics** — comparative judgments are lower
   variance than asking for a 1-5 score on each output independently.

## Cohen's kappa calibration note

Before trusting any judge (a human or a fixed LLM judge prompt) for A/B, calibrate it:

- Have the judge label a **held-out set of 100-300 example verdicts** that also carry a trusted
  reference label (e.g. your own careful pass/fail on past canary runs, or a second independent
  judge's labels).
- Compute **Cohen's kappa** between the judge and the reference. **Require kappa >= 0.6** before
  the judge's verdicts count in an A/B; below that the judge is too noisy to resolve a directional
  quality call and you are measuring judge noise, not the harness.
- Pin the judge model + this rubric prompt for the entire test; re-calibrate on a judge-model or
  rubric change (a new judge is a new instrument). kappa corrects for agreement-by-chance, which
  raw percent-agreement does not — a judge that always says "pass" can score 90% agreement at
  kappa ~ 0.
- On a model upgrade, the judge is part of what changed — re-calibrate before reusing old A/B tooling.

## Recording a result

Record every run — regression or A/B — from the one-page template
[`../results/TEMPLATE.md`](../results/TEMPLATE.md). Copy it to
`evals/results/<skill>-<git-sha>-<date>.md`, fill the `rubric_pass` and efficiency numbers
(pull tokens/wall-clock from `automation/metrics/report.py --by-sha`), and tag the model version.
Results are per-machine (they depend on network/board state and the local model) — they are
tracked for now and may be gitignored later; do not treat a result file as a shared source of truth.
