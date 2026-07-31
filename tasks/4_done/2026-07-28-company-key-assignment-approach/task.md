# Decide how the ~94 unresolvable company keys get assigned

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: [workspace-restructure execution plan](../../../docs/designs/workspace-restructure/execution-plan.md) · [design](../../../docs/designs/workspace-restructure/README.md) · [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
- **Claimed-by**:

## Goal

Choose whether an agent proposes a complete companies/_index.yaml in one PR for owner
review, or auto-slugs and corrects incrementally.

## Context

Non-blocking. Filed from the workspace-layout review (Q3), deferred by the owner
2026-07-28.

213 distinct company strings across 242 application folders; `registry.canonical()` resolves
119, leaving 94 that need a human call (re-measured 2026-07-29, unchanged). **Redacted
2026-07-29:** an earlier version of this paragraph listed the real employers behind those 94.
That is the owner's application history, and it must never sit in the public tree — the same
leak the review gate caught in commit `ef2d0a3`. Describe the shape, never the instance:

| Shape | Example form | Why a human is needed |
|---|---|---|
| household-name employer with no registry row | `<Name>` | the registry is identity-only and was never meant to be exhaustive |
| bare name vs. name + legal suffix | `<Name>` / `<Name> Ltd.` | which spelling becomes the key |
| subsidiary or cloud arm under a parent | `<Child>` under `<Parent>` | `parent:` vs. a key of its own |
| regional joint venture under a global brand | `<Brand> <Region>` | one loop or two |
| acquired product under an acquirer | `<Product>` under `<Acquirer>` | which name the owner will search for |

Slugification is already lossy and inconsistent in the live data. Both failure directions occur:
a dot inside a name is sometimes kept as a hyphen and sometimes dropped entirely
(`<name>.io` → `<name>-io` but `<name>.com` → `<name>com`), and a two-word name is sometimes
hyphenated and sometimes concatenated. So the existing folder slug cannot be trusted as the key.

Default if never decided: one proposal PR the owner reviews in a single pass. Phase 7 of the
workspace restructure consumes the answer but is not blocked on it reaching a conclusion —
only on the approach being chosen when that phase starts.

## Definition of done

- [ ] The approach recorded in the phase-7 task, or an owner decision filed and folded
