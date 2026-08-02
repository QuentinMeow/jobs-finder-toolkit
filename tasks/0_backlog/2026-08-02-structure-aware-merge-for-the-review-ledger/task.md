# Give the review ledger a structure-aware merge, or keep resolving it by hand

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: the `union` driver's first real convergence corrupted a row, 2026-08-02 (PR #198 introduced it, PR fix/13 removed it)
- **Claimed-by**:

## Goal

Make a converging merge of `automation/publish/review_ledger.yaml` either **correct** or **loud** —
never silently wrong. Today it is loud (a plain conflict, resolved by hand). The open question is
whether a row-granular driver is worth building to make it correct-and-quiet instead.

## Context

Every branch that changes the published tree appends a row here, so parallel branches always
collide on this one file. PR #198 addressed that with git's built-in `union` merge driver in
`.gitattributes`, reasoning — correctly — that "keep both sides' rows" is the only append-only-legal
resolution, and that it is *semantically* safe because every row now records its own `base:` and so
cannot be silently re-parented by a change in list order.

**The semantics were right; the mechanism was not.** `union` concatenates **lines**, not rows. On
the first real convergence two rows for the same range had been written with their keys in different
order (one had `finding:` last, per the file's convention; the other had it before `files:`/`digest:`).
The line-level union interleaved them, and a `finding:` line came to rest inside a neighbouring row.
YAML resolves a duplicate key to the last one, so that row silently began reporting a review its
author never wrote.

Nothing caught it. `review_gate.py --verify-all` stayed exit 0, because a row's digest is computed
over the commit range it names, not over its own prose — so a corrupted `finding:` is invisible to
every existing check. It was found only by eye, while reading the file for an unrelated reason.

`union` is now removed. Merges conflict again, which is safe but costs a manual resolution per
convergence — the exact cost #198 set out to remove.

## Definition of done

Pick one and implement it:

**(a) A row-granular merge driver.** A `merge.ledger.driver` entry plus a script that parses both
sides into rows (a row starts at a line beginning `- ` in column 0), emits base rows then each side's
new rows in order, and **fails loudly** rather than writing anything if any input or output row
carries a duplicate key or names neither `commit:` nor `base:`. Must be stdlib-only if the reconciler
ever reads it.

**(b) Decide the manual resolution is cheap enough** and record that as an ADR, with the per-merge
cost measured rather than guessed.

Either way, also do this — it is the part that actually prevents recurrence:

- **A well-formedness check on the ledger**, wherever the gate already parses it: every row carries
  each key at most once and names at least one of `commit:`/`base:`. This is the check whose absence
  let a corrupted row through a green `--verify-all`. It is a *validation* of an existing gate's own
  input, not a new gate, so it does not conflict with `process-weight-what-to-cut.md`'s default path.
- A regression test built from the real failure: two rows for the same range whose keys are in
  different order, merged, asserting the result has no duplicate keys.
