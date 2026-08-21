# The validator prints one census number and keeps the reconciliation in a file

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: GH #253; the 2026-08-20 `fix/filter-pipeline-reports` branch reconciled the
  census DATA and was scoped out of `validate_filter_variants.py`
- **Claimed-by**:

## Goal

The line a person actually reads after running the filter validator states the whole
funnel, so the reconciliation does not depend on opening a YAML file.

## Context

`skills/job-search/scripts/filter_variants.py::first_reject_census` now returns
`total_postings`, `total_rejected`, `preserved_for_review`, `total_survived` and a
`reconciliation` block, and `validate_filter_variants.py` already writes the whole dict
into the census YAML, so the machine-readable half of GH #253 is done.

The stderr line is not. `skills/job-search/scripts/validate_filter_variants.py` still
prints only:

    First-reject census: {total_rejected} of {len(postings)} postings hard-rejected
    across {n} rule famil...

which is the exact sentence that could not be reconciled with the search's
`kept + review`, because it names one bucket out of three. Anyone comparing the two
surfaces at the terminal is still doing the arithmetic that produced the bug report.

Suggested line, from values the census already returns:

    First-reject census: 7284 hard-rejected + 7 preserved for review + 371 survived
    = 7662 scanned (balanced) -> <path>

and, when `reconciliation.balanced` is false, say so loudly rather than printing a total
that does not add up — the same rule `render_funnel_section` follows on the search side.

## Definition of done

- The validator's stderr line names every bucket and their sum, and flags an unbalanced
  census instead of hiding it.
- A test covers both the balanced and the unbalanced line.
- `python automation/gates/run_gates.py --impact-from origin/main` green.
