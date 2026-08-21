# Two copies of one requisition still split when the bodies are only NEARLY identical

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: GH #281 comments; the 2026-08-20 `fix/filter-pipeline-reports` branch
  collapsed the identical-after-normalization case and left the near-identical one
- **Claimed-by**:

## Goal

Two postings that are the same job with a few words of difference are grouped like the
byte-identical ones, instead of each taking a shortlist slot.

## Context

`skills/job-search/scripts/search_jobs.py` now collapses postings whose JD bodies match
after normalization: `body_fingerprint` lowercases, strips every non-alphanumeric
character and hashes, so case, whitespace, dash typography, punctuation and heading
markup no longer split one requisition. Bodies under `MIN_BODY_FINGERPRINT_CHARS` (400
normalized characters) are never an identity, so stubs cannot fuse. The survivor carries
the collapsed rows' employer, title and URL on `duplicate_sources`, and the report's
`## Duplicate JD bodies` section prints every link.

That is exact matching, and one reported shape is not exact. GH #281 names a pair whose
bodies are 6,225 and 6,300 characters and describe the same streaming/durability role
under two employer names — the same job with edits, not the same text. Equality cannot
see it.

What a fix has to respect:

- **Cost.** A filter run handles up to ~15k postings and roughly 90 MB of JD text (GH
  #292). Shingling every body pairwise is not affordable; a bottom-k / MinHash sketch
  with a bucketing key, or a length-bucketed cheap prefilter, is the shape that fits.
  Measure before and after against a 15k-row corpus — the current whole-pipeline cost on
  that size is single-digit seconds.
- **The asymmetry.** Wrongly splitting one requisition costs a shortlist slot and is
  visible. Wrongly FUSING two different openings loses a real job and is invisible. A
  similarity threshold has to fall on the safe side, and the existing
  `duplicate_sources` provenance must keep carrying every collapsed row's URL.
- **The floor is not just length.** Some employers publish one boilerplate description
  across genuinely different reqs; the 400-character floor does not catch a long
  boilerplate. A similarity pass needs its own answer for that, or it will fuse a
  company's whole board.

## Definition of done

- Two postings whose bodies differ by a small edit but describe one requisition are
  grouped, with both URLs preserved, under fictional JD text.
- Two genuinely different openings sharing a long boilerplate body are NOT grouped.
- A benchmark shows the added cost over a ~15k-row corpus and states it in the task's
  verification record.
- `python automation/gates/run_gates.py --impact-from origin/main` green.
