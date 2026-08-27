# Label the manager-product filter variant (#234)

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GitHub issue #234; split from 2026-07-31-two-unlabeled-filter-variants-from-a-stage-1-sweep
- **Claimed-by**: Codex /root/issue_validity
- **Parent**: 2026-07-31-two-unlabeled-filter-variants-from-a-stage-1-sweep

## Goal

Teach the shipped filter-variant corpus that a delimited product name ending in `Manager` is an
intentional title-review family, so a known classifier result no longer fails a snapshot audit.

## Context

Production already classifies a role such as `Software Engineer, Ads Manager` as `review` under
`title.manager_product_suffix_ambiguous`. The corpus lacks that signature, so the audit emits the
known shape as an unknown `pending-title-55d4274c` variant. This task must label existing behavior,
not broaden the production exception. The existing true `Engineering Manager` controls remain in
the corpus and unit tests; under those fixtures' explicit include/exclude profile, the canonical
title assessor must also keep the non-delimited `Software Engineer (Manager Tools)` boundary at
`no_match`. This pins the assessor and corpus boundary, not a universal full-pipeline drop: a
configured `titles.word_filter.include` or `soft_exclude` rule may intentionally rescue an
assessor `no_match` to the review queue.

## Definition of done

- A fictional manager-product title labels `title.manager_product_suffix_ambiguous` as `review` in
  `skills/job-search/filter_variants/corpus.yaml`.
- A snapshot-audit regression proves the manager-product row is no longer emitted as pending.
- Under the fixture profile, the canonical title assessor keeps true-manager titles and the
  non-delimited `Manager Tools` boundary at `no_match`; the task makes no claim that a configured
  full-pipeline word-filter rescue cannot route such an excluded title to review.
- Focused tests, the corpus validator, and impacted repository gates exit 0.
