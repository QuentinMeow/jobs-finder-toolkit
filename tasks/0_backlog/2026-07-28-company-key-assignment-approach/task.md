# Decide how the ~94 unresolvable company keys get assigned

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../design/workspace-restructure/execution-plan.md) · [design](../../../design/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Choose whether an agent proposes a complete companies/_index.yaml in one PR for owner
review, or auto-slugs and corrects incrementally.

## Context

Non-blocking. Filed from the workspace-layout review (Q3), deferred by the owner
2026-07-28.

213 distinct company strings across 242 application folders; `registry.canonical()` resolves
119. The remaining ~94 need a human call — Google, Microsoft, Adobe, Netflix, Uber,
Salesforce, Oracle, Snap, T-Mobile, both spellings of Canonical, plus subsidiaries and joint
ventures (`aws`/`amazon`, `alibaba-cloud`, `tiktok-usds`, `warpstream`/`confluent`).

Slugification is already lossy and inconsistent in live data: `Customer.io`→`customer-io` but
`You.com`→`youcom`; `Pure Storage`→`purestorage` but `Included Health`→`included-health`.

Default if never decided: one proposal PR the owner reviews in a single pass. Phase 7 of the
workspace restructure consumes the answer but is not blocked on it reaching a conclusion —
only on the approach being chosen when that phase starts.

## Definition of done

- [ ] The approach recorded in the phase-7 task, or an owner decision filed and folded
