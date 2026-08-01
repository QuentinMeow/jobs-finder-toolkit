# Verification — 2026-07-31-sponsorship-negation-defeats-require-positive

Only commands actually run, with their real output. "BEFORE" rows come from a
scratch harness that loads `automation/shared/job_metadata.py` as of `git HEAD`
(the pre-fix module) and runs the identical fixtures; nothing in the worktree was
reverted to produce them. Every fixture sentence is fictional — no employer is
named anywhere.

**Corrected 2026-07-31 on the stack tip `40871e6`.** The behavioural evidence in §§1–4
all reproduces — the pre-fix corpus run in §4 was independently rebuilt and returns the
same 23 failure lines, character for character. What was wrong is the arithmetic in §4
and §5: the corpus size and two of the four suite totals were `main`-based, captured on
the isolated authoring worktree and never re-run after the branch was stacked. Corrected
in place, with the authoring-commit (`86a18e0`) and tip figures both given.

## 1. Sponsorship — the reported defect, before and after

`assess_sponsorship(text)` -> `verdict / decision / confidence / rule_ids`.

```
BEFORE (git HEAD)
D1 negated-offer adverb            likely   match    high   sponsorship.positive.offer visa sponsorship
D1 negated-offer distant cue       likely   match    high   sponsorship.positive.immigration sponsorship
D1 negated-offer after ';'         likely   match    high   sponsorship.positive.visa sponsorship available,...
D1 negated-offer 'not able to'     likely   match    high   sponsorship.positive.offer visa sponsorship
D1 comma aside                     likely   match    high   sponsorship.positive.offer visa sponsorship
D1 double negative                 unlikely no_match high   sponsorship.negative.cannot sponsor
D3 export-control only             unlikely no_match high   sponsorship.negative.without sponsorship
D3 export-control ITAR clause      unlikely no_match high   sponsorship.negative.without sponsorship
-- guard: export + real denial     likely   match    high   sponsorship.positive.provide visa sponsorship

AFTER (this branch)
D1 negated-offer adverb            unlikely no_match high   sponsorship.negated_offer.offer visa sponsorship
D1 negated-offer distant cue       unlikely no_match high   sponsorship.negated_offer.immigration sponsorship
D1 negated-offer after ';'         unlikely no_match high   sponsorship.negated_offer.visa sponsorship available,...
D1 negated-offer 'not able to'     unlikely no_match high   sponsorship.negated_offer.offer visa sponsorship
D1 comma aside                     unlikely no_match high   sponsorship.negated_offer.offer visa sponsorship
D1 double negative                 unknown  review   low    sponsorship.ambiguous.double_negation
D3 export-control only             unknown  review   low    sponsorship.non_immigration.export_control
D3 export-control ITAR clause      unknown  review   low    sponsorship.non_immigration.export_control
-- guard: export + real denial     unlikely no_match high   sponsorship.negated_offer.provide visa sponsorship
```

Guardrails — identical BEFORE and AFTER, i.e. the fix changes nothing here:

```
-- guard: coordinated denials      unlikely no_match high    (two denials != a double negative)
-- guard: plain denial             unlikely no_match high
-- guard: export + real offer      likely   match    high
-- guard: clause restart           likely   match    high    ("no relocation budget, and visa sponsorship is available")
-- guard: caveat after offer       likely   match    high    ("... though sponsorship is not guaranteed")
-- guard: contrastive 'but'        likely   match    high
-- guard: conditional offer        unknown  review   unknown ("we will consider visa sponsorship ...")
-- guard: work-auth boilerplate    unknown  review   unknown
-- guard: true offer               likely   match    high
-- guard: unrelated sponsorship    unknown  review   unknown
-- guard: conflict                 unknown  review   low
-- guard: silence                  unknown  review   unknown
```

## 2. Required YOE — third-party attribution, before and after

`extract_required_yoe_details` + `assess_required_yoe(cap=8)` +
`analyze_job_metadata(...)["job_level"]["normalized"]`.

```
BEFORE (git HEAD)
D2 founders' years              min=25   conf=high    kind=required   cap8=no_match level=senior_staff
D2 team combined total          min=30   conf=high    kind=required   cap8=no_match level=senior_staff
D2 customers' years             min=40   conf=high    kind=required   cap8=no_match level=senior_staff
D2 'a team with ... combined'   min=40   conf=medium  kind=contextual cap8=review   level=senior_staff
D2 blurb + real requirement     min=25   conf=high    kind=required   cap8=no_match level=senior_staff
D2 real requirement + blurb     min=30   conf=high    kind=required   cap8=no_match level=senior_staff

AFTER (this branch)
D2 founders' years              min=None conf=unknown kind=not_stated cap8=review   level=unknown
D2 team combined total          min=None conf=unknown kind=not_stated cap8=review   level=unknown
D2 customers' years             min=None conf=unknown kind=not_stated cap8=review   level=unknown
D2 'a team with ... combined'   min=None conf=unknown kind=not_stated cap8=review   level=unknown
D2 blurb + real requirement     min=3    conf=high    kind=required   cap8=match    level=mid
D2 real requirement + blurb     min=3    conf=high    kind=required   cap8=match    level=mid
```

Guardrails — identical BEFORE and AFTER:

```
-- guard: plain requirement             min=3    conf=high    cap8=match
-- guard: qualifications bullet         min=8    conf=high    cap8=match
-- guard: 'we are looking for'          min=6    conf=high    cap8=match
-- guard: 'we have an opening'          min=6    conf=high    cap8=match
-- guard: team subject, then candidate  min=6    conf=high    cap8=match
-- guard: preferred                     min=None conf=unknown cap8=review
-- guard: tool-specific                 min=7    conf=medium  cap8=review
```

## 3. New tests fail against the pre-fix module

**Both runs below were reproduced 2026-07-31** in a rebuilt pre-fix tree (the tree at
`86a18e0` with `automation/shared/job_metadata.py` and its job-search vendored copy
replaced by `86a18e0^`'s). Same totals, same failure counts, same test names in the same
order.

Pre-fix run of `automation/shared/tests/test_job_metadata.py` (a scratch copy of
`automation/shared/` + `automation/vendoring/` with `job_metadata.py` from `HEAD`):

```
$ python -m unittest discover -s automation/shared/tests -t automation/shared/tests \
      -p 'test_job_metadata.py'          # in the scratch pre-fix tree
FAIL: SponsorshipExportControlSenseTests.test_export_clause_does_not_suppress_a_real_denial
FAIL: SponsorshipExportControlSenseTests.test_export_license_boilerplate_is_not_a_denial
FAIL: SponsorshipExportControlSenseTests.test_itar_clause_is_not_a_denial
FAIL: SponsorshipNegationScopeTests.test_double_negated_denial_is_unknown_not_a_denial
FAIL: SponsorshipNegationScopeTests.test_negated_offer_after_semicolon_is_unlikely
FAIL: SponsorshipNegationScopeTests.test_negated_offer_with_adverb_is_unlikely
FAIL: SponsorshipNegationScopeTests.test_negated_offer_with_distant_cue_is_unlikely
FAIL: SponsorshipNegationScopeTests.test_not_able_to_offer_is_unlikely
FAIL: SponsorshipNegationScopeTests.test_parenthetical_aside_does_not_break_the_negation
FAIL: ThirdPartyYoeAttributionTests.test_combined_team_total_is_not_a_requirement
FAIL: ThirdPartyYoeAttributionTests.test_company_blurb_does_not_fabricate_metadata
FAIL: ThirdPartyYoeAttributionTests.test_company_blurb_does_not_outrank_the_real_requirement (x2 subtests)
FAIL: ThirdPartyYoeAttributionTests.test_company_blurb_no_longer_hard_drops_the_posting
FAIL: ThirdPartyYoeAttributionTests.test_customer_experience_is_not_a_requirement
FAIL: ThirdPartyYoeAttributionTests.test_founders_experience_is_not_a_requirement
Ran 126 tests in 0.170s
FAILED (failures=16)
```

Pre-fix run of `skills/job-search/scripts/tests/test_visa.py` (vendored copy
temporarily replaced with `HEAD`'s, then restored by `sync_vendored.py`):

```
$ python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests -p 'test_visa.py'
FAIL: NegatedOfferTests.test_double_negative_is_unclear
FAIL: NegatedOfferTests.test_export_control_boilerplate_is_unclear_not_no
FAIL: NegatedOfferTests.test_negated_offers_score_no (x4 subtests)
FAIL: VisaPolicyBindingTests.test_default_policy_keeps_an_export_control_posting
FAIL: VisaPolicyBindingTests.test_require_positive_drops_a_negated_offer
Ran 17 tests in 0.076s
FAILED (failures=8)
```

The commit adds **35** test methods (28 in `test_job_metadata.py`, 7 in `test_visa.py`;
`git show 86a18e0 --numstat` shows both files pure-append). **20** of them fail pre-fix —
15 above plus 5 in `test_visa.py` — so the remaining **15** are deliberate guardrails:
they assert behaviour that must NOT change, so they pass both before and after. (This
line originally said 13, which is the `test_job_metadata.py` guardrail count alone and
drops `test_visa.py`'s two.)

## 4. New corpus cases fail against the pre-fix module

**Reproduced 2026-07-31, independently of the original scratch harness.** The tree at
`86a18e0` was extracted to a temp dir and `automation/shared/job_metadata.py` plus its
job-search vendored copy were replaced with `86a18e0^`'s, then the *shipped* validator
was run — no bespoke harness. It returns the same 23 lines in the same order, exit 1.
The only wrong figure here is the corpus size: the corpus at `86a18e0` holds **57**
cases, not 51.

```
$ python skills/job-search/scripts/validate_filter_variants.py --profile example
      # tree at 86a18e0, job_metadata.py swapped back to 86a18e0^
pre-fix run of 57 corpus cases -> 23 failure line(s)              exit 1
  CHECK sponsorship-negated-offer-phrase: decision: expected 'no_match', got 'match'
  CHECK sponsorship-negated-offer-phrase: verdict: expected 'unlikely', got 'likely'
  CHECK sponsorship-negated-offer-distant-cue: decision: expected 'no_match', got 'match'
  CHECK sponsorship-negated-offer-distant-cue: verdict: expected 'unlikely', got 'likely'
  CHECK sponsorship-negated-offer-after-semicolon: decision: expected 'no_match', got 'match'
  CHECK sponsorship-negated-offer-after-semicolon: verdict: expected 'unlikely', got 'likely'
  CHECK sponsorship-double-negation-is-ambiguous: decision: expected 'review', got 'no_match'
  CHECK sponsorship-double-negation-is-ambiguous: verdict: expected 'unknown', got 'unlikely'
  CHECK sponsorship-double-negation-is-ambiguous: confidence: expected 'low', got 'high'
  CHECK sponsorship-export-control-is-not-a-denial: decision: expected 'review', got 'no_match'
  CHECK sponsorship-export-control-is-not-a-denial: verdict: expected 'unknown', got 'unlikely'
  CHECK sponsorship-export-control-is-not-a-denial: confidence: expected 'low', got 'high'
  CHECK sponsorship-export-control-beside-a-real-denial: decision: expected 'no_match', got 'match'
  CHECK sponsorship-export-control-beside-a-real-denial: verdict: expected 'unlikely', got 'likely'
  CHECK yoe-third-party-founder-experience: decision: expected 'review', got 'match'
  CHECK yoe-third-party-founder-experience: min: expected None, got 25
  CHECK yoe-third-party-founder-experience: confidence: expected 'unknown', got 'high'
  CHECK yoe-third-party-founder-experience: requirement_kind: expected 'not_stated', got 'required'
  CHECK yoe-third-party-combined-team-total: decision: expected 'review', got 'match'
  CHECK yoe-third-party-combined-team-total: min: expected None, got 30
  CHECK yoe-third-party-combined-team-total: confidence: expected 'unknown', got 'high'
  CHECK yoe-third-party-combined-team-total: requirement_kind: expected 'not_stated', got 'required'
  CHECK yoe-company-blurb-then-real-requirement: min: expected 3, got 25
```

9 of the 12 new corpus cases fail pre-fix. The other 3
(`sponsorship-offer-after-clause-restart`, `sponsorship-caveated-offer-stays-offer`,
`yoe-requirement-after-team-subject`) are guardrails against over-correcting.

## 5. Corpus validator, vendoring drift, and the three suites (post-fix)

Re-measured 2026-07-31 at this change's own commit `86a18e0`. Three figures were
`main`-based and are corrected: the corpus was **57** cases (not 51), shared **541**
(not 517), job-search **425** (not 363). Tracker 108 and resume 98 were already right.

```
$ .venv/bin/python skills/job-search/scripts/validate_filter_variants.py --profile example
filter variant corpus clean: 57 cases

$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 541 tests in 23.314s
OK

$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests
Ran 425 tests in 101.651s
OK

$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests
Ran 108 tests in 77.032s
OK

$ .venv/bin/python -m unittest discover -s skills/resume-writer/scripts/tests
Ran 98 tests in 40.467s
OK
```

At the stack tip `40871e6` the same five give: corpus **60** cases, shared **559**,
job-search **473**, tracker **108**, resume **98** — all clean, vendoring still in sync.

No live fetches were made; every fixture is fictional text passed straight to the
classifier.
