# Eval result — company-research

| Field | Value |
|-------|-------|
| Skill | `company-research` |
| Canary set | `evals/canaries/company-research.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `046a1f17e5f5` |
| Model version | `claude-opus-5` |
| Config mode | examples fallback (`config.yaml` unset, no overlay — a detached worktree) |
| Date | `2026-07-30` |
| Judge | manual, against `expected_behavior` per `evals/rubrics/judging.md` |

## Why this run exists, and what it does not cover

The triggering edit moves five blocks out of `SKILL.md` into `reference.md`. That is a
**retiering**, which `evals/README.md` lists under MUST-run.

Three of the six canaries were run, chosen because between them they exercise **all five
moved blocks**. The other three exercise none of them and were **not run**. That distinction
is stated here rather than left to the reader: "the canaries pass" and "the canaries that
could detect this change pass" are different claims, and only the second one is being made.

| Canary | Moved block it exercises | Run? |
|---|---|---|
| `cr-moat-5whys` | the 5-Whys worked example | yes |
| `cr-question-bank` | the question-bank example questions | yes |
| `cr-full-research-structure` | competitor scorecard · company rating · why-this-company | yes — see the note below |
| `cr-product-cold-reader` | none | no |
| `cr-ai-strategy` | none | no |
| `cr-honest-scaffolding-fictional` | none | no |

## Per-canary results

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|---|---|---|---|---|
| `cr-moat-5whys` | **1** | ~125k | 721 | 32 | Followed the moved pointer verbatim and read only the named section |
| `cr-question-bank` | **1** | ~1.0M | 1767 | ~305 | Followed both moved pointers; see the efficiency finding below |
| `cr-full-research-structure` | — | — | — | — | Run started; result recorded separately if it completes |

Pass rate on the canaries judged: **2/2**.

## Verdict

- **Regression: PASS** on both judged canaries. Every `expected_behavior` bullet held and no
  listed `failure_mode` appeared.
- **The specific thing this run had to establish — that an agent still finds content behind a
  pointer instead of losing it — held in both cases.** Each run reported reading
  `reference.md` and quoted the trigger line that sent it there. `cr-moat-5whys` applied the
  moved 5-Whys pattern to reject a "network effects" claim as a saturating data-scale effect,
  which is the reasoning the moved example teaches. `cr-question-bank` produced all three
  mandatory groups in the moved example's format, one parenthesised intent tag per question.

## Efficiency finding, and it is not good news

`cr-question-bank` consumed roughly **1.0M tokens** and exhausted the session's WebSearch
budget, because the run fanned out into four research subagents of its own. `cr-moat-5whys`,
doing comparable work in one context, used ~125k.

That is an 8x spread on two canaries from the same skill, and it is **not attributable to this
edit** — nothing in the retiering encourages fan-out, and there is no pre-edit baseline to
compare against. It is recorded because the eval gate asks whether an efficiency metric blew
up, and the honest answer is "one run did, for a reason the diff does not explain". Anyone
running this set again should expect the cost and consider whether the canary should pin
subagent count.

## What the runs found in the skill (filed, not fixed here)

Both runs reported the same contradiction independently:

- `SKILL.md` § "Acquisition and Output Reference" says **"read `reference.md` completely"**,
  while the moved-block pointers say **"read ONLY `reference.md` § …"**. Both fire on the same
  task. Every agent followed the broader instruction and read the whole file.

  **This means the retiering buys budget headroom, which was its goal, and not token savings,
  which it was never promised to buy.** Filed as
  `tasks/0_backlog/2026-07-30-company-research-read-completely-defeats-its-own-pointers`.

- The skill assumes an application record exists (`config.applications_root()/<status>/<slug>/`
  with `meta.yaml` and a saved JD) and states no fallback for researching a company that has
  none. Both runs hit it and improvised. Filed as
  `tasks/0_backlog/2026-07-30-company-research-no-application-record-fallback`.

Neither is caused by the retiering; both were found by running it.
