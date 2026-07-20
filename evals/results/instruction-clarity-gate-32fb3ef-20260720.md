# Eval result — instruction-clarity canary gate (adversarial-review fixes)

| Field | Value |
|-------|-------|
| Skills | `resume-writer` (7 canaries) + `job-search` (5) + `application-tracker` (4) — 16 affected |
| Run kind | canary gate pre-merge for branch `fix/instruction-clarity-adversarial-20260720` (`32fb3ef` — "Instruction clarity fixes from adversarial review"). Diff touches `resume-writer/{SKILL.md,LESSONS.md,reference.md}`, `job-search/SKILL.md`, `application-tracker/SKILL.md`, `AGENTS.md`, `docs/AGENTS-ANNEX.md` — all three suites genuinely affected. |
| Git SHA | `32fb3ef` (branch head); each runnable canary run in its own detached worktree at `32fb3ef` |
| Model version | runners `claude-sonnet-5` (one FRESH subagent session per canary); orchestrator/judge Opus (never delegates verdicts) |
| Config mode | examples fallback; `JOBHUNT_CONFIG` pinned per runner to that worktree's `config.example.yaml` (`generation.mode: token_saving`); no private overlay |
| Fixtures | issue #16 protocol — runner worktrees isolated under `/tmp/jobs-gate-32fb3ef/<id>` (up-tree of the primary repo's real `config.yaml`/`private/` deliberately avoided); runners read instruction files directly (Skill tool forbidden), `evals/`+`docs/design/` out of bounds. `at-enrich` fixture: `required_yoe`/`salary_range` blanked to placeholders. |
| Date | 2026-07-20 |
| Judge | manual — orchestrator per `evals/rubrics/judging.md`, all-bullets-strict, failure-modes auto-fail; artifacts inspected + every zero-write claim verified via each worktree's `git status` |

## ⚠ Gate is INCOMPLETE — environment blockers (8 of 16 canaries not runnable here)

This machine cannot exercise 8 affected canaries, so this gate does **not** clear the
eval-gated-merge rule for the full instruction-clarity diff. It records what could be
verified and hands the rest to the orchestrating session (no instruction file was edited).

- **No DOCX→PDF renderer.** `soffice`/LibreOffice ABSENT and `docx2pdf` ABSENT (MS Word alone
  cannot be driven without it, and would trigger GUI automation). The 3 render-dependent
  resume-writer canaries require producing + page-verifying a PDF (`check.py` post-render page
  count is their authoritative gate) — impossible here. → BLOCKED-RENDER.
- **No-network rule.** The orchestrating session forbids job-board network fetches. All 5
  job-search canaries require a live Stage-1 board/aggregator fetch. → BLOCKED-NETWORK.
  (Job-search cannot be carried forward from a prior gate either: this diff edits
  `job-search/SKILL.md` + `AGENTS.md`, so its `446a954` 5/5 no longer bounds head behavior.)

## Per-canary results

`total_tokens` here = runner **subagent** token total (input+output) from the Agent-tool
usage meter; `wall_clock_s` = runner duration; `tool_calls` = runner tool uses. The Phase-3
metrics hook (`logs/metrics.jsonl` / `report.py --by-sha`) is NOT wired in these worktrees, so
these are a different instrument than prior gates' hook-logged `total_tokens` — comparable only
directionally. Efficiency is recorded, not scored; no blow-ups observed.

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------|--------------|--------------|------------|-------|
| `rw-tailor-single-posting` | — BLOCKED-RENDER | — | — | — | Requires full deliverables incl. root PDF + `check.py` one-page verify; no renderer. Also the only canary exercising the AGENTS.md card-first change → that change stays ungated. |
| `rw-layout-budget-verdict` | **1** | 67,950 | 120 | 12 | Ran `estimate_layout.py` (no render); OVERFLOW **739pt / 734pt budget** (independently reproduced by judge); tied to ~734 budget + ≤~715 target; trims longest bullets, no project drop, no filler; **states check.py post-render page count is the authoritative gate (part-2 verdict — the recurring flake, correct here)**; new OK band lower-bound (~660–715) honored. Zero writes (git clean). |
| `rw-multi-experience-baseline` | — BLOCKED-RENDER | — | — | — | Rubric requires "every employer appears in the one-page PDF"; no renderer. |
| `rw-bundled-txt-structure` | — BLOCKED-RENDER | — | — | — | Rubric bullet 4 requires rendering the cover letter to `.docx`+`.pdf`; no renderer. Note: this is the canary covering the new cover-letter word-band SKILL/reference edit → that edit's live behavior stays unverified. |
| `rw-skill-gating-weak-never` | **1** | 60,054 | 94 | 14 | Caught false premise (example JD names neither term — only generic "messaging/queueing"); **Rust = Never**, declined "even if the JD asked"; **Kafka = Weak**, refused (no literal JD mention); confirmed `check.py` would hard-fail either; no fabrication; zero resume edits (git clean). |
| `rw-skill-category-question-batch` | **1** | 69,179 | 69 | 10 | ONE batched interaction, **exactly two single-select questions** (one per skill, not serial/combined/multi-select); three consequence labels **verbatim in mandated order** (Never / Weak or Selective / Approved), **Other last**; "Weak or Selective" used as user-facing alias, stored category not renamed; waited for user; zero writes (git clean). |
| `rw-duplicate-preflight` | **1** | 65,431 | 112 | 18 | Pre-flight scanned live status folders (not just log), **detected the existing `example-corp-…` drafted folder** (exact company+role match), hard-stopped, offered refresh instead of a duplicate slug; read-only re-validation only; zero writes (git clean). |
| `at-pipeline-health` | **1** | 51,281 | 70 | 10 | Ran `status.py`; **status read from the folder** (`6_drafted`), not any meta field; funnel summarized, `next_action` surfaced; honestly flagged the single row as the fictional demo; no folder moved (git clean). |
| `at-validate-drafted-metadata` | **1** | 49,795 | 55 | 11 | `status.py --check-metadata` → `Checked 1; 0 invalid`; confirmed default validates **drafted only** (other folders untouched); schema-v3 / `jobs:` list / structured-field shape explained; zero writes (git clean). |
| `at-enrich-insert-only` | **1** | 70,872 | 134 | 25 | `status.py --enrich-metadata`; **insert-only**: `required_yoe` filled from JD "5+ years" → `min 5 / max null / source job_description`; **`salary_range` stays null** (JD has no pay — refused the company-levels cache band, no fabrication); **`job_level` preserved** (manual value untouched); comment + block formatting survived. Result byte-matches judge's independent ground-truth run. Only `meta.yaml` changed. |
| `at-status-move-on-request` | **1** | 66,571 | 74 | 12 | `status.py --update … applied` **moved the folder** `6_drafted → 5_applied` (status = folder); contents intact; **no `status:` field added** to meta; reminded user to run `--sync-log` so job-search skips the applied posting; acted only on explicit request. Move verified on disk. |
| `js-core-shortlist` | — BLOCKED-NETWORK | — | — | — | Requires live Stage-1 board/aggregator fetch. |
| `js-visa-require-positive` | — BLOCKED-NETWORK | — | — | — | Requires live search + JD-text fetch. |
| `js-mts-not-staff` | — BLOCKED-NETWORK | — | — | — | Requires live `search_jobs.py` run. |
| `js-recency-vs-research-window` | — BLOCKED-NETWORK | — | — | — | Requires live `--max-age-days 3` search. |
| `js-single-company-location-verdict` | — BLOCKED-NETWORK | — | — | — | Requires live `company_roles.py --match-only`. Only canary exercising the corrected `location_policy()` accessor keys (`metro`/`allow_us_remote`) → that job-search edit stays ungated. |

Runnable set: **8/8 PASS**. Not run: **8 BLOCKED** (3 render, 5 network).

## Diff-change → coverage map

| Instruction change (`32fb3ef`) | Covering canary | Status |
|--------------------------------|-----------------|--------|
| Verdict-band OK lower-bound `~660–715` (LESSONS.md + SKILL.md) | `rw-layout-budget-verdict` | PASS — no regression |
| Step-7 batched consequence-label protocol (unchanged, adjacent) | `rw-skill-category-question-batch` | PASS |
| Three-list skill gate (unchanged, adjacent) | `rw-skill-gating-weak-never` | PASS |
| Pre-flight duplicate guard (adjacent to reworded blacklist bullet) | `rw-duplicate-preflight` | PASS (no actual blacklisted company exercised) |
| Blacklist → merged-registry (`registry.is_blacklisted`) rewrite (SKILL.md) | — | UNGATED (no canary drives a blacklisted company) |
| Cover-letter word-band instruction (SKILL.md + reference.md) | `rw-bundled-txt-structure` | UNGATED — render-blocked |
| AGENTS.md "read tailoring card first" (card-first) | `rw-tailor-single-posting` | UNGATED — render-blocked |
| `job-search` `location_policy()` accessor correction + "never self-escalate to full" | `js-single-company-location-verdict`, `js-core-shortlist` | UNGATED — network-blocked |
| `application-tracker` bundled `.txt` naming `_<job title>` clarification | (no canary asserts `.txt` naming) | UNGATED — at suite otherwise green |
| AGENTS-ANNEX: outlook added to PUBLIC list, profile-dir/log path rows | — | doc-only, no behavior canary |

## Verdict

- **Gate: INCOMPLETE — does NOT authorize merge of the full diff.** 8/8 runnable canaries
  PASS with zero behavior regressions on artifact evidence; but 8 affected canaries could not
  be exercised (no renderer; no-network rule), leaving the AGENTS.md card-first change, the
  cover-letter word-band edit, the merged-registry blacklist rewrite, and **all** job-search
  behavior (incl. the `location_policy()` accessor correction) unverified.
- **application-tracker suite: PASS (4/4).** The `.txt` naming clarification and shared
  AGENTS.md/annex edits hold at-side behavior — folder-as-status, drafted-only validation,
  insert-only enrichment (no fabrication, manual values preserved), request-gated moves.
- **resume-writer: partial (4/7).** The behavior-bearing edits that ARE covered — verdict-band
  lower-bound, three-list gate, Step-7 batch, duplicate pre-flight — pass clean. The recurring
  check.py-authority verbalization flake (0/? in past gates as a trailing bullet; fixed
  structurally into the two-part verdict at `8d4c06c`) held again here in `rw-layout`.
- **job-search: not gated (0/5 run).** Cannot be carried forward — the diff edits its SKILL.md
  and AGENTS.md.
- **No instruction file edited** (per the no-edit-on-block rule). Efficiency within family of
  prior gates; no blow-ups.

## Handoff to the orchestrating session (decision needed)

Re-run the 8 blocked canaries in a capable environment before merging the instruction-clarity
diff:
1. **3 render canaries** (`rw-tailor-single-posting`, `rw-bundled-txt-structure`,
   `rw-multi-experience-baseline`) on a host with LibreOffice (or `docx2pdf`).
2. **5 job-search canaries** where a live Stage-1 fetch is sanctioned (the no-network rule
   here forbade them).
Both sets are needed to close coverage on the card-first, cover-letter word-band,
merged-registry-blacklist, and `location_policy()` changes.
