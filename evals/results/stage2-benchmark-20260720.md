# Stage 2 benchmark — pinned scenario v1.1 (reference vs post-tiering)

| Field | Value |
|-------|-------|
| Scenario | `design/token-usage-modes/benchmark-scenario.md` v1.1 (pipeline-state-neutral) |
| Reference head | `627a393` (Stage-1 state, pre-tiering), worktree checkout |
| Post-Stage-2 heads | search @ `bbd62a4`; draft @ `e2f7a82` (delta = card-builder story-bank fix, scripts+test only — instruction stack byte-identical) |
| Model | `claude-sonnet-5` subagents, per the model-pinned protocol |
| Date | 2026-07-20 |
| Invalidated attempt | one v1.0 reference search (112,305 tok) hit zero eligible candidates purely from same-day pipeline state; v1.1 pinned neutrality flags; tokens excluded from rows per the scenario's attempt rule |

## Measured rows

| Leg | Reference (Stage 1) | Post-Stage-2 | Δ |
|---|---:|---:|---:|
| search | 130,739 tok / 37 calls / ~6.2 min | 120,446 tok / 48 calls / ~9.5 min | **−7.9% tok** |
| draft A | 162,958 / 53 / ~12.2 min | 157,854 / 47 / ~12.2 min | **−3.1% tok** |
| draft B | 190,896 / 60 / ~14.7 min | — (see below) | — |
| **total (as-run)** | **484,593 / 150** | 278,300 / 95 | — |
| **total (2-draft normalized)** | **484,593** | **436,154** (search + 2× draft) | **−10.0%** |

**Why post-Stage-2 has one draft:** the pinned 3-day window truthfully contained one
eligible new candidate. Two causes, both recorded: (a) same-day pool depletion — the
reference run had already drafted the window's top candidates, and the pinned
duplicate-exclusion correctly removed them (an inherent asymmetry of running both rows
the same day; future paired rows should run on separate days or the reference should be
re-run first each time); (b) the second handoff this run produced was rejected by the
authoritative drafted-app location gate (`status.py --check-locations` → `other_us`) —
an SF-hybrid role passed the search-time heuristic via the known
hybrid-counts-as-remote scoring branch. The reference search caught the same pattern by
JD text; this run's JD fetch fell back to API text that was silent on workplace. The
mis-handed-off folder was left in place for owner disposition (agents don't move
status folders). Sample size is 1 run per row; treat leg deltas as indicative.

## Where the savings came from (self-audit deltas)

- Boot instruction reads, search leg: contract doc 40,229 → 13,449 B; skill doc
  29,075 → 17,299 B (−55% instruction bytes at boot).
- Boot instruction reads, draft leg: contract doc 40,229 → 13,449 B; skill doc
  37,778 → 24,844 B. The draft leg still chose to read the (now larger) reference
  file in full plus the validator source (~59 KB) — on-demand tiers redirect
  reading but don't prevent a curious agent from opening them; quickstart wording
  could discourage full-file reference reads further.
- Candidate context, draft leg: tailoring card (8.6 KB) read FIRST; full profile
  (12.9 KB) opened only via the listed trigger (JD domain outside card coverage);
  story bank consulted via the card's digest pointer. Card-first bound in both
  benchmark drafting legs and both organic canary builds — 5/5 applicable runs
  since tiering (was 0 uptake before).
- Mechanics held: 1 fetch + 2 zero-network refilters (search); 1 render cycle
  (draft, target 1–2); research at the 2-fetch cap; handoff metadata valid
  (35 applications checked, 0 invalid).

## Quality signal (unchanged or better)

- 3 title-gate false positives (a partner-development role, a legal-counsel role,
  a mislabeled engineering-manager role) rejected by JD-text verification before
  any handoff spend.
- 3 same-day duplicates caught by the folder scan, including one the task prompt
  did not name.
- Draft: check.py PASS on cycle 1 with honest partial-fit framing (the JD's
  must-have stack is Weak-gated for this profile; the letter and notes.md say so
  plainly rather than overclaiming).
- Step 7 ran the one-at-a-time consequence-labeled protocol; 8-skill queue,
  first question posed, stopped.

## Gate decision

Projection was −25% vs the pinned reference; measured is **−10.0% (normalized)**.
That is 15pp off projection — inside the execution plan's ≥ ~25pp pause threshold,
so the plan does not force a pause. The boot tax fell as designed; the residual gap
to projection is mostly (a) the draft leg's discretionary full reads of
reference.md + validator source and (b) verification/fallback work in a hostile
fetch environment (7/7 JD pages JS-rendered this run). **Stage 3 (explicit
token_saving/full modes) remains a maintainer decision** — the measured trend
supports it, and the quickstarts are now the natural place to hang the mode switch.

## Follow-ups surfaced by this row

- Search-time location heuristic: hybrid-counts-as-remote branch produced another
  mis-handoff (see issues #21 and the LESSONS entry); consider making the
  drafted-app location gate (`--check-locations`) a mandatory handoff.py
  post-step so search cannot hand off a folder the pipeline will reject.
- JD fetching: the reference search recovered JS-rendered pages via the
  single-company script's ATS-API path; this run's search did not think to.
  Documenting that fallback in the skill's reference tier would make it reliable.
- Quickstart wording could steer agents away from full-file reads of
  reference.md/validator source on the routine path.
- Card size now exceeds the 8 KB soft ceiling by ~0.4 KB after the story digest
  fix (builder WARNs but proceeds) — acceptable; revisit if the story bank grows.
