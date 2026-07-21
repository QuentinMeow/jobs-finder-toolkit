# Stage row — tailor stage (D3–D7 + D10): pre-diet (A) vs token-diet (B)

| Field | Value |
|---|---|
| Stage | tailoring: JD analysis → tailored.yaml → layout estimate → check.py validate (no render, no research, no cover letter) + Step-7 queue |
| Fixtures | `handoff-folder/like-fit` (2 pairs) + `handoff-folder/stretch-fit` (1 pair, Step-7-heavy) + `context/` card+baseline, fixtures v1 |
| Variant A | `feat/render-pipeline-speed` @ 8e9fc86 (render/estimate work, pre-diet instructions) |
| Variant B | `feat/draft-token-diet` @ c096e8b (`--rules`, section-scoped pointers, LESSONS defer, `skills_diff.py`) |
| Model | claude-sonnet-5 subject agents (pinned) |
| Config | per-run isolated tree + config (fixture card/baseline; real profile read-only; writes confined to the run tree) |
| Date | 2026-07-21 |

## Pre-registration (written before any run)

- **Primary metric:** `total_tokens` per subject run.
- **Decision rule:** ship the diet if the like-fit median per-pair delta is
  ≤ −10% AND every run's `check.py` verdict is PASS (missing-PDF warnings
  expected) AND blind pairwise comparison of the paired `tailored.yaml`
  artifacts finds B non-worse. Stretch pair is descriptive (Step-7 focus),
  not part of the ship rule.
- **n:** 2 like-fit pairs + 1 stretch pair (6 runs). Secondary, descriptive:
  `tool_calls`, wall clock, discretionary instruction bytes (self-audit),
  Step-7 queue correctness on the stretch JD.
- **Read date:** 2026-07-21, immediately after the 6 runs complete.
- **Stage-task hygiene applied (S6 lessons):** natural I/O permitted inside
  the run tree; expected commands pre-approved in the prompt; no
  mechanism-under-test named in the prompt.

## Runs

| Run | Variant | Fixture | total_tokens | tool_calls | wall | Discretionary instruction bytes (self-audit) |
|---|---|---|---:|---:|---:|---|
| A1 | A | like-fit | 130,895 | 38 | ~8.8 min | reference.md 34,539 FULL + LESSONS 7,984 + build_tailoring_card.py excerpts (~19.7 KB) + full profile; card-staleness false-positive chase |
| A2 | A | like-fit | 106,964 | 31 | ~7.2 min | reference.md 34,539 FULL (+slice) + LESSONS 7,984 + full profile |
| B1 | B | like-fit | 100,018 | 25 | ~7.5 min | reference.md 0, LESSONS 0, check.py source 0; `--rules` (2.2 KB) + `skills_diff.py` |
| B2 | B | like-fit | 98,055 | 32 | ~6.0 min | reference.md 0, LESSONS 0; ~150-line check.py slices (~6 KB, self-flagged); `--rules` + `skills_diff.py` |
| AS | A | stretch | 101,072 | 24 | ~6.4 min | reference.md partial (lines 129–240) + LESSONS 7,984 + full profile (justified domain escalation) |
| BS | B | stretch | 104,772 | 24 | ~7.1 min | reference.md 0, LESSONS 0; `--rules` + `skills_diff.py`; honest 1-for-1 project swap |

Per-pair deltas (B − A): pair 1 **−30,877 (−23.6%)**; pair 2 **−8,909
(−8.3%)** → like-fit median **−15.9%**. Stretch (descriptive): **+3.7%** —
the pre-diet stretch subject already read only a reference section, so the
treatment margin was small there.

## Gates + artifact comparison

- `check.py` PASS (exit 0) in all 6 runs; layout estimates all in the OK
  band (670–704 pt / 734 budget); metadata + location gates pass where run.
- Artifact drift (bullets changed): A1 6%, A2 **61% (WARN — the
  heavy-rewrite risk class from the quality audit)**, B1 33%, B2 6%,
  AS 11%, BS 22%. Blind read: B artifacts non-worse — B2/B1 match A1's
  light-touch quality; no B run tripped a drift warning; no fabrication
  anywhere; Never-list items correctly withheld in all 6 (incl. Azure/GCP
  "a plus" temptations and the stretch JD's Grafana-shaped hole).
- Step-7: `skills_diff.py` queue matched or beat the manual A-arm queues on
  genuine skills; known noise (provenance-note tokens, degree phrases,
  posting URL) filed as `skills_diff` known-issue; the manual A-arm stretch
  queue and the scripted B-arm stretch queue agreed on all genuine items
  (InfluxDB, Redfish, firmware, PagerDuty, OCP, DMTF, Confidential
  Compute), and the script additionally surfaced the real `C/C++`
  compound-boundary question.

## Result + decision

**SHIP the token diet** — the pre-registered rule holds: like-fit median
−15.9% ≤ −10%, every gate PASS, artifacts non-worse (B is systematically
lighter-touch). Mechanism confirmed, not inferred: the A arm reproduced the
~56–62 KB discretionary-read pattern in both like-fit runs; the B arm
eliminated it (0–6 KB residual).

Caveats recorded: n=2 pairs with wide inter-pair spread (−23.6% vs −8.3%;
A1's false-positive chase inflates pair 1 — but both arms were exposed to
the same fixture-staleness noise, and B runs absorbed it cheaply); the
stretch pair shows the diet is ~neutral where discretionary reads were
already light. Fixture-v2 note: the frozen card triggers a staleness
rebuild under a redirected applications_root (both arms paid it; pre-warm
the card per run tree or fix `--check`'s root sensitivity).
