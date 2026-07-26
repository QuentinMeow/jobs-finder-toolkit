# Lessons — Search-Recall-Audit

Hard-won edge cases from running the recall audit. Promote durable heuristics here.

Last reviewed: 2026-07-25

Lifecycle tags: each `##` section carries `<!-- added: <first-seen> · last_confirmed: <date> · status: active -->`
(gardener `lessons_report` parses these; `added` = the section's first git appearance, `last_confirmed` = last review date).

## Hybrid/on-site in a non-preferred metro is the #1 false "miss"
<!-- added: 2026-07-25 · last_confirmed: 2026-07-25 · status: active -->
- AI reviewers reliably OVER-match here: they read "US + hybrid" as an acceptable
  US-remote role. It is NOT. A **hybrid or on-site** role in a US city that is NOT
  one of the profile's preferred metros classifies as `other_us` → `no_match`,
  because it requires being in that city. Only an office in a **preferred metro**
  or a **fully US-remote** role matches. The canonical prompt states this
  explicitly; keep it there, and always confirm an AI "MISSED" with `trace` before
  believing it. In the first run, 3 of 4 "misses" (Asana NYC, Benchling Boston,
  Palantir DC — all outside the profile's preferred metros) were this exact
  over-match — the pipeline was correct.

## Surfaced ≠ drafted; recently-searched suppresses whole companies
<!-- added: 2026-07-25 · last_confirmed: 2026-07-25 · status: active -->
- A role that `trace` shows passing ALL gates but that has no application is
  usually NOT a bug: either it was surfaced but not selected for drafting
  (drafting is selective), or its company was skipped by the 7-day
  recently-searched window (`company_search_log.skip_within_days`). Confirm
  surfacing with a `--refilter … --include-recent --include-considered
  --max-per-company 0` cross-check before calling anything a miss. Example: the
  Elastic "Distributed Systems, Serverless" role passed all gates (score 14.5)
  and was simply undrafted alongside two sibling Elastic roles.

## Grep the WHOLE JD, not the title
<!-- added: 2026-07-25 · last_confirmed: 2026-07-25 · status: active -->
- Sampling only by title-column matches hides the most valuable recall bug class:
  a role whose TITLE misses the include-list but whose BODY is clearly in-scope
  (`TITLE_GATE_FALSE_NEGATIVE`). The sampler greps the full posting line
  (company+title+location+description). This also pulls in obvious non-matches
  (e.g. a "Sales" JD that merely mentions "developer experience") — that noise is
  expected and the Sonnet match step filters it; do not narrow the grep to reduce it.

## Duplicated `gh_jid` breaks naive URL matching
<!-- added: 2026-07-25 · last_confirmed: 2026-07-25 · status: active -->
- Some Greenhouse custom-domain boards return `absolute_url` with the id repeated
  (`?gh_jid=X&gh_jid=X`). The audit's `canon()` de-duplicates IDENTICAL query
  pairs (always safe) so `trace --url` and the coverage pre-check still match the
  single-`gh_jid` form. Do NOT "fix" this by stripping distinct query params — a
  bare-path strip collapses genuinely different postings and fabricates false
  "already covered" hits (an early version of the coverage pre-check did exactly
  that). See `private/memory/known-issues/greenhouse-absolute-url-duplicate-gh-jid.md`.

## Product-name "… Manager" IC titles are a real title-gate false negative
<!-- added: 2026-07-25 · last_confirmed: 2026-07-25 · status: active -->
- The profile exclude `manager` matches on a word boundary and is highest-precedence
  in `assess_title`, so an IC role whose title ends in a PRODUCT named "… Manager"
  (Palantir "Mission Manager", OpenAI "Ads Manager") is hard-dropped before the
  "software engineer" include is ever evaluated — a genuine recall miss. Confirm with
  `trace` (FIRST DROP GATE: title) AND a blast-radius scan (titles carrying an IC
  role-noun + whole-word "manager") before proposing a fix: most such titles are real
  Engineering/Project/Tech-Lead/Staff managers that are correctly excluded (in one
  kubernetes-focused recall run, only 2 of 12 were genuine FNs). Filed as known-issue
  `title-gate-manager-product-suffix-false-negative.md`; the fix (route the narrow
  case to `review`) is a human-reviewed content-gate edit, never applied on a hunch.
- Meta: an AI `TITLE_GATE_FALSE_NEGATIVE` verdict is itself only a hypothesis — trace
  it too. In that run the composer reviewers flagged two CoreWeave titles as title-gate
  FNs, but `trace` showed the title gate PASSES both (they were surfaced); the only real
  title FN was the product-name "Manager" class.

## Field-fidelity: fix KNOWN source formats, escalate WEIRD ones — never fold noisy fields
<!-- added: 2026-07-25 · last_confirmed: 2026-07-25 · status: active -->
- A second audit variant checks GENERATED fields (the `location` string the gate reads)
  against the RAW source payload (`field_fidelity.py corpus/sample/check/todo`). The
  win is a per-source known-format extractor, NOT "fold every raw location field in":
  naive folding is noisy (greenhouse `offices[]` tags a UK-remote role to a "US (Remote)"
  office group — composer verdict NOISY_FIELD; do NOT fold it). Confirmed real drops:
  Lever ignored `categories.allLocations` (onsite multi-city US → vague "United States"
  → FALSE us-remote match) and `country`; Ashby dropped `address.addressCountry`
  (bare "Belgrade"/"Sao Paolo" → `review` not foreign `no_match`); Apple duplicated
  country via `f"{loc} {country}"` (cosmetic). Fixed in `posting_parsers.py`
  (~46 MATCH→NO_MATCH corrections; lever drops/flips → 0).
- The escape hatch is the pipeline's existing three-valued `review`, not a new system:
  pure region-bucket strings ("West"/"Central"/"International" — a Greenhouse office
  GROUP, not a place) get a distinct `weird_location_format` review reason and route to
  `review` (never a silent guess), with `field_fidelity.py todo` listing them for AI
  triage. Keep the detector CONSERVATIVE: it must not flip any existing match/no_match
  (verify the decision distribution is unchanged over the corpus before/after).
- Trust the DETERMINISTIC re-parse over the heuristic flag. The audit's
  `dropped_raw_token`/`gate_decision_flip` heuristics are noisy (7.5k/821 raw); the
  signal is `gate_decision_flip` AFTER excluding known-noisy fields, then composer
  verification, then a re-parse. ISO codes ("US-CA-San Francisco", "GB-London", "CN-Beijing")
  already classify correctly via substring — do NOT "fix" them.
- Filed: `private/memory/known-issues/location-field-fidelity-parser-drops.md`. Residual
  knob: the broad `unclassified_location` review bucket (~370 bare foreign cities from
  greenhouse/workday) is handled as `review` but not yet TODO-routed — the actionable
  fix there is extending the foreign/US token lists by distinct token, not per-posting.
