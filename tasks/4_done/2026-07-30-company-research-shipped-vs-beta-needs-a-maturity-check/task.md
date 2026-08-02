# company-research asks for shipped-vs-planned but its own recommended sources cannot answer it

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: found by the `cr-full-research-structure` canary run, 2026-07-30 —
  [the eval record](../../../evals/results/company-research-046a1f17e5f5-20260730-reference-retier.md)
- **Claimed-by**: agent (fix/10-company-research-correctness, 2026-07-31)
## Goal

Give the skill one line telling the agent where product maturity actually lives, so the
shipped-versus-announced split it already demands can be made correctly.

## Context

`skills/company-research/SKILL.md` § `06` requires separating **already shipped** — features
live in the hands of users or engineers — from **announced or planned**, and the Final Checks
require the split to carry dates and evidence. It is one of the most valuable things the skill
asks for, because "AI-first" press releases are exactly what a candidate should not repeat in an
interview.

The skill's guidance for establishing *shipped* is only "cite the artifact", and
`reference.md` § "Handy Fetches" points at the vendor's docs and product directory. That is not
enough, and a canary run demonstrated why: a large vendor's product-directory entries and docs
landing pages **carry no maturity badge**. One page read "Available on all plans" — a pricing
tier — for a product that had been in open beta for about fifteen months. Another product had
been in private beta for roughly a year with nothing on the page saying so.

Following the skill's own recommended sources produced **four wrong "shipped" classifications**.
They were caught only because a second verification pass went to the launch blog post and the
body text of the docs, neither of which the skill names.

This is not a research-quality problem to solve with "be more careful". The signal genuinely is
not on the page the skill sends you to.

## Approach

One sentence in `SKILL.md` § `06` is probably the whole fix — something with the shape of
*"a product-directory entry is not evidence of GA: confirm maturity in the launch post or the
docs body, and give the beta stage and its duration when it is one."* Consider also:

- adding the launch-post-and-docs-body check to `reference.md` § "Handy Fetches" beside the
  fetches that produce the wrong answer today;
- whether the same trap applies to the `05` moat file, which also reasons from product
  capability — a beta product is weaker evidence for a moat than a GA one.

Check whether `evals/canaries/company-research.yaml`'s `cr-ai-strategy` rubric should gain a
bullet for it. It currently asks for the shipped-versus-planned split but not for the evidence
class that establishes it, so a run can satisfy the rubric with a confident wrong answer.

## Definition of done

- [ ] `SKILL.md` § `06` names where maturity is actually established, in the routine path
- [ ] The `cr-ai-strategy` canary can distinguish a correct split from a confident wrong one
- [ ] company-research canaries pass, recorded in `evals/results/`
