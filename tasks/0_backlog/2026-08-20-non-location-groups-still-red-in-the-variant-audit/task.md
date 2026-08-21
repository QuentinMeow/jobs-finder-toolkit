# Three non-location groups still leave the filter-variant audit red (#247)

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: cluster C3 (location gate), branch `fix/location-gate-precision`, 2026-08-20

## Goal

Give the remaining structural groups from issue #247 a documented expected disposition in
`skills/job-search/filter_variants/corpus.yaml`, so `validate_filter_variants.py` exits 0 on a
fresh public snapshot rather than reporting unlabeled groups a novice cannot act on.

## Context

Issue #247 lists eight recurring structural classes that leave the shipped corpus audit red on a
15,326-row snapshot. The five LOCATION classes are now labelled (branch
`fix/location-gate-precision`, commit "test(location): label the location groups the corpus audit
left unnamed"):

- `Vancouver, WA, US` misread as mixed US/foreign scope — fixed and labelled.
- `USCA` short-form location — fixed and labelled.
- Stripe-shaped US-remote plus a conditional office policy — labelled.
- Brex-shaped hybrid plus four remote weeks a year — fixed and labelled.
- Vercel-shaped hybrid/mixed-region — NOT labelled: the issue does not quote the wording, and the
  location classifier could not be shown to misread any reconstruction of it. Whoever has the live
  snapshot should paste the actual location string and JD excerpt into a fixture.

Three groups remain and are NOT location shapes, so they belong to the title and sponsorship
owners:

- `Ads Manager` title ambiguity x5 — tracked separately in #234.
- Anthropic sponsorship conflict x6 — a sponsorship-domain variant.
- unclassified location x129 — listed here despite its name because #247 gives no example string.
  A large part of that count was `mixed_us_foreign_scope` and `weird_location_format` on the shapes
  now fixed, so re-run the validator against a FRESH snapshot before adding fixtures: the count is
  expected to fall sharply, and whatever remains needs its real strings quoted rather than guessed.

`skills/job-search/filter_variants/corpus.yaml` is the shipped corpus; append new cases at the end.
`skills/job-search/scripts/filter_variants.py` carries `lint_corpus` / `check_corpus`, and
`skills/job-search/scripts/tests/test_filter_variants.py` runs them.

## Definition of done

- One labelled corpus variant per remaining group, each carrying that group's real structural
  wording.
- `.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests`
  exits 0.
- `validate_filter_variants.py` exits 0 against a fresh stage-1 snapshot, or the residual groups are
  re-filed with their actual strings quoted.
