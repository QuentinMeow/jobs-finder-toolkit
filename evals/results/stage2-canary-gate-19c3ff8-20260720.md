# Eval result — Stage-2 combined gate (instruction tiering)

| Field | Value |
|-------|-------|
| Skills | `resume-writer` (6 canaries) + `job-search` (5 canaries) |
| Run kind | combined-state gate pre-merge: quickstart-first SKILL.md tiering (both skills) + AGENTS.md core/annex split + outlook-email-assistant additions ported (from PR #19) |
| Git SHA | 10 canaries at `c81032a`; `rw-layout-budget-verdict` re-run at `19c3ff8` (see delta note) |
| Model version | runners `claude-sonnet-5` (one fresh subagent session per canary) |
| Config mode | examples fallback (`JOBHUNT_CONFIG` pinned to each worktree's `config.example.yaml`; no private overlay) |
| Fixtures | issue #16 protocol — produce-artifact canaries ran with the to-be-produced artifacts stripped via local setup commits |
| Date | 2026-07-20 |
| Judge | manual — orchestrator per `evals/rubrics/judging.md`, artifacts inspected (worktree `git status` verified for every zero-write claim) |

## Per-canary results

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------|--------------|--------------|------------|-------|
| `rw-tailor-single-posting` | 1 | 154,045 | 645 | 59 | Full app; **built the missing tailoring card first and tailored from card + baseline (card-first bound)**; baseline-copy start; self-caught + reverted an untraceable over-claim; justified backup swap; estimate TIGHT→trim→OK, 1 render cycle, check.py all-pass; mentoring gap honestly refused; Step 7 clean. |
| `rw-layout-budget-verdict` | 0 → **1 (re-run)** | 78,104 / 65,141 | 313 / 164 | 27 / 22 | First run: bands/budget/simulate-first all correct (739→704pt in scratch, zero writes) but the user-facing verdict omitted "check.py is the authoritative gate" → FAIL (all-bullets-strict). Fixed by a one-clause protocol strengthening (`19c3ff8`); re-run states it verbatim → PASS. |
| `rw-bundled-txt-structure` | 1 | 99,675 | 371 | 42 | Three `===` sections; contact→salutation, no subject; paras 96/139 words, 274-word body, check_cover_letter PASS; pypdf page verify; built missing card organically; JD nice-to-have without profile backing omitted. |
| `rw-skill-gating-weak-never` | 1 | 60,046 | 142 | 15 | False premise caught (JD names neither term); Rust hard-blocked (Never, "even if the JD asked"); Kafka refused (Weak, no JD mention); zero edits (verified); cross-read check.py to confirm gate semantics. |
| `rw-skill-category-question-consequences` | 1 | 76,525 | 111 | 16 | One question; three consequence labels byte-identical, in order, Other last; stopped without categorizing; followed core→annex §12 pointer on demand (annex discoverability works). |
| `rw-duplicate-preflight` | 1 | 52,910 | 86 | 11 | Folder-scan detection (not just log), zero writes (verified), refused duplicate slug, offered in-place refresh. |
| `js-core-shortlist` | 1 | 78,363 | 226 | 18 | Real Stage-1 run (11,370 postings→40 matches); discoveries file with source+url on all 40 rows; ranked presentation with level/YOE/visa caveats; handoff offered, no tailoring. |
| `js-visa-require-positive` | 1 | 100,668 | 450 | 40 | Diagnosed issue #15 no-op from scoring.py and made the gate real via scratch profile; JD-verified every company: Anthropic genuine, Walmart + xAI negation false-positives excluded with quotes; advisory-label caveats; no silent widening. Two new negation phrasings recorded on issue #15. |
| `js-mts-not-staff` | 1 | 112,888 | 478 | 31 | 1,277 staff/principal/distinguished hard-excluded; 34 MTS preserved via exclude_neutralize; distinction explained; two borderline rows flagged honestly. Surfaced classify_level MTS gap → issue #22. |
| `js-recency-vs-research-window` | 1 | 62,637 | 158 | 13 | Chose `--max-age-days 3` from phrasing; noted age-off-by-default; separated the 7-day company re-search window explicitly. |
| `js-single-company-location-verdict` | 1 | 71,848 | 202 | 19 | company_roles.py --match-only via registry; no-title-gate caveat; debunked 42/43 heuristic matches ("Distributed" tag on foreign-city-titled sales roles → issue #21), JD-verified the one genuine match. |

Pass rate: **11/11** (one canary required a protocol strengthening + re-run; no behavior regression).

## Head-delta note (`c81032a` → `19c3ff8`)

The re-run head differs from the main gate head by one additive clause in the
resume-writer Step 5.5 verdict bullet ("state this explicitly whenever you give
the user a fit verdict"). No other canary's protected behavior references that
bullet, so the ten `c81032a` runs remain valid for the combined gate; the delta
and this non-interaction analysis are recorded here rather than re-running the
full suite for a one-clause change.

## Verdict

- **Gate: PASS.** The tiered instruction state (job-search 239-line + resume-writer
  376-line quickstart-first SKILL.md files, AGENTS.md 180-line core + annex, with
  the outlook additions ported) holds the full strengthened rubric.
- **Card-first now binds:** two organic `build_tailoring_card.py` runs when the card
  was missing, and the tailor run worked from card + baseline instead of the full
  profile — the previously 0-uptake instruction is exercised in 3/3 applicable runs.
- **Annex discoverability works:** a runner followed the core Guardrail pointer into
  `docs/AGENTS-ANNEX.md` §12 unprompted for the full skill-list rule.
- **Efficiency:** within family of the pre-tiering gate runs (tailor 154k vs 145k —
  this fixture also had no pre-built card; gating 60k vs 43k; category 77k vs 56k;
  duplicate 53k vs 64k; layout 65k vs 63k). No blow-up; boot reads now include the
  annex only when pointed.

## Findings for the toolkit (filed)

- Issue #15 reconfirmed live (+2 new negated-sponsorship phrasings, recorded there).
- Issue #21 (new): "Distributed" ATS location tag on globally-pinned roles yields
  false `us_remote` matches in the location heuristic.
- Issue #22 (new): `classify_level()` bare `\bstaff\b` regex lacks MTS-awareness
  (display-level mislabel only; filtering unaffected).
