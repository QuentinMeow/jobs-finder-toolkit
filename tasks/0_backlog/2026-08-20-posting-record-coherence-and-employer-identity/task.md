# Cross-domain posting coherence and employer identity in the source-quality gate

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GH #293 and the later comment threads on GH #271, both partly
  fixed on branch `fix/posting-quality-and-scoring`. That branch deliberately
  built only the detections that fit inside `scoring.assess_posting_quality`
  and filed the rest here.
- **Claimed-by**:

## Goal

Give the job-search pipeline a real coherence check across a posting's five
assessment domains (title, location, sponsorship, quality, experience), and give
the source-quality gate the two record-level signals it still cannot see:
a missing employer identity and a body with no job content in it.

## Context

Three findings from the same cluster were fixed. These four were not, each for a
named reason.

### 1. Cross-domain coherence (GH #293, the general case)

`scoring.assess_posting_quality` now flags ONE shape of title/body chimera: the
body's own leading heading names an occupation family disjoint from the
structured title's (`quality.title_body_conflict` -> review reason
`posting_title_body_conflict`). That covers the two reported technical cases
(a `Technical Writer` row whose body is a product-manager requisition, and a
product-designer row whose body is an engineering-manager requisition).

It does NOT cover the clinical reproduction in #293's comments: an `RN - L&D`
row whose body is a Med/Surg posting with NO contradicting heading. Nothing in
the title/heading pair contradicts there — the contradiction is between the
title's specialty and the body's stated requirements. Detecting that needs a
comparison across the assessments the pipeline already computes (title
occupation, required YOE, location, sponsorship), which lives in
`search_jobs.filter_score_rank`, not in a single-domain assessor.

Note for whoever picks this up: an earlier triage marked #293 shipped via the
store-side fix at `skills/job-search/scripts/build_postings.py:594-607`
(`jd_from_another_posting`). That fix is real but only fires when a folded JD
came from a DIFFERENT observation (`jd_sid != latest_sid`). Every reported #293
case is a single observation whose row already arrived incoherent from the
aggregator, so it never fires. Do not re-close this on that code path.

### 2. Missing employer identity (GH #271 comments)

Two comment threads report complete Indeed JDs whose normalized `company` is
blank surviving into the review queue (a `Student TA - UX Design II` row, a
`Web Designer` row, and a 6k-character space/firmware JD). Employer identity is
what makes legitimacy, dedupe, blacklist, and sponsorship research possible.

Not built because `assess_posting_quality(title, description)` never receives
the company, and the deterministic corpus dispatch
(`filter_variants.run_case`) cannot pass one without a signature change to a
file the branch did not own. Sizing it also needs one honest measurement first:
what share of rows from each source carry a blank company at gate 0? A review
reason that fires on a whole source floods the review queue, which is the
problem #271 is about.

### 3. Boilerplate-only bodies (GH #271 comments)

A Lever `Staff Engineer, AI Platform & Architecture` row ranked in two refilters
with a captured description containing only company/offer/EEO boilerplate — no
duties, skills, YOE, degree, or export requirement. A Markelic
`Apply Support Engineer` row has a 595-character body repeating
salary/vacancy/education three times.

Not built because "has no job content" needs a positive content model (does the
body contain a requirements/responsibilities section, a skill list, a YOE
statement?), not another placeholder pattern. Guessing that model risks
rejecting terse but real postings, which is worse than the bug.

### 4. Structured/body date contradiction (GH #293)

#293 also reports a structured `posted_at` of 2026-07-30 against a body date of
January 13, 2026 on the same chimera row. The quality assessor never receives
the posted date, so only the title half of that contradiction is detected. Same
signature constraint as (2).

## Definition of done

- A coherence check that fires on the clinical #293 reproduction (title
  specialty vs body requirements) without flagging ordinary postings, with the
  finding visible in the review report.
- A measured, per-source blank-company rate recorded in the task's
  `verification.md` BEFORE any missing-employer rule ships.
- Minimal regressions added to
  `skills/job-search/scripts/tests/test_pipeline_corrections.py` and, where the
  input is a single assessor's, to `skills/job-search/filter_variants/corpus.yaml`.
- A before/after kept-count over the public example corpus showing no real
  posting newly rejected — the harness used on the source branch is
  `assess_posting_quality` run over every corpus/example-store/fixture record
  against `origin/main`'s module.
- `.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t .`
  exits 0.
