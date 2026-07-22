# Confirmation row — full pinned scenario v1.2 on the round's integrated head

| Field | Value |
|---|---|
| Scenario | `docs/design/token-usage-modes/benchmark-scenario.md` v1.2 (isolated benchmark config; writes never touch the real pipeline) |
| Head | `integration/round-20260721` @ 2d9bbec = main + #36 + #37 + #38 + #40 + #39 + #41 (handoff location gate, JD digest @ fetch, render parallel-PDF + estimate gate + flake retry, draft-leg token diet, process folders, stage-benchmark scaffolding) |
| Reference | Stage-3 row 452,673 tok / 205 calls (search 121,391/9.1 min; drafts 169,243/13.6 min + 162,039/13.4 min), `evals/results/stage3-benchmark-20260720.md`; pinned program reference 484,593 |
| Model | claude-sonnet-5 subject agents (pinned) |
| Config | `JOBHUNT_CONFIG=private/config.benchmark.yaml`; snapshot cache cleared (cold); benchmark tree holds 7 prior drafts (duplicate gate active by design) |
| Date | 2026-07-21 |

## Pre-registration (written before any run)

- **Primary metric:** summed `total_tokens` across the three legs (1 search
  + 2 drafts).
- **Decision rule:** the round confirms if the sum is ≤ 407,000 (Stage-3
  −10%) AND every hard gate passes (blacklist/log preflight, location gate,
  `check.py` PASS incl. render, metadata valid) AND the two drafted
  applications score non-worse than the frozen 7-draft baseline on the
  artifact-quality rubric (spot-scored dimensions D2 traceability, D4
  cover-letter specificity, D5 honest fit).
- **Secondary, descriptive:** per-leg wall clock (time target: draft legs
  materially under the 13.5-min reference; render block expected ~halved),
  tool calls, self-audit discretionary-read bytes, failure/retry telemetry.
- **Caveat noted up front:** JD-difficulty mix is uncontrolled (same-day
  posting pool + 7-draft duplicate blocking); interpret against the fit-mix
  actually drawn, as the Stage-3 row did.
- **Read date:** 2026-07-21, immediately after the three legs complete.

## Legs

**Search leg — recorded, INVALIDATED for comparison (zero-eligible day).**
149,958 tok / 50 calls / ~13 min. The 2h→1d→3d widening yielded 10
candidates: 6 exact-URL duplicates of the benchmark tree's own 7 drafts
(folder gate working as designed) and 4 legitimate rejections at JD
verification (a people-management role, two wrong-metro hybrids — one also
10+ YOE over the profile cap, one sales/BD role matching only on a title
substring). The subject refused to bend any gate, made zero handoffs, and
filed the outcome as a self-contained decision doc
(`private/message-queue/needs-human/decisions/benchmark-search-leg-20260721-zero-eligible.md`).
Precedent: the scenario doc's own v1 attempt was invalidated identically;
tokens do not enter a comparison row. Two structural findings: (1) the
benchmark tree depletes its own future candidate pools — a scenario-v1.3 /
fixtures-v2 question; (2) all 4 JS-rendered recoveries used
`company_roles.py --jd`, which has NO digest mode — the fetch-time digest
lever does not cover the ATS-API path (task filed).

**Draft legs — run from the pinned fixture handoffs** (fresh full-flow run
trees; NOT the pre-existing completed drafts): D1 = the stretch NVIDIA
telemetry JD — the SAME JD as Stage-3 draft A (169,243 tok / 13.6 min),
giving a direct same-JD cross-round pair; D2 = the like-fit Snowflake JD
(no exact prior comparator; Stage-2 normalized row is the like-fit
reference class).

| Leg | Tokens | Tool calls | Wall clock | Render cycles | Notes |
|---|---:|---:|---:|---:|---|
| search | (149,958) | (50) | (~13 min) | — | INVALIDATED for comparison — zero-eligible day, see above; tokens excluded from the row per scenario precedent |
| D1 stretch (same JD as Stage-3 draft A) | 119,480 | 47 | ~10.0 min | 2 (2nd voluntary sparse-bottom polish, NOT failure recovery) | check.py PASS; 1 research fetch grounding real GH200 facts; honest gap disclosure in the letter; profile escalation correctly not triggered; `--rules` + `skills_diff` used; zero validator-source or reference.md full reads |
| D2 like-fit | 114,839 | 40 | ~9.7 min | **1** | check.py PASS; 78.7 KB TOTAL file ingestion incl. boot; 2 research fetches (thin yields: JS-shell header + 404) |
| **draft total** | **234,319** | **87** | ~19.7 min | | **vs Stage-3 draft legs 331,282 / 139 calls / 27.0 min → −29.3% tokens, −27% wall clock, −37% tool calls** |

Same-JD matched pair (the cleanest cross-round comparison in the program):
NVIDIA telemetry stretch draft — Stage-3: 169,243 tok / 63 calls / 13.6 min /
2 cycles (one lost to a since-fixed data bug); this round: 119,480 / 47 /
10.0 min / 2 cycles (second voluntary). **−29.4% tokens, −26% wall clock.**

Draft-leg failure telemetry: zero permission blocks, zero meaningless
retries; 4 single-shot adaptive retries in D1 (arg-form/interpreter fixes,
each resolved on first correction) + 1 in D2 (same `--check-metadata`
arg-form slip — a recurring stumble worth a usage-line fix in the script's
error message).

## Gates + quality spot-scores

All hard gates PASS on both draft legs (check.py 0 FAIL incl. render + PDF
gates; metadata v4 ok; location match; no Never token; cover letters pass
structure gates). Blind rubric grading (independent grader, all 7
dimensions, same-JD frozen comparators):

- D1 NVIDIA telemetry (stretch): **1.86 avg — EQUAL to the prior same-JD
  row on all 7 dimensions.** Honest gap disclosure verified verbatim;
  cover letter grounded in 3+ accurate company facts.
- D2 Snowflake (like-fit): **2.00 avg — EQUAL on all 7.** Despite thin
  research yields, the letter carries 3+ verifiable JD/company specifics.
- Defects: 4, all LOW/cosmetic (baseline header comment carried into
  tailored.yaml ×2 — the pre-existing systemic class; one coverable Weak
  term omitted; soft continuity phrasing; near-limit bullet WARN). None
  score-affecting; both drafts cleaner on structural/skill compliance than
  most of the original cohort (frozen-baseline setup eliminates the old
  token-drift FAILs).

## Result + decision

**The round CONFIRMS on the draft side, with the search side deferred.**

- The pre-registered 3-leg-sum rule is NOT evaluable as registered: the
  search leg hit a legitimate zero-eligible day and is invalidated per the
  scenario's own precedent. No number is claimed for it.
- The evaluable evidence is decisive: draft legs −29.3% tokens / −27% wall
  clock / −37% tool calls vs the Stage-3 reference legs, INCLUDING a
  same-JD matched pair at −29.4%, with blind per-dimension quality EQUAL
  and every hard gate passing. Cumulative vs the program's pinned
  reference (484,593 for search + 2 drafts), the draft-leg share
  (331,282 → 234,319) alone moves the program total to roughly −20% even
  with a flat search leg.
- Search-side levers carry live behavioral evidence (auto location gate
  exercised in rejections; digest canaries 5/5) but no clean comparison
  row yet — deferred to a fresh-pool day on fixtures v2
  (`tasks/0_backlog/2026-07-21-stage-fixtures-v2/task.md`), together with the benchmark-tree
  pool-depletion question
  (`private/message-queue/needs-human/decisions/benchmark-search-leg-20260721-zero-eligible.md`).
- Ship decision: PR stack #38→#40 and #39→#41 stands as merge-ready on
  this evidence; the stage rows (`stage-tailor-20260721.md` ship verdict,
  `stage-s6-verification-20260721.md` no-ship-for-saved-files verdict)
  record the per-lever detail.
