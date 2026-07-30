# Phase 5 moves company-specific interview material into company folders and reorganises nothing else

- **Status**: decided
- **Date**: 2026-07-29
- **Decided by**: owner
- **Supersedes / Superseded-by**: retires the standing "roughly four dozen `interviews/` files
  are genuine judgment calls" item in
  [the workspace-restructure execution plan](../../docs/designs/workspace-restructure/execution-plan.md#phase-5--the-lifetime-taxonomy-inside-private)

## Context

Workspace phase 5 gives the private overlay a lifetime taxonomy: durable knowledge (`me/`,
`companies/`, `market/`) outlives any one application. The interview tree is the largest
unsettled part of that move — 552 tracked files, the biggest single subtree the phase touches
outside applications themselves.

The plan carried a standing open item saying that "roughly four dozen `interviews/` files are
genuine judgment calls, not mechanical moves", each to be routed through the owner before
placement. It named four kinds: flat per-language solution files that arguably wanted a folder
per problem, a round type the plan's schema did not model, aggregate documents spanning several
problems, and one loose reply draft. The count was an estimate, never re-derived. Left standing,
it made phase 5 open-ended — the phase could not be scheduled, because nobody knew how many
owner round-trips it contained.

Two things about this tree are worth stating plainly, because they are why the question was
answerable at all. First, the material is working reference the owner reaches for *during* an
interview, not a curated knowledge base — its value is in being findable, not in being modelled.
Second, one directory level already encodes the only classification that matters: everything
under the company-specific root sits inside a per-company folder, so its owner is knowable from
its path without reading it.

## Decision

**Move company-specific material into company folders. Reorganise nothing else.**

Everything under the company-specific root is company-specific by construction, so all of it
moves to `companies/<key>/` — including both items the plan had flagged as open judgment calls.
Company-prefixed files in the behavioral question bank move to their company too. Re-measured
against the overlay on 2026-07-29:

| Subtree | Tracked files | Destination |
|---|---:|---|
| `interviews/` total | 552 | — |
| `interviews/company-specific/` | 478, across 25 company folders | all → `companies/<key>/` |
| ├ per-company research | 299, in 18 of those folders | `companies/<key>/research/` |
| ├ per-company coding material | 163, in 9 of those folders | `companies/<key>/coding/` |
| ├ per-company product-sense material | 15, in one of those folders | `companies/<key>/product-sense/` |
| └ one loose reply draft | 1, directly inside a company folder | `companies/<key>/` |
| `interviews/behavioral/question-bank/` | 55 | 19 company-prefixed → `companies/<key>/`; the other 36 → `me/interviews/questions/` |
| `interviews/behavioral/story-bank/` | 17 | `me/interviews/stories/` |
| `interviews/common-message-replies/` | 2 | `me/interviews/replies/` |

The two previously-open judgment calls are resolved by the same rule that resolves everything
else: the product-sense folder does not need a round-type schema, because it moves whole under
its company; the loose reply draft does not need a home chosen for it, because it already sits
inside a company folder.

**What the decision forbids.** The owner's standard is "don't touch anything else unless it's an
obvious mistake". That rules out every *content* reorganisation the plan had proposed inside this
tree:

- no splitting flat per-problem solution files into a folder each,
- no round-type schema for the product-sense material,
- no breaking aggregate documents that span several problems into per-problem pieces,
- no company-versus-personal re-homing judgment, because location under a company folder is
  already the answer.

An agent may repair something *plainly* broken while passing through — a typo'd path, a file
filed under the wrong company — but may not restructure. The test is whether the fix needs an
argument: if it does, it is not an obvious mistake, and the right move is to leave it and file it.

**What this decision does not settle.** "Don't touch anything else" reads two ways for the 55
non-company files (the story bank, the general question bank, the shared reply drafts): either
(a) do not *reorganise* them but still *relocate* them to their taxonomy home, or (b) leave the
interview tree entirely where it is. The working assumption is **(a)** — relocation is the
taxonomy phase 5 exists to build, whereas reorganisation is what the owner declined — and it is
filed for confirmation as a clarification queue item (since answered and deleted when folded —
see the amendment below; the queue contract keeps git history as the archive rather than a
`done/` folder). It is not blocking: a separate owner decision put the link-checker repair ahead
of phase 5, so there is time for an answer before any of it matters.

**Amendment, 2026-07-29 — settled as (a).** The owner confirmed in chat: *"I confirm that you are
right, they get relocated to `me/interviews/…` without being reorganised."* So the 55 non-company
files move to `me/interviews/stories/` (17), `me/interviews/questions/` (36) and
`me/interviews/replies/` (2), with nothing inside them altered — not a filename, not a heading,
not a directory below the top level. The clarification item was deleted in the commit that folded
this in, per the queue contract; git history is its archive. The paragraph above is left standing
rather than rewritten, because an ADR records what was decided *and when it was still open* — the
fact that this hung on an inference for a day is part of the record, not an embarrassment to
tidy away.

Nothing in phase 5 changes as a result: (a) was already the working assumption the plan and the
task were built on. What changes is that the largest remaining piece of phase 5 no longer rests
on an agent's reading of an ambiguous sentence.

**No company is named here, and none may be.** This tree *is* the owner's interview history;
`AGENTS.md`'s leak rule forbids naming a real employer in the public tree, and the public review
gate caught exactly this class of leak once already. Counts and shapes only.

## Alternatives considered

- **Keep routing each file through the owner individually.** What the plan said. Lost because it
  makes an unschedulable phase out of a mechanical one, and because the owner's answer shows the
  premise was wrong: the files are not individually ambiguous, they are uniformly resolved by
  their parent folder.
- **Reorganise while moving** — problem folders, a modelled round type, split aggregates. Lost
  because it confuses two jobs. The taxonomy phase is about *lifetime* (does this outlive the
  application?), and answering that question does not require rewriting the material's internal
  shape. Reorganising in the same pass also destroys the property that makes the move safe to
  verify: file-for-file correspondence before and after.
- **Leave `interviews/` untouched and let phase 5 cover only the rest.** Lost because the
  company-specific half is precisely the durable knowledge the `companies/` root exists to hold;
  omitting it would leave the taxonomy half-built and guarantee a second migration later.

## Consequences

- **Phase 5's interview work becomes mechanical and countable**, and the plan's "four dozen
  judgment calls" estimate is withdrawn rather than refined. What remains open is one yes/no
  clarification covering 55 files, not four dozen individual placements.
- **Fidelity is the acceptance test.** Because nothing is reorganised, the move can be verified
  file-for-file: same count in, same count out, per company folder. Any discrepancy is a defect,
  not a judgment call — which is a much stronger gate than the plan previously had here.
- **The per-company file counts are lopsided and that is fine.** 18 of 25 company folders carry
  research, 9 carry coding material, one carries product-sense material. `companies/<key>/` must
  tolerate sparse subtrees; no folder shape is mandatory.
- **A later reorganisation stays possible and is now cheap to reason about**, because it would be
  its own decision against a settled layout rather than a rider on a migration.
- **Revisit if** the flat layout is observed to actually cost the owner time in a live interview
  — that is the only evidence that would justify the reorganisation this decision declines.
