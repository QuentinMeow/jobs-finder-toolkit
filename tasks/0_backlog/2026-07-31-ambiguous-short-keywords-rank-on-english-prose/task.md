# A profile keyword that is also an English word ranks on ordinary prose

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: adversarial audit #2, finding 33; originally triaged as ACCEPTED
  (not fixed). GH #279 re-filed it with live evidence and the `go` case was fixed
  in code on 2026-08-20 — see below for what is left
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

A profile can say "Go, the programming language" — or R, or C, or Swift —
without also matching "go-to-market", "R&D", "plan C" and "a swift response".

## What has already shipped (2026-08-20, GH #279 parts 1-2)

`common.term_matches` no longer accepts an ambiguous term on the strength of a
word boundary alone. `_AMBIGUOUS_TERM_GUARDS` maps such a term to a guard that
must ALSO read the occurrence as the technology; `_go_is_the_language` is the
one shipped guard, and `skills/job-search/scripts/tests/test_term_matching.py`
pins nine English phrasings that no longer score and eleven Go phrasings that
still do.

That took no profile-schema change, which is what the original triage said any
fix would need. It also closed the title-gate half of #279 for this one word:
a `go` include term no longer rescues a finance title the occupation lexicon
rejected.

## What is left

1. **Other ambiguous terms have no guard.** A profile listing `r` matches every
   "R&D" (`normalize()` turns `R&D` into `r d`), `c` matches "plan C", `swift`
   matches "a swift response", `rust` matches literal rust. Each needs its own
   guard entry, and each guard is a small vocabulary of frames — cheap
   individually, but nobody should write six of them speculatively. Add one when
   a real search shows that term producing noise.
2. **A profile still cannot DECLARE its own ambiguous term.** The guard table is
   code, so a candidate whose vocabulary contains an ambiguity the repo never
   anticipated has no way to express it. That is still the profile-SCHEMA change
   the original triage priced: the example profile, the loader,
   `validate_filter_variants` and every private profile move together, and the
   schema has to answer what an old profile omitting the field means.

## Definition of done

- [ ] Either a guard exists for each ambiguous term a real search shows scoring
      on prose, or a profile can declare one (design choice still open:
      phrase-only flag, companion-term requirement, or a regex form)
- [ ] A test per added term: one prose JD that no longer scores it, one genuine
      JD that still does — the shape `test_term_matching.GoIsNotEveryGo` uses
- [ ] `skills/job-search/scripts/validate_filter_variants.py --check` clean
