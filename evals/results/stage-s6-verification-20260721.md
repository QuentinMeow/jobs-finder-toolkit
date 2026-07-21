# Stage row — S6 JD verification: full-read (A) vs digest (B)

| Field | Value |
|---|---|
| Stage | S6 JD-text verification (stage-map §A.1; boundary: verdict table produced, no writes) |
| Fixture | `private/benchmark/fixtures/v1/jd-set/` (6 clean JDs + expected.yaml; JS-shell entries absent in v1) |
| Variant A | `fix/search-hardening` @ 53fba4d (pre-digest) |
| Variant B | `feat/jd-digest` @ 3346aac (`--digest` + SKILL Step-4 steering) |
| Model | claude-sonnet-5 subject agents (pinned) |
| Config | `JOBHUNT_CONFIG=private/config.benchmark.yaml` (read-only for this stage; matches expected.yaml ground truth) |
| Date | 2026-07-21 |

## Pre-registration (written before any B run)

- **Primary metric:** `total_tokens` per subject run.
- **Decision rule:** ship the digest if the median per-pair token delta is
  ≤ −15% AND zero gate-verdict errors vs `expected.yaml` in any B run
  (the akamai row is recorded `uncertain`; either verdict is accepted iff
  the subject surfaces the hybrid-signal ambiguity).
- **n:** 2 matched pairs (4 runs). Secondary, descriptive: `tool_calls`,
  wall clock, bytes of JD content read (self-audit).
- **Read date:** 2026-07-21, immediately after the 4 runs complete.

## Runs

| Run | Variant | total_tokens | tool_calls | wall clock | JD bytes read | Notes |
|---|---|---:|---:|---:|---:|---|
| A1 | A | 87,384 | 20 | ~4.0 min | 37,805 (all 6, full) | also full-read vendored `location.py` (12.7 KB) |
| A2 | A | 96,869 | 23 | ~5.8 min | 37,805 (all 6, full) | partial reference.md section reads |
| B1 | B | 102,086 | 27 | ~4.2 min | 37,805 (all 6, full — escalated) | ranged-read digest source; built digests in-process; digests ambiguous on extracted-text fixtures → full-read escalation |
| B2 | B | 108,361 | 29 | ~9.4 min | 37,805 (all 6, full — escalated) | full-read `fetch_jd.py` (27.8 KB); repeated auto-mode classifier blocks on URL-bearing CLI calls (retry churn); digest title mis-fired on a provenance-note-led file |

Per-pair deltas (B − A, same slot): pair 1 **+14,702 (+16.8%)**; pair 2
**+11,492 (+11.9%)**. Median **+14.3%** vs the pre-registered ship bar of
≤ −15%.

## Verdict-accuracy gate

Zero hard verdict errors in all four runs. All runs: Scale AI + Snowflake
`match` (metro), Grafana `match` (us_remote), Akamai `review`/uncertain with
the hybrid ambiguity surfaced (accepted per pre-registration). A2 deviated
conservatively on the two structured-field `US, Remote` postings (`review`
instead of `match`, demanding body-prose corroboration) — surfaced, not
wrong; noted as same-arm judgment variance. B2 correctly detected and
manually overrode the digest title mis-extraction.

## Result + decision

**Do NOT ship digest-first steering for already-saved JDs** (decision rule
failed decisively). The digest remains scoped to **fetch time**, where the
5/5 canary gate on `feat/jd-digest` showed it working on live raw pages
(a subject rejected a foreign role from the ~2 KB digest without opening the
10.7 KB JD, zero missed gate signals) and where it prints for free with the
fetch that must happen anyway.

Why B lost here (evidence in the run notes): (1) first-encounter reads of the
digest implementation; (2) the stage task's no-write constraint + the
auto-mode permission classifier blocking URL-bearing CLI invocations forced
improvised in-process calls and retries — measurement contamination that
inflates B, but even net of it B could not reach −15%; (3) the fixture JDs
are already-extracted text (4.3–9.7 KB, not raw ~13 KB pages), so the
digest's savings ceiling is small and its extraction heuristics (H1 title)
mis-fire on extraction artifacts; (4) ambiguous digests correctly triggered
the full-read escape hatch — quality held, cost doubled.

**Amendments shipped to `feat/jd-digest` from this row:** (1) SKILL Step-4
scoped: digest-verify at fetch time; an already-saved JD is read directly;
(2) digest title extraction skips the documented non-verbatim provenance
header (a production case — PR #38's fallback convention — not fixture
noise), with a regression test.

**Fixture/protocol lessons (for v2):** the jd-set must include raw fetched
pages (not only extracted text) and provenance-led saved files; a stage task
must permit the natural I/O of the mechanism under test (the no-write
constraint distorted arm B); pre-approve the subject's expected CLI calls so
permission-classifier blocks don't contaminate measured runs.
