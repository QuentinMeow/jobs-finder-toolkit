# Build stage-benchmark fixtures v2: raw pages, provenance-led files, natural-flow tasks

- **Status**: todo
- **Priority**: P1
- **Area**: benchmarks
- **Source**: `evals/results/stage-s6-verification-20260721.md` (fixture/protocol
  lessons section)

## Goal

A v2 fixture set + stage-task template that fix the three external-validity
gaps the first measured stage row exposed, so fetch-time mechanisms can be
benchmarked at their real margin.

## Context

The v1 `jd-set/` holds already-extracted JD text (4.3–9.7 KB) — but the
mechanisms under test (e.g. the fetch-time digest) target raw fetched pages
(~13 KB median, up to 26 KB, plus JS-shell and nav-chrome cases). The v1 S6
row therefore measured a scenario with a near-zero savings ceiling. Three
gaps, all evidenced in the row:

1. **Raw-page fixtures missing** — capture raw fetched page-markdown (before
   extraction), including at least one JS-shell page and one nav-chrome-heavy
   page, alongside the extracted text.
2. **Provenance-led saved files missing** — the documented no-fetch fallback
   convention produces saved JDs with a leading non-verbatim provenance
   header; fixtures must include this case (it broke digest title extraction
   in the row — since fixed, but the case must stay covered).
3. **Stage-task template hygiene** — a stage task must permit the natural
   I/O of the mechanism under test (v1's no-write constraint forced arm B
   into improvisation), and must pre-approve the subject's expected CLI
   calls so permission-classifier blocks don't contaminate measured runs
   (observed: URL-bearing CLI invocations blocked repeatedly in one run).

## Definition of done

- `private/benchmark/fixtures/v2/` with the added raw-page + provenance-led
  cases, MANIFEST updated (provenance, SHA-256, replay commands).
- A pinned stage-task prompt template in
  `docs/design/stage-benchmarks/protocol.md` (or a new tasks section)
  encoding lessons 3's two rules.
- One re-run of the S6 row on v2 fixtures with the fetch-time flow allowed,
  recorded in `evals/results/`.
