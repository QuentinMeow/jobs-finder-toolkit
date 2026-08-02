# Should `AGENTS.md` name the public review gate, the way it names the reconciler?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [workspace-restructure review-gate design](../../../docs/designs/workspace-restructure/review-gate.md)
- **Blocks**: nothing.
- **Default path**: no document changes. Agents keep meeting the gate where they meet
  it today — at pre-commit, from its own failure message — and keep riding the ledger
  row along with the next commit.
- **Cost if wrong**: ratify
- **Safe to merge because**: no document changes, and agents already meet the gate where it
  actually runs.

## Background

`AGENTS.md`'s Guardrails section names exactly one gate:

> - **The reconciler is a gate**: `automation/reconcile/reconcile.py --check` … runs in
>   pre-commit + CI and must pass — fix the finding or let `--file-retries` queue it;
>   never weaken a check to make a commit pass, never bypass with `--no-verify`.
> — `AGENTS.md:230-233`

The public review gate is at least as consequential and appears in none of the three
contract documents: `grep -ic "review_ledger\|review gate\|review_gate"` over `AGENTS.md`,
`README.md` and `CONTRIBUTING.md` returns **0, 0, 0**. It blocks anyway, in both places
the reconciler does — `automation/hooks/pre-commit:98-99` and
`.github/workflows/ci.yml:154-163` (`review_gate.py --verify-all`, with `--head <sha>` on
a PR).

**One correction to that framing before you decide, because it changes the size of the
gap.** The gate is not undocumented. `skills/github-workflow/SKILL.md:183` carries it as
row 3 of the ten-gate table, and `:204-223` is a dedicated subsection ("The review gate
and the one-commit lag") explaining the ride-along convention in full. `AGENTS.md:110`
routes agents there for *"PR descriptions, stacked PRs, CI, the push gates"*. So an agent
doing PR work is routed to a correct and thorough explanation.

**The gap that is left is narrower and specific:** the gate fires at **pre-commit**, which
is the very first commit of a session, long before anything routes anyone to the PR skill.
An agent that has read `AGENTS.md` and its task's files and nothing else meets a red gate
it has no context for. What saves it is that the failure message is unusually
self-teaching — `review_gate.py:566-600` prints the changed files, the `git diff` to read,
the exact YAML row to append, and the one-behind rule in prose. So the practical cost of
the silence is one surprised agent per session, not a stuck one.

**What it is not.** Not a budget problem: `AGENTS.md` is 318 lines against a 500-line
budget (`automation/metrics/instruction_budget.py --strict`), so there is room.

**The real cost of adding it** is precedent. Guardrails names one gate out of ten by
choice. Add a second and the section is now, in a reader's mind, the place gates are
listed — and the other eight have an equal claim to be there. The containment I would
suggest if you say yes: Guardrails names a gate only when there is a **behavioural rule
an agent could violate** attached to it. The reconciler has one ("never weaken a check,
never `--no-verify`"). The review gate has one too, and it is not obvious from the code:
the row rides along with your *next* commit rather than getting a commit of its own. The
other eight gates have no such rule — they are pass/fail and the fix is mechanical — so
the line holds.

The fork-contributor half of this question is filed separately as
`message-queue/needs-human/decisions/does-the-review-ledger-bind-fork-contributors.md`;
it needs a different answer from a different audience and one may be decided without the
other.

## Options

### Option A — no change (default path)

The gate stays documented in `skills/github-workflow/SKILL.md` only, and teaches itself
at the moment it fires.

*Pros:* Guardrails stays a list of behavioural invariants, not a gate inventory; zero
maintenance. *Cons:* the first commit of every session is where an agent can be surprised,
and surprise at a gate is where "let me just add `--no-verify`" gets invented — which
`AGENTS.md` forbids in the reconciler bullet and nowhere else.

### Option B — one Guardrails bullet in `AGENTS.md`, pointing rather than restating

Roughly three lines: the gate's name and file, that it blocks in pre-commit and CI, the
ride-along rule, and a pointer to `skills/github-workflow/SKILL.md` §3 for the mechanics.
Nothing restated that the skill already explains.

*Pros:* the anti-bypass injunction lands on the gate most likely to attract a bypass,
instead of only on the reconciler. *Cons:* the precedent above; the containment rule has
to be honoured by later editors or the section grows.

### Option C — `README.md` too

README already tells a human reader that the leak guard blocks in CI and pre-push
(`README.md:107-108`). The review gate is the second half of that same story and is
absent from it.

*Pros:* the human-facing account of "what stops personal data shipping" becomes complete.
*Cons:* README is for people evaluating the toolkit, and this gate is meaningless to
anyone who is not committing to *this* repository — it is maintainer machinery in a
document about capability.

## Recommendation

**Option B, and I hold it weakly.** The honest case for it is not that agents cannot learn
the gate — the failure message is genuinely complete, down to telling you that a
ledger-only commit closes a branch without creating new work (`review_gate.py:597-599`).
It is that `AGENTS.md` states *"never weaken a check to make a commit pass, never bypass
with `--no-verify`"* exactly once, attached to the reconciler, whose failures are
mechanical and easy to fix. The gate where an agent is actually tempted to reach for
`--no-verify` is the one that fires unexpectedly and asks it to certify a diff — and that
one is not covered by the sentence. Three lines move the injunction to where the
temptation is.

If you read that as too thin to spend contract lines on, Option A is a perfectly good
answer and the status quo already works.

Not Option C: README's audience is people deciding whether to use the toolkit, and this
gate never runs for them.

**Your answer:** ______
