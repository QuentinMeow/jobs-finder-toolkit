# Document the JD-fetch-verbatim-unavailable fallback convention

- **Status**: todo
- **Priority**: P2
- **Area**: job-search
- **Source**: `evals/results/stage1-benchmark-20260720.md:61-63`

## Goal

Write down, in the job-search skill's instruction files, the convention a search
agent already improvised once: when a verbatim JD re-fetch fails outright (e.g.
HTTP 403 from the source), save the aggregator/scraper-extracted description
instead, with an explicit provenance note marking it as non-verbatim.

## Context

In the Stage-1 pinned benchmark row, the search agent could not re-fetch one JD
verbatim — the aggregator's source returned HTTP 403 — and fell back to saving
the scraper-extracted description it already had from the discovery pass, adding
a provenance note rather than silently presenting it as the verbatim page text.
The row's own assessment: "acceptable fallback, worth a documented convention."

This is distinct from the separately-tracked ATS-API JD-fetch fallback task
(recovering a *verbatim* JD via a company's ATS API when the naive page fetch is
JS-rendered) — checked directly against this repo's docs and confirmed the two
don't overlap: the ATS-API path is a way to still get verbatim text via a
different fetch route, while this convention is for the harder case where no
fetch route succeeds at all and the agent has to fall back to already-scraped,
non-verbatim text. Kept as two separate tasks; if the ATS-API documentation task
lands first, this task should still note the ATS-API path as the fallback to try
*before* reaching for scraper-extracted text.

Today, neither `.agents/skills/job-search/SKILL.md` nor `reference.md` documents
what to do when a verbatim JD fetch fails outright (checked directly — no mention
of "403", "provenance", or "scraper-extracted" as a JD-save fallback in either
file). `SKILL.md` currently only describes the happy path: "Fetch a candidate's
JD text **verbatim** (no summarization)" via `fetch_jd.py`, and `handoff.py`
saves `source/JD-<job title>.md` the same way.

Relevant files:
- `.agents/skills/job-search/SKILL.md` (the verbatim-JD-fetch guidance to extend)
- `.agents/skills/job-search/scripts/fetch_jd.py` (the fetch that can fail with a
  non-200 status)
- `.agents/skills/job-search/scripts/handoff.py` (saves the JD file during
  scaffolding; already handles a `save_jd()` failure by printing a warning and
  leaving the file for manual save — the natural place to describe the
  fallback-to-scraped-text option instead)

## Definition of done

- `.agents/skills/job-search/SKILL.md` (or `reference.md`, wherever JD-fetch
  guidance lives) documents: when a verbatim JD re-fetch fails, save the
  best-available scraper/aggregator-extracted description text instead of
  leaving the JD file empty, and mark the saved file with an explicit provenance
  note (e.g. a leading comment or header line stating it's non-verbatim and why).
- The documented convention is discoverable from `handoff.py`'s existing
  `save_jd()` failure message or its neighboring instructions, not just buried in
  a benchmark result file.
