# Move the search's filter vocabulary out of code and into the profile, in three classes

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: owner decision 2026-08-02, recorded as `memory/decisions/search-filter-vocabulary-is-profile-owned.md` (folded from the queue item title-prefilter-hardcoded-seniority-words, deleted in the folding commit — git history is the archive)
- **Claimed-by**:

## Goal

No script decides which title words a search filters on. The vocabulary comes from the
candidate's search profile in three classes — hard-exclude, soft-exclude, inclusion — and each
class behaves as the owner described. This task is the **conformance checklist** an
implementation is checked against, because the decision is a design direction and deliberately
does not contain a finished spec.

## Context

Read `memory/decisions/search-filter-vocabulary-is-profile-owned.md` first — it carries the
owner's answer verbatim, which is the specification here. The three classes, in the owner's own
examples:

| Class | Example | Behaviour |
|---|---|---|
| hard-exclude | `intern` | always drop; not fetched, not reasoned about |
| soft-exclude | `manager` | **never dropped on the title alone** — could be a real software-engineering role, or a product literally named "manager"; the JD is read and the AI judges |
| inclusion | (candidate's own) | a hit means the role **must** be examined and reasoned about |

An agent may already be shipping a first cut of this while this task sits in the backlog. That is
fine and expected — the point of this file is that the first cut is checkable against what was
actually asked for, rather than against whichever half of it was convenient.

Where the old contract lives:

- `skills/job-search/scripts/sources.py` — the hardcoded title-skip tuple and `_title_prefilter`,
  which runs on the title alone before the per-posting detail fetch.
- `skills/job-search/scripts/scoring.py` — `assess_title`, the profile-driven title gate the
  prefilter currently pre-empts.
- `skills/job-search/profiles/_TEMPLATE.yaml` and `skills/job-search/profiles/README.md` — the
  public statement of what a profile may say; the three classes have to be documented here.
- `skills/job-search/SKILL.md` and `skills/job-search/reference.md` — the title-gate description.
- `skills/search-recall-audit/SKILL.md` — its sampling instructions restate `titles.exclude`
  semantics and will be wrong once exclusion is no longer binary.

Nothing under `skills/` was touched by the folding session: it held only the process tree
(`message-queue/`, `memory/`, `docs/handbook/`, `tasks/0_backlog/`). The principle is stated in
`docs/handbook/configuration.md`; every file above still describes the old behaviour.

**The cost this must not pay twice.** Soft-exclude means titles that used to be dropped before the
detail fetch are now fetched. Per-board candidate caps are applied in page order, so a wider
candidate set can push wanted roles past the cap with no filtered row and no count — the exact
silent-loss shape the decision exists to end. Handle it deliberately (raise the caps, order the
candidate list, or report displacement); do not let it be the implementation's unremarked cost.

## Definition of done

- [ ] No candidate-specific filter word is a literal in any script under `skills/`; a test fails if
      one is re-introduced.
- [ ] The profile schema carries the three classes, each with the documented behaviour, and the
      shipped template + `profiles/README.md` explain the difference between hard and soft.
- [ ] A soft-exclude hit is never dropped on the title alone — proven by a test where a posting
      whose title carries a soft-exclude word survives to the JD-reading step.
- [ ] An inclusion hit is surfaced for reasoning rather than silently kept alongside ordinary
      matches.
- [ ] Displacement is addressed explicitly: the change says what happens to wanted roles when the
      candidate set grows, and that claim is measured, not asserted.
- [ ] `skills/search-recall-audit/SKILL.md`'s restatement of exclusion semantics agrees with the
      new three-class rule.
