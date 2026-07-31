# company-research assumes an application record exists and says nothing about what to do when it doesn't

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: found by the `cr-moat-5whys` and `cr-question-bank` canary runs, 2026-07-30 —
  [the eval record](../../../evals/results/company-research-046a1f17e5f5-20260730-reference-retier.md)
- **Claimed-by**:

## Goal

Give the skill a stated path for "research this company" when no application folder for it
exists, so two agents do not improvise two different answers.

## Context

`skills/company-research/SKILL.md` § "Before You Start" step 3 sends the agent to the
application record — `config.applications_root()/<status>/<slug>/` with its `meta.yaml` and
`source/JD-*.md` — to ground the role deep-dive (`08`), the why-this-company angles (`10`), and
the level/scope questions in the question bank.

"Research company X for an interview" is a perfectly ordinary request that arrives **before**
any application exists. The skill has no branch for it. Two canary runs hit this independently
and each invented a different accommodation: one wrote a company-level file with a scope note
explaining the absence, the other tagged individual lines `[JD-dependent]` so they could be
re-targeted later. Both are reasonable. Neither is written down, so the next run invents a third.

The gap is wider than one missing sentence, because several outputs are *specified* in terms of
the posting: `08-role-deep-dive.md` has no subject, the why-this-company angles are supposed to
be per role type, and the recruiter questions ask about level and scope. A fallback has to say
what happens to each.

There is a second, smaller instance of the same shape: the skill requires `09-question-bank.md`
to "summarize the prepared answer and link to the fuller `10-why-this-company.md`", but a user
who asks only for the question bank never gets a `10`. One run inlined the `10` template into
`09` to avoid a dangling reference — again reasonable, again unwritten.

## What to decide

- Does company-level research without a posting produce the **full** folder with the
  posting-dependent files scaffolded, or a **reduced** set that stops before `08`?
- Are posting-dependent lines marked (`[JD-dependent]`) so a later run can re-target them, or
  left out until a posting exists?
- When a single file is requested and it is specified to link a file that was not produced, does
  the skill inline, link forward, or drop the reference?

## Definition of done

- [ ] `SKILL.md` states the no-application-record path in the routine section, not in
      `reference.md` — this is the common case for early-stage research, not an escalation
- [ ] The three questions above are answered in the file, in one place
- [ ] company-research canaries pass, recorded in `evals/results/`
