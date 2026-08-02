# Should the review-gate design doc be updated to describe the ledger's `base:` key?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-01
- **Source**: [docs/designs/workspace-restructure/review-gate.md](../../../docs/designs/workspace-restructure/review-gate.md)
- **Blocks**: nothing. The gate works and is documented where it runs.
- **Default path**: **leave the design doc alone.** The live description of `base:` stays
  in the `review_gate.py` module docstring, which is what agents and CI read.
- **Cost if wrong**: ratify
- **Safe to merge because**: the default edits nothing at all. Adding a paragraph later is
  a pure addition to a Markdown file, and the behaviour it would describe is already
  written down in the module that implements it.

## Background

`automation/publish/review_gate.py` grew an optional `base:` key on ledger rows. A row's
verified range is normally derived from its **position** in the list (`base_index`), which
breaks when several branches cut from one base append their rows at the end. A row that
carries `base:` is verified as `<base>..<commit>` verbatim instead. The key is additive: a
row without it falls back to `base_index` and verifies exactly as it always has. All of
this is documented in the module's own docstring (the "A ROW'S OWN BASE" section) and
enforced by `OPTIONAL_KEYS`/validation in the same file.

`docs/designs/workspace-restructure/review-gate.md` is the design doc that specified the
gate. It predates the `base:` key and does not mention it.

The tension is with `docs/designs/AGENTS.md`, which states:

> Historical families are records — never rewrite their conclusions.

`workspace-restructure` is a shipped family. So: is adding `base:` to its design doc
"rewriting a conclusion" (forbidden), or "keeping a reference current" (fine)?

## Options

### Option A — leave the design doc alone (the default path)

The design records what was decided then; the module docstring records what the code does
now.

- Respects the records rule literally, and keeps one authority for live behaviour — the
  code. A docstring cannot drift from its implementation the way a doc in another tree can.
- Matches where the gate's readers already look. Nothing in pre-commit or CI reads the
  design doc.
- Cost: a reader who starts from the design doc sees a spec that is a version behind. They
  would have to open the module to learn `base:` exists.

### Option B — append a dated addendum to the design doc

Leave the original text untouched and add an "Amendments" section noting the key and
pointing at the module.

- Nothing is rewritten, so the records rule holds in spirit and letter.
- The design doc stops being silently stale.
- Cost: starts a pattern where every shipped design accretes addenda, which is the drift
  the records rule exists to prevent. Two authorities to keep in sync instead of one.

### Option C — rewrite the design doc's gate section to match today's behaviour

- Cost: this is the one option `docs/designs/AGENTS.md` forbids outright. Listed only to
  be explicit that it was considered and rejected.

## Recommendation

**Option A.** The records rule is unambiguous, and the `base:` key is an implementation
detail of *how* a range is computed rather than a change to what the gate concludes — the
gate still verifies that every published commit range was reviewed. Keeping the live
description in the module docstring means it cannot fall out of sync with the code, which
is the failure mode that matters here. If you find yourself reading the design doc for
current behaviour more than once, Option B is the cheap escalation.

**Your answer:** ______
