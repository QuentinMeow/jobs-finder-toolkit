# Document the ATS-API JD-fetch fallback in the job-search reference tier

- **Status**: todo
- **Priority**: P1
- **Area**: job-search
- **Source**: `evals/results/stage3-benchmark-20260720.md:58-59`;
  `evals/results/stage2-benchmark-20260720.md:83-85`

## Goal

Give the ATS-API JD-fetch path (`company_roles.py`'s direct-to-ATS-API fetch,
already documented for company/board-token lookups in
`.agents/skills/job-search/reference.md` § "Supported ATS APIs") an explicit,
discoverable place in the skill reference as the recommended fallback when a
posting's own page is JS-rendered and `fetch_jd.py`'s verbatim scrape comes back
unusable.

## Context

`.agents/skills/job-search/reference.md` § "Supported ATS APIs (public, no auth
for reads)" already documents the Greenhouse/Ashby/Lever/SmartRecruiters JSON
endpoints, and `company_roles.py --dump-jd` already fetches a posting's
description directly from those APIs — bypassing whatever the job board's own
page renders client-side. In the Stage-3 pinned benchmark row, this path
recovered 100% of JS-rendered JD pages across two different ATSes when a runner
used it, and in the Stage-2 pinned benchmark row a comparable search leg did not
think to use it at all (the reference search recovered a JS-rendered page via the
single-company script; the paired run's search leg did not). The capability
exists and works; it just has no documented tie to the "a JD page came back
JS-rendered / empty" trigger that a search or drafting agent would actually hit.

Relevant files:
- `.agents/skills/job-search/reference.md` (the ATS APIs section to extend, plus
  wherever the doc currently covers `fetch_jd.py` failure/fallback handling, if
  anywhere)
- `.agents/skills/job-search/scripts/fetch_jd.py` (the verbatim-scrape path that
  can come back JS-rendered/garbled)
- `.agents/skills/job-search/scripts/company_roles.py` (the ATS-API fetch path,
  `--dump-jd` / `dump_jd()`)
- `.agents/skills/job-search/SKILL.md` (references `company_roles.py` today only
  for the single-company location re-check use case, not JD recovery)

This is a distinct fallback from the JD-fetch-verbatim-unavailable convention
(scraper-extracted text + provenance note, tracked separately) — that convention
is for when *no* fetch of any kind succeeds (e.g. an HTTP 403); this task is about
recovering the actual verbatim JD text via a different, already-working fetch
path when the naive page fetch is JS-rendered.

## Definition of done

- `.agents/skills/job-search/reference.md` (or `SKILL.md`, wherever the routine
  JD-fetch guidance lives) states: when a fetched JD page is JS-rendered or
  otherwise unusable and the company's ATS type is known/discoverable, re-fetch
  the JD text via `company_roles.py`'s ATS-API path instead of accepting a
  partial/garbled scrape.
- The documentation names which ATS types this applies to (the four already
  listed under "Supported ATS APIs").
- A reviewer can find this guidance by reading the reference tier alone, without
  needing this task file or the benchmark rows that surfaced it.
