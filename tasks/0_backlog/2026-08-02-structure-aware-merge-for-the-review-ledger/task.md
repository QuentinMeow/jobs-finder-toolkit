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

## Status, 2026-08-02: the recurrence-prevention half is DONE; the merge driver is not

The well-formedness check below shipped on `fix/24-ledger-row-validation`. `_LedgerLoader` in
`review_gate.py` now overrides `construct_mapping` and rejects a repeated key **during
construction** — which is the only place it is visible, because `yaml.safe_load` keeps the last
duplicate and hands back an ordinary dict that passes every per-row rule the gate has
(`DuplicateKeyTests.test_the_parsed_row_alone_shows_nothing_wrong` pins that). The failure names
the row by its opening `- <key>: <value>` line, lists the repeated keys, and says the ledger TEXT
is damaged rather than the reader's commit. Exit code is 2 (a ledger problem), unchanged.

The "names at least one of `commit:`/`base:`" half was **already enforced** by `validate_row`
before this task was filed (`a row with neither pins no range`, covered by
`PendingRowTests.test_a_row_with_neither_anchor_is_rejected`); nothing was needed there.

Regression tests: `LedgerValidationTests.test_a_line_based_merge_of_the_ledger_is_refused` drives a
real `union` merge of two rows for one range in a throwaway repo — the merge still succeeds
silently, and the gate now exits 2 on its output — plus `DuplicateKeyTests`, which pins the
interleaved shape, the stray-line-in-a-neighbour shape, and the two legitimate row shapes
(`commit:`+`base:`, and pending `base:`-only) that must not regress. All four refusal tests were
run against the pre-change code and fail there.

**Still open, and deliberately not bundled:** everything under "Pick one and implement it" — the
row-granular merge driver (a) versus recording the manual resolution as an ADR (b). That is a
larger decision about mechanism, not about detection, and the check above is what makes either
choice safe to take slowly: a line-based merge can no longer corrupt a row *quietly*.

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

- [x] **A well-formedness check on the ledger**, wherever the gate already parses it: every row
  carries each key at most once and names at least one of `commit:`/`base:`. This is the check whose
  absence let a corrupted row through a green `--verify-all`. It is a *validation* of an existing
  gate's own input, not a new gate, so it does not conflict with
  `process-weight-what-to-cut.md`'s default path. **Done 2026-08-02** — see Status above.
- [x] A regression test built from the real failure: two rows for the same range whose keys are in
  different order, merged, asserting the result has no duplicate keys. **Done 2026-08-02** — the
  test performs the `union` merge itself rather than asserting on hand-written interleaved text,
  so it cannot drift from what the driver actually produces.

## Measured evidence, 2026-08-21 (appended; nothing above was changed)

A ten-agent session (15 merged PRs, #340-#354) gave this its largest real convergence test to date.

- The ledger conflicted on **6 of 6** first-wave branches, and on every branch afterwards. It was the
  **only** conflicting file on all of them.
- Merging any one PR re-dirtied **every** other open PR within ~20 seconds. Measured directly: after
  #341 merged, #340/#342/#343/#344 all moved `MERGEABLE` to `CONFLICTING`. Ten parallel agents
  therefore landed strictly sequentially, each round costing a hand resolution, a re-push, a CI run
  (~2 min) and a merge.
- Resolving by **YAML round-trip** was tried and discarded: `yaml.safe_dump` of the parsed rows
  reformatted all 351 historical rows — **1,986 insertions and 1,412 deletions to append 3 rows**.
  The gate accepted the result, so this failure is silent to tooling and only visible to a human
  reading the diff. Worth naming in this task as a third rejected resolution alongside the `union`
  driver.
- The resolution that worked, applied 12 times without incident: **byte-level append** — take the
  incoming side's bytes whole, then re-append this branch's authored bytes whole. This matches the
  remediation text `review_gate.py` already prints ("recover the authored rows from git history and
  re-append them whole").
- `skills/job-search/filter_variants/corpus.yaml` has the identical shape and conflicted three times
  in the same session, for the same reason: independent agents each append entries at the end of one
  list. Whatever this task decides should name that file too.

Follow-on: `tasks/0_backlog/2026-08-21-parallel-agent-work-is-serialized-and-its-green-results-are-unverified`
treats the ledger itself as THIS task's scope and does not duplicate it.
