# Handover — jd-metadata-extraction

- **Date**: 2026-08-20
- **Task(s)**: none claimed; three new backlog items filed (below)

## What happened

- Nothing is broken or in flight. Branch `fix/jd-metadata-extraction` holds three
  finished commits, unpushed by design — the orchestrating session opens the PR.
- Three JD-metadata reads in `automation/shared/job_metadata.py` were reporting a
  stated fact as a different fact, or as no fact. All three are fixed with tests.
  GH #257: a nested specialty clause ("...including at least 2 years AI/ML")
  replaced the eight-year bar it narrows, so a Principal role read as a 2-year
  requirement and — after the #251 confidence fix landed — decisively PASSED a
  5-year cap. GH #264: year counts written in words ("at least five years",
  "six (6) years") parsed as nothing, and pay stated in the JD published as null
  when the band named no period ("$115,000-$152,500") or named it only in the
  amounts ("$21/hr to $25/hr"). GH #288: engineering-manager rows were rendered
  on the IC Google ladder, so the same job family read `mid (L4)` at one employer
  and `senior (L5)` at the next.

## Where things stand

- Three commits on `fix/jd-metadata-extraction`, not pushed, no PR.
- `automation/gates/run_gates.py --impact-from origin/main` exits 0: 30 gates
  green, `example-render` SKIPPED locally (no LibreOffice — CI runs it).
- Measured over the 228 JD-bearing cases in the tracked corpora, zero existing
  verdicts move; nine new corpus cases were appended at the END of
  `skills/job-search/filter_variants/corpus.yaml` (shared file).

## Decisions made for you

- A nested clause's requirement cue is INHERITED by the count it narrows, so the
  eight-year bar becomes decisive and `max_years_experience` can act on it.
  Without inheriting, the bar reports 8 but stays `review` — visible, not
  actionable. Undoing it is a one-line change in `_nest_yoe_candidates`.
- A large unlabelled band under a pay keyword is read as ANNUAL when both ends
  clear the annual floor the module already uses. Cheap to revert
  (`_implied_annual_period`); leaving it out means Greenhouse postings with pay
  in the JD keep publishing null.
- Management scopes were added to `NORMALIZED_LEVELS` rather than suppressing
  only the L-range. This changes what `classify_level` returns for a manager
  title everywhere, including the posting store's level opinion — deliberate,
  because the honest word is what every consumer should see.
- No new field was added to `analyze_job_metadata`'s return: `metadata_field_gaps`
  copies it into `meta.yaml` and `validate_job_metadata` rejects unknown
  structured fields there. The two review-reason readers are therefore standalone
  and currently unconsumed (filed).

## If X then Y

- If CI's `example-render` is red, it is not this change: no resume, template or
  render path was touched, and the gate only SKIPPED locally.
- If a manager posting shows up scoring differently, it is not the level change:
  `scoring.level_fit_delta` returns 0.0 for an absent range, so a management row
  is neither rewarded nor penalised for level.
- If `filter-variants` conflicts on rebase, it will be at the END of
  `corpus.yaml` — several agents appended there today. Resolve by keeping both
  blocks; the cases are independent.

## Dead ends

- Splitting the work into three commits was abandoned for two: the module is
  vendored byte-identically into three skills and stamped into the example-store
  fixtures, so a partial-file commit would ship an inconsistent tree. The
  management commit also depends on the YOE commit's number regexes.
- Flagging every unread "<count> years" phrase as a metadata-review finding
  fired on sponsorship waiting periods ("after two years"). The flag now requires
  the word "experience" in the same sentence.

## Needs your attention

- Nothing blocking. Three backlog items were filed, all P1/P2, none gating:
  `tasks/0_backlog/2026-08-20-google-eq-column-claims-occupations-it-never-mapped/`
  (the column still claims a Google equivalent for account-management and
  clinical roles — if nothing is done those rows keep showing an unsourced
  `L3`/`L8`);
  `tasks/0_backlog/2026-08-20-metadata-review-reasons-never-reach-the-report/`
  (the two new readers are computed and never shown — if nothing is done, a
  refused fact still looks identical to an absent one on the row);
  `tasks/0_backlog/2026-08-20-build-postings-reads-a-yoe-key-that-does-not-exist/`
  (the store's level fallback reads `minimum` where the assessment returns `min`,
  so it has never fired — if nothing is done every unleveled title keeps
  recording `unknown`).
