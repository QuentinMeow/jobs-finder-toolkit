# Build stage-benchmark fixtures v2: raw pages, provenance-led files, natural-flow tasks

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

- `private/evals/fixtures/v2/` with the added raw-page + provenance-led
  cases, MANIFEST updated (provenance, SHA-256, replay commands).
- A pinned stage-task prompt template in
  `evals/protocols/stage-benchmarks.md` (or a new tasks section)
  encoding lessons 3's two rules.
- One re-run of the S6 row on v2 fixtures with the fetch-time flow allowed,
  recorded in `evals/results/`.

## 2026-07-31 — one stale coordinate corrected

The definition of done said `private/benchmark/fixtures/v2/`. **`private/benchmark/` does not
exist**; the tree is `private/evals/fixtures/v1/` (7 files, 4,330–9,684 bytes — the claim's
"4.3–9.7 KB" holds to the decimal). Commit `7c525e3` re-pointed every literal at the new `evals/`
layout and touched this very file, but changed only its protocol-doc line and left the dead
fixture path in the DoD. The path above is now corrected, and the same dead path was corrected in
`evals/results/TEMPLATE.md`, which copies itself into every future run record.

**Verify-with**: `ls -d private/evals/fixtures/v1/jd-set/` · `grep -rn 'private/benchmark' .`

Nothing else in this task changed: `evals/protocols/stage-benchmarks.md` still exists with zero
code fences, so neither of lesson 3's rules is pinned anywhere, and the S6 re-run still has not
happened.
