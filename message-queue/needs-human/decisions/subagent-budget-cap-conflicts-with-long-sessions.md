# The 8-subagent cap conflicts with the sessions you actually ask for — scope it, exempt it, or enforce it?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [the cap itself](../../../docs/handbook/subagent-budget.md) · [`AGENTS.md`](../../../AGENTS.md) "Subagent Budget" · [a canary record that measured a fan-out against it](../../../evals/results/company-research-046a1f17e5f5-20260730-reference-retier.md)
- **Blocks**: nothing. Work continues either way; the cap is unenforced, so today the conflict resolves itself silently in whichever direction the session happens to go.
- **Default path**: **follow the cap as written for search and application fan-out — the case it was written for.** Where you have explicitly directed a long autonomous session that cannot be done inside 8 subagents, exceed it and say so in the session's report. Do not delete or weaken the text meanwhile.
- **Cost if wrong**: ratify
- **Safe to merge because**: the cap is unenforced text; following it writes nothing, and
  exceeding it is reported in the session's own report.

## Background

`AGENTS.md` and `docs/handbook/subagent-budget.md` both say the same thing:

> When a single user request fans out into multiple applications or searches, launch **at most 8
> subagents total** across the entire request, including later waves. Reuse or resume those agents,
> or finish remaining work in the parent agent; never launch a ninth. This is a repo-wide cap — the
> skills reference it rather than restating it.

Three things about it, each checked on 2026-07-31.

**1. It is unenforceable and unenforced.** There is no counter, no test, and no gate. `grep` for
`subagent` across `automation/` and `skills/` scripts returns only unrelated prose in
`field_fidelity.py`. Nothing anywhere can observe how many subagents a session launched, so the
cap is honour-system-only and its violation leaves no trace.

**2. Its first sentence scopes it and its third sentence unscopes it.** *"When a single user
request fans out into multiple applications or searches"* is narrow — it names the two job-hunt
fan-outs the rule was written for. *"This is a repo-wide cap"* is not. Both readings are on the
page, so an agent facing a large harness task can honestly reach either conclusion.

**3. "A request" is undefined, which is where it actually breaks.** The one record that measures a
fan-out against it — a `company-research` canary set — reports that *"two of the three runs fanned
out into their own research subagents"*, one canary alone spending `~123 turns + 4 subagents` and
roughly 1M tokens. If "a request" means one canary, that run complied. If it means the six-canary
set the user asked for, it did not. The record itself reads the cap as the only thing bounding the
run's cost, which is a real function worth keeping.

**And the conflict is live, not hypothetical.** You have directed long autonomous sessions whose
shape — an adversarial review across two repositories, then a stack of PRs — cannot be done inside
8 subagents without the parent doing everything serially, which is slower and worse. So the repo
currently ships a hard-sounding rule that its own owner routinely and reasonably overrides. That
is the failure mode worth fixing: **a rule nobody can enforce and everybody overrides teaches
agents that the contract is aspirational**, which is expensive for every *other* rule in
`AGENTS.md`.

## Options

### Option A — scope it to what it was written for *(recommended)*
Restrict the cap in both files to **search and application fan-out** — the case where each
subagent costs a full JD fetch or a full draft, and where 8 really is the right ceiling. Say
explicitly that harness, review and multi-repo work is governed by judgement and by the session's
own report, not by this number. Keeps a real cost control exactly where it controls a real cost,
and stops it being a rule that is broken weekly.

**What breaks:** the one measured benefit disappears for the runs that most need it. The
company-research canary record says the cap was *the only thing* bounding a multi-million-token
run. Scoping it out of harness work means nothing bounds those; the honest mitigation is that the
session must report its fan-out, so the cost is visible after the fact even though it is not
capped before.

### Option B — keep it repo-wide, add an owner-directed exemption
Keep the number, and add: *"a session the owner has explicitly directed as long-running and
autonomous may exceed the cap; it must state the total it used in its report."* Smallest edit,
preserves the default, makes the override legitimate instead of silent.

**What breaks:** "explicitly directed" is a judgement call an agent makes about your intent, and
agents will read it generously. It converts a hard number into a soft one without saying so.

### Option C — keep it as written and actually enforce it
Add a per-session subagent counter, refuse the ninth, and record the count in the session's
handover. Honest, and the only option under which the number means anything.

**What breaks:** most. It is real tooling for a rule with one recorded near-violation, it would
have blocked several sessions you asked for, and it puts a hard stop in front of work whose right
shape is genuinely parallel. It also cannot see subagents launched by a subagent.

### Option D — delete the cap
Removes the conflict by removing the rule. Loses the one thing it demonstrably did: bound the cost
of a canary run that would otherwise have spent several million tokens unobserved.

## Recommendation

**Option A, with the reporting half of Option B folded in.** Scope the cap to search and
application fan-out, where it maps to a real per-subagent cost and where 8 is defensible; and
require any session that fans out more widely to state its total in the report, so cost stays
visible even where it is not capped. That keeps the number honest in the place it was measured,
removes a rule that is routinely and correctly overridden elsewhere, and does not build enforcement
machinery for a problem that has produced one recorded near-miss.

Whichever you pick, **both surfaces must change in the same commit** — `AGENTS.md`'s Conventions
line and `docs/handbook/subagent-budget.md` — and the two skills that cite the number
(`job-search`, `search-recall-audit`) reference it rather than restating it, so they follow
automatically.

**Your answer:** ______
