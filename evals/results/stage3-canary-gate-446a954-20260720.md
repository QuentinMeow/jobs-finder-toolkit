# Eval result — Stage-3 gate (generation.mode token_saving/full switch)

| Field | Value |
|-------|-------|
| Skills | `resume-writer` (6 canaries) + `job-search` (5 canaries) |
| Run kind | combined-state gate pre-merge: Stage-3 mode switch (config accessor + quickstart mode blocks in both SKILL.mds + AGENTS.md core note; 4 vendored config copies re-synced) |
| Git SHA | `446a954` (branch `stage3/generation-mode`, based on `cb99304`) |
| Model version | runners `claude-sonnet-5` (one fresh subagent session per canary) |
| Config mode | examples fallback (`JOBHUNT_CONFIG` pinned per worktree); `generation.mode: token_saving` present in the example config — several runners read it and reported the mode governing their run |
| Fixtures | issue #16 protocol (produce-artifact canaries with to-be-produced artifacts stripped via local setup commits) |
| Date | 2026-07-20 |
| Judge | manual — orchestrator per `evals/rubrics/judging.md`, artifacts inspected, zero-write claims verified via worktree `git status` |

## Per-canary results

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------|--------------|--------------|------------|-------|
| `rw-tailor-single-posting` | 1 | 160,004 | 589 | 59 | Card built + used as primary context; **mode-aware**: read `generation.mode` → token_saving → 0 research fetches (fictional company, sound), 1 render cycle; estimate OVERFLOW→fix→OK 714pt; check.py PASS; mentoring gap refused; Step 7 legitimately empty. |
| `rw-layout-budget-verdict` | 1 | 67,187 | 157 | 15 | Estimator-first, OVERFLOW from bands tied to 734pt budget + 715 target; per-bullet trim analysis; no-project-drop with reasoning; **states "check.py's post-render page count is still the authoritative gate" verbatim** (the Stage-2 strengthening holds); zero writes. Observation: predicted the post-trim estimate analytically rather than literally applying trims to a copy and re-running — rubric bullets all met; simulate-literalism worth watching. |
| `rw-bundled-txt-structure` | 1 | 110,754 | 348 | 43 | Three `===` sections; no subject; paras 115/122 words, 264-word body; check.py all-pass + pypdf page check; claims traced; card built organically (missing-card trigger). |
| `rw-skill-gating-weak-never` | 1 | 59,650 | 121 | 15 | False premise caught; Rust Never-blocked; Kafka Weak-refused (no JD mention); zero writes (verified); enforcement mechanics confirmed against check.py source. |
| `rw-skill-category-question-consequences` | 1 | 61,496 | 111 | 11 | One question; three consequence labels verbatim in order; Other last; recommendation stated WITHOUT reordering; stopped; zero writes (verified). |
| `rw-duplicate-preflight` | 1 | 52,902 | 85 | 12 | Folder-scan detection, zero writes (verified), refused duplicate slug, offered refresh; read-only re-validation of the existing folder. |
| `js-core-shortlist` | 1 | 62,230 | 122 | 8 | Real Stage-1 run (11,371→40); discoveries file with source+url on all 40 rows (verified); **mode-aware**: token_saving identified as the routine path with hard-gates-unchanged stated; handoff offered, not done. |
| `js-visa-require-positive` | 1 | 108,375 | 490 | 41 | Issue-#15 no-op diagnosed and worked around via profile copy; JD-verified: 2/56 negation false-positives (excluded, quoted), 54 confirmed genuine; advisory caveats; no silent widening. |
| `js-mts-not-staff` | 1 | 94,764 | 303 | 30 | Hard exclude + `exclude_neutralize`; verified on data: 1,290 staff+/principal dropped, 150 MTS survived; distinction explained; borderline rows flagged. |
| `js-recency-vs-research-window` | 1 | 56,691 | 164 | 12 | `--max-age-days 3` chosen from phrasing; age-off-by-default noted; 7-day company window separated; refilter-first follow-up guidance (mode-aware). |
| `js-single-company-location-verdict` | 1 | 101,676 | 252 | 21 | company_roles.py via registry; ~12/43 "Distributed"-tag foreign false-positives debunked with verbatim JD quotes (issue #21 pattern); one genuine match verified; no-title-gate caveat. |

Pass rate: **11/11**.

## Verdict

- **Gate: PASS.** The mode switch integrates cleanly: runners discover `generation.mode`
  from config, treat token_saving as the already-written routine path, and state that
  hard gates never relax. No behavior regression anywhere in the strengthened rubric.
- Efficiency within family of the Stage-2 gate runs; no blow-up.
- Card-first: 2 more organic builds + card-primary tailoring (7/7 applicable runs since tiering).
