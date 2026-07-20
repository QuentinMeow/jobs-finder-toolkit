# Stage 1 benchmark — one search + two drafted applications (measured)

| Field | Value |
|-------|-------|
| Scenario | design-README benchmark: one search ("last 2 hours", widened) + two drafted applications end-to-end, owner's real config |
| Head | post-merge `main` (Stage 0 + Stage 1 + PR #18 all merged) |
| Model | `claude-sonnet-5` subagents (same mid-tier as the 2026-07-20 baseline) |
| Date | 2026-07-20 |
| Baseline compared | 437,273 tokens / 159 tool calls (README table, same date) |

## Per-agent results

| Agent | Tokens | Tool calls | Wall clock | Outcome |
|---|---:|---:|---:|---|
| job search | 158,458 | 64 | ~11.5 min | 3 fetches + **7 zero-network refilters** (baseline: 7 full fetches); 3 mislabeled postings disqualified by JD-text verification before handoff; 2 handoff folders scaffolded, metadata validated |
| drafting A | 195,404 | 67 | ~13.4 min | full app, check.py PASS, **1 render cycle**; honest partial-fit framing; found a real salary-extractor gap (posting range present, extractor needs a "/year" cue) |
| drafting B | 148,101 | 50 | ~11.3 min | full app, check.py PASS, **2 render cycles**; first organic tailoring-card build; Step 7 ran the consequence-labeled one-at-a-time protocol |
| **total** | **501,963** | **181** | — | **+15% vs baseline** (projection was −44%) |

## Analysis — why the total rose while every mechanism worked

**Mechanism wins, individually verified in the run logs:**
- Repeat-fetch pathology dead: the same widening journey = 7 refilters at zero network.
- Render waste dead: 3 cycles → 1–2; the Stage-0 baseline-wording fix produced zero
  blocklist false positives (the one render failure was a legitimate Weak-gate catch).
- Transcription dead: handoff.py wrote schema-v3 metadata that passed the tracker's
  checks untouched; JDs fetched once, verbatim.
- Quality up: three postings the baseline pipeline would have drafted (hybrid mislabeled
  remote; role-fit keyword trap; an explicit sponsorship denial the heuristic labeled
  `unclear`) were rejected before any drafting spend — the new LESSONS entries working.

**Why the total still rose:**
1. **Boot tax untouched (by design until Stage 2):** all three agents read the full
   instruction stack + candidate context (~35–40% of each agent's tokens). Approach 1's
   analysis predicted exactly this; it is now the binding constraint.
2. **Freed budget converted to verification and research, not savings:** JD-text
   verification per candidate, a second-profile market sweep, per-letter product research,
   visual PDF checks, and diagnosis of a real extractor gap. This is the "cheap can also
   mean better" trade — the design says keep the checking; this run shows its price.
3. **Scenario drift:** this run did strictly more product work than the baseline
   (two profiles instead of one, three researched rejections, two validated scaffolds).
   The benchmark scenario needs pinning (profile count, verification depth, deliverables)
   before the next row, or rows measure scope rather than cost.

## Gate decision

Per `docs/design/token-usage-modes/execution-plan.md` (a result ≥ ~25% off projection
pauses the next stage): **Stage 2 is paused pending maintainer review** — which coincides
with the plan's built-in review pause. Recommended agenda for that review: (a) proceed
with Stage 2 instruction tiering (boot tax is now the dominant, measured cost);
(b) pin the benchmark scenario; (c) decide whether card-first context (built once this
run, still not read-first — see the re-gate record's standing observation) should be
promoted in the Stage 2 quickstarts, per the execution plan's original intent.

## Toolkit follow-ups surfaced by this run

- Salary-range extractor misses ranges without an explicit "/year" cue near the number
  (drafting agent filled it manually; noted in that application's notes.md).
- Two uncategorized-skill questions queued for the user by drafting agent B (Step 7,
  one-at-a-time), plus a categorization list in drafting agent A's notes.md.
- The search agent could not re-fetch one JD verbatim (HTTP 403 from the aggregator's
  source); it saved the scraper-extracted description with a provenance note instead —
  acceptable fallback, worth a documented convention.
