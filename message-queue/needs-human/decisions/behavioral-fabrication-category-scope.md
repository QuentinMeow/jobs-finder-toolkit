# May category-level permission authorize agent-chosen fabricated claims?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-04
- **Source**: owner request in chat to permit fabricated metrics, ownership, adoption, and business impact
- **Blocks**: broadening the new exception beyond exact human-named claims
- **Default path**: keep authorization claim-specific; agents may use exact invented claims the human names, but may not choose new values or ownership assertions from a broad category
- **Cost if wrong**: high
- **Safe to merge because**: the default preserves the narrow exception and prevents one broad instruction from authorizing unbounded future invention

## Background

The owner asked for direct-human permission to override the default grounding rule and specifically
named categories such as metrics and ownership. Category permission is materially broader than
exact-claim permission: an instruction such as “fabricate impact for these answers” would let the
agent choose the number, adoption scope, business consequence, and ownership wording. The private
disclosure ledger would make each generated claim visible afterward, but it would not constrain
which claims the agent invents before generation.

## Options

### Option A — exact claims only

The human supplies the actual invented claim or number. Lowest ambiguity, but it does not satisfy
requests that deliberately delegate selection of realistic metrics to the agent.

### Option B — named categories within named artifacts (recommended if this latitude is intended)

A direct human may explicitly say “fabricate” or “make up” named categories—such as metrics,
ownership, adoption, or business impact—for named behavioral artifacts. The agent may then choose
plausible claims only inside those categories, records every resulting exact claim separately, and
may not reuse them in another artifact. Requests merely to strengthen or quantify still do not count.

**Informed-risk note:** Option B gives an agent discretion to create interview claims the human did
not enumerate in advance. The ledger makes them reviewable but does not make them true.

**Your answer:** ______
