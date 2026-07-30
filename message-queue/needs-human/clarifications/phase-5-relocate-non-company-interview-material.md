# When you said "don't touch anything else", did that also mean "don't move it"?

- **Status**: folding — answered 2026-07-30, being folded into the ADR and the phase-5 task
- **Blocking**: no
- **Assumption**: reading (a) — the 55 non-company interview files are **relocated** to their
  taxonomy home (`me/interviews/stories/`, `me/interviews/questions/`,
  `me/interviews/replies/`) but not **reorganised** in any way: same files, same names, same
  internal structure, new parent folder.
- **Matters-by**: before the first phase-5 commit that touches `interviews/`. Not urgent — a
  separate decision put the link-checker repair ahead of phase 5, so that work comes first.
- **Filed**: 2026-07-29
- **Source**: [the interview-material ADR](../../../memory/decisions/interview-material-moves-by-company-only.md)
  · [execution plan, phase 5](../../../docs/designs/workspace-restructure/execution-plan.md#what-the-owner-decided-and-what-that-forbids)

## Background

You settled the interview tree on 2026-07-29: move company-specific things into company-specific
folders, "then don't touch anything else unless it's an obvious mistake". That resolved 497 of
the 552 tracked files outright — everything under the company-specific root, plus the
company-prefixed files in the behavioral question bank — and it clearly forbids reorganising
their contents (no per-problem folders, no new round-type schema, no splitting aggregate
documents).

**55 files are not company-specific and the sentence reads two ways for them**: 17 story-bank
files, 36 general question-bank files (18 `_general_*`, one README, 16 under `sources/`, one
under `tests/`), and 2 shared reply drafts.

- **Reading (a) — relocate, don't reorganise.** The three folders move to their homes in the new
  personal root: stories to `me/interviews/stories/`, the general question bank to
  `me/interviews/questions/`, the shared replies to `me/interviews/replies/`. Nothing inside them
  changes — not a filename, not a heading, not a directory below the top level.
- **Reading (b) — leave the interview tree alone entirely.** The company-specific material moves
  out; whatever is left keeps sitting at `interviews/` under its current name.

**I am proceeding on (a)**, because relocation is the entire point of the phase — it is what
builds the `me/` · `companies/` · `applications/` split — whereas reorganisation is the thing you
declined. Reading (b) would leave a fourth top-level root holding 55 files whose lifetime is
exactly the same as everything else in `me/`, and would guarantee a second migration later.

Two things worth knowing before you answer:

- Under (a), one of the three folders already has a config key
  (`paths.story_bank_dir`), so its move is a `config.yaml` edit. But its *display key* is
  hardcoded in two places, and changing one and not the other makes every tailoring card read
  permanently stale — so under (a) that pair has to move together, which the plan already tracks.
- Under (b), nothing breaks either. The cost is only that the taxonomy is left half-built.

**Your answer:** (2026-07-30, in chat) *"I confirm that you are right, they get relocated to
`me/interviews/…` without being reorganised."*

Reading **(a)**, as assumed. The 55 non-company files move to `me/interviews/stories/`,
`me/interviews/questions/` and `me/interviews/replies/`; nothing inside them changes — not a
filename, not a heading, not a directory below the top level. The assumption phase 5 was already
carrying is now a decision, so nothing about the plan changes; what changes is that it no longer
rests on an inference.
