# The company-key guard reads function bodies, so a helper extraction defeats it

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: adversarial review of workspace phase 7, 2026-07-30 — reproduced, not theoretical
- **Claimed-by**:

## Goal

Make the additive-key guard cover the transitive call graph, so the invariant cannot be violated by
moving one expression into a helper.

## Context

`automation/shared/tests/test_company_key_additive.py::test_match_paths_do_not_mention_company_key`
asserts the literal `company_key` never appears in `inspect.getsource(fn)` for each guarded
function. **`inspect.getsource` returns the function body only.** Every guarded function delegates
to helpers that are not themselves guarded — `handoff._norm`, `store_refilter.canon`,
`audit._norm_company`, `skip_log.read_postings` and others.

An adversarial review **reproduced four mutations** that violate the invariant while the guard and
every affected suite stay green. The clearest:

> In `automation/search-recall-audit/audit.py`, extract the company normalisation out of
> `build_coverage` into a new module-level helper that reads `company_key or company`, and call it
> from `build_coverage`.

Guard: **PASS**. Suites: **OK**. And it changes the answer — on a fixture whose `company` and
`company_key` disagree (an alias *merge*, the exact failure the ADR names), the set of
same-company folders for a new posting went from one match to none. That is a genuinely new posting
being suppressed, which is the outcome the whole invariant exists to prevent.

Phase 7 partially mitigated this by adding the **deciders** to the guarded list — the review found
that the original 17 entries were all collectors and normalizers, while the functions taking the
actual verdict (`handoff._duplicate_reason`, `audit.coverage_for`,
`store_refilter.is_blacklisted`/`gate_decisions`, `skip_log.read_postings`/`fold`,
`application_context.find_application_matches`) were absent. The list is now 26 and each new entry
was mutation-checked. **That narrows the hole; it does not close it.** Any of the 26 can still
delegate to an unguarded helper.

## What a fix looks like

Walk the call graph from each guarded root rather than reading one body:

- parse each guarded module with `ast`, resolve the names each guarded function calls within its own
  module, and follow them to a fixed point (a depth limit is fine — record it);
- assert the literal appears nowhere in that closure;
- report the *path* when it fires (`build_coverage -> _company_identity`), because a bare
  "somewhere in the closure" message is not actionable.

Cross-module calls are the judgement call: full inter-module resolution is a lot of machinery for
this. Same-module closure plus the explicit decider list may be the right stopping point — decide
deliberately and write down what is deliberately not covered.

**The regression test must be one of the four reproduced mutations**, so the fix is proved against
the thing that defeated the old guard rather than against a hypothetical.

While here, two related weaknesses from the same review:

- `test_the_guard_list_is_not_vacuous` asserts only `len(MATCH_PATHS) >= N`, so deleting a guarded
  row and adding an unrelated one keeps it green. Assert the *membership* of the load-bearing
  entries, not the count.
- The behavioural half (`test_skip_sets_are_identical_with_and_without_company_key`) covers 2 of the
  readers. `audit.build_coverage` is source-guarded only because its signature does not share the
  `(log, root)` shape.

## Definition of done

- [ ] The guard follows calls out of each guarded function, not just its body
- [ ] At least one of the four reproduced mutations is a regression test, and is shown to pass the
      OLD guard and fail the new one
- [ ] When it fires, the message names the call path
- [ ] What the guard deliberately does not cover is written down in the module docstring
- [ ] `test_the_guard_list_is_not_vacuous` pins membership rather than a count
- [ ] Full gate green
