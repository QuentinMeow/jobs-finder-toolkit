# Handover — search-recall-audit skill + parser-fidelity hardening

- **Date**: 2026-07-26
- **Task(s)**: none (tooling hardening; job-hunt session specifics recorded privately)

Timeless-tooling work landing in the public toolkit. The real job-search session
that motivated it (target list, drafted companies, profile specifics) is recorded
in the private overlay, not here.

## What happened

- **New PUBLIC skill `search-recall-audit`** (`SKILL.md` + `LESSONS.md`): a QA
  harness that randomly samples raw JDs (grepping the WHOLE posting, never
  title-only), fans them to subagents that judge each against the *active
  profile's* gates, then **deterministically traces** every apparent miss to the
  exact gate that dropped it. Ships two tools under
  `automation/maintenance/search_recall_audit/`: `audit.py` (recall/precision
  `corpus`/`sample`/`trace`) and `field_fidelity.py` (generated-`location`
  vs raw-source fidelity). Both are read-only on the pipeline and write only to
  gitignored `tmp/`. Registered in `AGENTS.md` (skill list + read order).
- **Location parser fidelity** (`posting_parsers.py`): Lever now folds
  `allLocations` + `country`, Ashby folds `address.addressCountry`/`addressRegion`,
  and Apple no longer duplicates the country string. `location.py` gained an
  ambiguous-region-bucket detector + a `weird_location_format` review reason so a
  bare bucket ("West"/"Central") routes to `review` instead of a silent guess.
  Vendored copies re-synced byte-identical.
- **Title gate** (`scoring.py`): a narrow exception routes an IC-role title that
  ends in a delimited product-name "… Manager" (e.g. "Software Engineer — Mission
  Manager") to `review` instead of the hard `manager` exclude — never an outright
  match. Definite management occupations still hard-drop. New unit tests added.
- **Registry** (`companies.yaml`): added an opt-in AI + Healthcare company-identity
  batch (`poll_batch: image-leads-02`) and tagged Benchling `healthcare`.

## Where things stand

- Done and green: job-search unit suite (incl. the new `ManagerProductSuffix` and
  location tests), the recorded eval result
  (`evals/results/job-search-4b20b7cd728c-2026-07-25.md`), the public leak guard,
  and the reconciler `--check` all pass.

## Needs your attention

- One non-blocking decision filed in the private decisions queue (whether a
  company's FIRST-ever search should use a wider recency window). The documented
  manual wide-refilter recipe is the default path and was applied.
