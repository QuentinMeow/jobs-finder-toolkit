<!--
Eval-gate run for feat/draft-token-diet (token-diet: check.py --rules, skills_diff.py,
SKILL.md quickstart self-sufficiency + section-scoped pointers, AGENTS.md conventions).
Heavily behavioral instruction change (retiering + Step-7 semantics) -> full 7-canary run.
The instruction-read self-audit per subject is the leading indicator the change worked.
-->
# Eval result — resume-writer

| Field | Value |
|-------|-------|
| Skill | `resume-writer` — full current 7-canary set |
| Canary set | `evals/resume-writer/canaries.yaml` |
| Run kind | regression pre-merge (behavioral edits on `feat/draft-token-diet`, stacked on `feat/render-pipeline-speed`) |
| Git SHA | `5add15c` (all 7 canaries run against it); follow-up steering `edc176c` (see below) |
| Model version | `claude-sonnet-5` (one fresh subject subagent per canary; Agent-tool `sonnet` runner) |
| Config mode | examples fallback + an ISOLATED temp-config tree per canary under gitignored `tmp/canary/<id>/` (temp config points `applications_root`/`discoveries_dir` into the tmp tree, with absolute `profile_md`/`baseline_yaml`/`reference_docx` into the shipped `examples/**`; `rw-multi` uses the multi-experience fixture profile/baseline). No private overlay. |
| Date | `2026-07-21` |
| Judge | manual — orchestrator per `evals/rubrics/judging.md`; every artifact inspected (`check.py`, PDF page counts, employer presence); each subject's `git status --porcelain` self-audit verified empty (all writes landed under gitignored `tmp/`; `examples/**` and `private/**` untouched). |

## Per-canary results

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes (subject = fresh sonnet subagent) |
|-----------|-------------|--------------|--------------|------------|------------------------------------------|
| `rw-tailor-single-posting` | 1 | 113,612 | 482 | 41 | Full path in isolated scaffold: preflight (no dup/blacklist, `Remote (US)` match), built the missing tailoring card (card-missing trigger), `cp` baseline→tailored.yaml with ZERO content edits (all JD skills already Approved; honest mentoring gap named, not fabricated), est 739pt borderline (render.py did not abort), `check.py ✓ all passed (0 warnings)` first cycle, resume + cover both 1 page, Step-7 queue legitimately empty. Also detected + refused an embedded prompt-injection in tool content. |
| `rw-layout-budget-verdict` | 1 | 67,363 | 163 | 19 | Ran `estimate_layout.py` read-only BEFORE any render; two-part verdict — OVERFLOW 739pt vs ~734pt budget with the bands, targeted ≤~715pt, recommended shortening the longest bullets (simulated the trim in a tmp scratch copy → 716pt, never dropped a project), and stated `check.py`'s post-render page count is the authoritative gate. No render, no edits. |
| `rw-multi-experience-baseline` | 1 | (report relayed; usage not captured) | — | — | Canonical ordered `employers:` — both employers (Northwind Systems, Blue Lantern Labs) preserved with count/order/locked fields; 3 direct role bullets each kept as bullets (no 4-6-project restructuring, none dropped); both employers verified present in the 1-page resume PDF; cover 1 page; `check.py ✓ all passed (2 non-blocking warnings: 94% drift, ~1.3in trailing whitespace < 1.5in fail line)`. All artifacts in the isolated `_test_application_` tree. |
| `rw-bundled-txt-structure` | 1 | 88,484 (+ render resume) | 247 | 32 | One `..._Application_<role>.txt` at root; three `===`-underlined sections in order (COVER LETTER / WHY THIS COMPANY & ROLE / PAST EXPERIENCE); COVER LETTER = name+contact then salutation, NO subject line, 2 body paras (119/132 w, 283 total), plain text, "Sincerely,"+name; claims traced to tailored.yaml/JD (no fabrication). Cover-letter render completed on a follow-up (`cover_letter.py --label`): cover DOCX (source/) + PDF (root), 1 page; `check_cover_letter` clean. |
| `rw-skill-gating-weak-never` | 1 | 66,136 | 112 | 15 | Rust = Never (declined outright, absolute); Kafka = Weak but withheld after grepping the JD and confirming NEITHER term actually appears (caught the false premise); confirmed remaining JD skills all Approved (nothing uncategorized/silent); no fabricated proficiency; zero writes. |
| `rw-skill-category-question-batch` | 1 | 52,007 | 113 | 6 | Confirmed OpenTelemetry + WebAssembly absent from all three lists; ONE batch, TWO single-select questions (one per skill), the three consequence-labeled choices in exact Never / Weak or Selective / Approved order + Other last (recommendation allowed, order preserved); "Weak or Selective" treated as the user-facing alias for stored `Weak` (no rename/new category); did not categorize; zero writes. |
| `rw-duplicate-preflight` | 1 | 58,171 | 55 | 7 | Ran the preflight scan (log absent + every `<status>/<slug>/` folder), detected the complete existing `example-corp-senior-software-engineer` folder as an exact company+role match, STOPPED without a second folder/slug, offered to refresh; did not rely on the log alone; zero writes. |

Pass rate: **7/7**.

## Instruction-read self-audit (the leading indicator — did the token diet work?)

Per-subject bytes of INSTRUCTION files actually read (from each subject's own `wc -c` self-audit).
The two ~35 KB discretionary targets are **reference.md** (was pulled wholesale by routine SKILL
pointers) and the **check.py source** (was read whole because no authoritative surface existed).

| Canary | AGENTS.md | SKILL.md | LESSONS.md | reference.md | check.py source | app-tracker SKILL.md |
|--------|-----------|----------|------------|--------------|-----------------|----------------------|
| `rw-tailor` | 14,773 | 29,876 | 7,984 | **none** | slice ~250 lines (grep/offset: `check_skills`/`check_never_skills`/`check_cover_letter`) | none |
| `rw-layout` | 14,773 | 29,876 | 7,984 | **none** | **none** | none |
| `rw-multi` | 14,773 | 29,876 | 7,984 | slice ~45 lines ("Rephrasing…" §, on-trigger) | slice ~70 lines (`check_drift`+cover) | none |
| `rw-bundled` | 14,773 | 29,876 | 7,984 | slice ~200 lines (cover-letter §, lines 241–440) | greps only (constants) | none |
| `rw-skill-gating` | 14,773 | 29,876 | 7,984 | **none** | **none** | none |
| `rw-skill-batch` | none | 29,876 | none | **none** | **none** | none |
| `rw-duplicate` | 14,773 | 29,876 | 7,984 | **none** | **none** | none |

**Before → after (headline).** Baseline pattern (pre-change): every drafting run discretionarily
read ~70 KB (~18k tokens) beyond boot — reference.md 34.5 KB via routine pointers + check.py source
36.8 KB — plus LESSONS.md 6.9 KB unconditionally at boot.

- **reference.md wholesale reads: ELIMINATED.** 0 / 7 subjects read the full file. 5/7 read it not
  at all; 2/7 read a single **section-scoped** slice on an explicit trigger (rw-multi the Rephrasing
  §, matching its 94% rephrase; rw-bundled the cover-letter §). Section-scoped-pointer steering
  working as designed.
- **check.py full-source reads: ELIMINATED.** 0 / 7 read the whole source. 4/7 read none; 3/7 read
  targeted slices/greps for the skill-gate / cover-letter logic. This is the one residual (below).
- **Net discretionary read, heaviest full-tailoring subject (`rw-tailor`): ~11 KB** (check.py slices,
  0 reference.md) **vs ~70 KB before → ~59 KB / ~15k tokens retired.** Lightest (`rw-skill-batch`):
  **~0 discretionary** — SKILL.md only.
- **LESSONS.md residual:** 6/7 still read it (7,984 each; only rw-skill-batch skipped). It was an
  *unconditional* boot read before this change, so moving it to a render-failure trigger is
  net-neutral-to-better, not a regression — but the boot-defer steering is only partly honored. Small
  (7.9 KB) and, for `rw-layout`/`rw-multi`, arguably on-trigger (layout/sparse-bottom signal).

No subject got STUCK for want of information moved out of the quickstart — every routine cover
letter, tailoring run, and Step-7 batch completed from the SKILL.md quickstart alone (no unreachable
information → no restore needed).

## Verdict

- **Gate: PASS.** All seven canaries' `primary_metric` (`rubric_pass`) = 1; no listed `failure_mode`
  observed. Token/tool counts are in line with the prior gate record at `25f465e2e9ad` (the two
  full-tailoring canaries remain the heaviest); no efficiency blow-up.
- **Behavioral coverage:** the retiering (routine tailored.yaml-schema + cover-letter self-sufficiency;
  LESSONS→trigger; section-scoped pointers) and the script-first Step 7 (`skills_diff.py`) are
  exercised — `rw-tailor`/`rw-multi`/`rw-bundled` produced valid artifacts drawing only on the
  quickstart + scoped slices; `rw-skill-gating`/`rw-skill-batch` exercised the gate + batched Step-7
  protocol unchanged; `rw-duplicate` the preflight stop.
- **Isolation:** every subject's `git status --porcelain` empty; the tracked tree stayed clean
  throughout (all canary writes under gitignored `tmp/canary/**`); `examples/**` and `private/**`
  untouched.

## Follow-up steering strengthening (`edc176c`)

The one residual above (a full-tailoring subject reading targeted **check.py source slices** for the
skill-gate/cover-letter logic, rather than the new `check.py --rules` dump) was addressed by an
additive steering pointer at the Step-5 three-list gate: *"Need the exact gate semantics or a
threshold? Run `check.py --rules` (~1 KB) — never read the check.py source."* This is additive
steering only (no gate/step/deliverable change), so per the risk-based eval rule
(`evals/README.md`) it does not require re-gating the whole suite; a targeted `rw-tailor` re-run at
`edc176c` validates the reduction and is appended below.

**`rw-tailor` re-run @ `edc176c` (fresh sonnet subject): rubric_pass = 1** — 113,252 tokens, 497 s,
49 tool calls. Same faithful full-tailoring path (preflight clean; baseline start with light-touch
reword of 3 summary + 3 project bullets, all 5 projects kept, honest mentoring gap not fabricated;
est OVERFLOW 750pt → trimmed to 704pt OK; `check.py ✓` first cycle; resume + cover 1 page each).
**Step 7 ran `skills_diff.py` → "no uncategorized skills"** — the script-first Step-7 path exercised
end-to-end in a real run. Instruction reads: AGENTS.md 14,773 · SKILL.md 30,069 · LESSONS.md 7,984 ·
**reference.md slice ~260 lines (195–454, cover-letter/render templates, on-trigger)** · **check.py
source: none**.

Effect of the strengthening: the earlier run's **check.py source slice is gone (0 bytes this run)** —
the subject relied on `render.py`'s automatic `check.py` plus `skills_diff.py`/`estimate_layout.py`
instead of opening the validator. The residual moved to a section-scoped reference.md slice (the
cover-letter templates), not a wholesale read — confirming the net effect across both `rw-tailor`
runs: **wholesale reference.md and full check.py-source reads are eliminated; what remains is
section-scoped slices, exactly the "read ONLY that §" behavior the pointers now prescribe.**
