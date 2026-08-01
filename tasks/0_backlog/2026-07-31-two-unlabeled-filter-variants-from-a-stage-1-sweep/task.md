# Two unlabeled structural variants from a stage-1 example sweep

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: routine `--max-age-days 3` search on the `example` profile, 2026-07-31; `validate_filter_variants.py` exited 1
- **Claimed-by**:

## Goal

Label the two structural variants that `validate_filter_variants.py` flagged as unknown, so the
title and location classifiers have a deterministic answer for their shapes and the snapshot audit
goes back to exiting 0.

## Context

A routine stage-1 sweep on the public `example` profile fetched 11,639 postings. The mandatory
snapshot audit then reported:

```
UNKNOWN title 55d4274ceefb87d8 x2: pending-title-55d4274c
UNKNOWN location b45419505ac08d8f x2: pending-location-b4541950
Snapshot has 2 unlabeled structural variant(s)
```

Both shapes are already handled conservatively — each was routed to `review` rather than silently
accepted or dropped — so nothing was lost in that run:

- `pending-title-55d4274c` — rule `title.manager_product_suffix_ambiguous`. An IC engineering
  title whose *product surface* is named "… Manager" (a product noun, not a people-management
  role). The classifier cannot currently tell that suffix from a real management title, so it
  yields `review` with `confidence: low`.
- `pending-location-b4541950` — rule `weird_location_format`. An ATS location string that is a
  run-together multi-country token with no separator, so neither the foreign check nor the
  US-abbrev check can read it. Also `review`, `confidence: low`.

Neither variant affected that run's answer: both example postings were roughly two months old and
therefore outside the 3-day window that was asked for. This is classifier maintenance, not a miss.

The full report (with the example postings and the `label_required` stubs) is at
`local/filter_variant_reports/<snapshot>-unknown.yaml`. `local/` is gitignored, so **the report
does not survive a fresh clone** — regenerate it by re-running the audit on any snapshot that
contains the same shapes.

Per `skills/job-search/SKILL.md` § Filter-variant gate, the fix order is: verify the shape against
the real JD, extend the deterministic classifier, then add a **fictional minimal** regression to
`skills/job-search/filter_variants/corpus.yaml` — never a real posting, since that file is public.

## Definition of done

- Both signatures classify deterministically (no `pending-*` stub for them).
- One fictional minimal corpus case per shape added to `filter_variants/corpus.yaml`.
- `.venv/bin/python skills/job-search/scripts/validate_filter_variants.py --snapshot <a snapshot
  containing both shapes> --profile example` exits 0, and the corpus self-check still passes.
