# Lessons — Job Search

Curated operational lessons from real usage — mostly hard-won domain edge cases (visa phrasing,
title/location false-matches, source noise). Promote durable heuristics here from `.agents/MEMORY.md`
after they prove out. The two-stage model and AI-native scoring are explained in SKILL.md.

Last reviewed: 2026-07-19

Lifecycle tags: each `##` section carries `<!-- added: <first-seen> · last_confirmed: <date> · status: active -->`
(gardener `lessons_report` parses these; `added` = the section's first git appearance, `last_confirmed` = last review date).

## Sources
<!-- added: 2026-07-13 · last_confirmed: 2026-07-19 · status: active -->
- ATS board tokens are not always the company's obvious name: Glean → `gleanwork`,
  Scale AI → `scaleai`, Together AI → `togetherai`, Cursor → `cursor` (not `anysphere`).
  Probe both Greenhouse and Ashby when unsure; run `validate_companies.py` after edits.
- Greenhouse `content` is double entity-encoded HTML; `strip_html` already unescapes twice.
- Ashby exposes `descriptionPlain` directly (no HTML parsing needed) and `isListed:false`
  postings should be skipped.

## Visa filtering
<!-- added: 2026-07-13 · last_confirmed: 2026-07-31 · status: active -->
- Keep the negative phrase list specific. Generic "must be authorized to work in the US"
  is boilerplate used even by sponsoring employers — matching it would wrongly reject
  almost everything. Only explicit denials should yield `no`.
- Most postings are `unclear`. Default `exclude_negative` keeps them; use
  `require_positive` only when the user wants a hard sponsorship guarantee (few results).
- `unclear` is the safe answer and the classifier is built to fall back to it: a `no` is
  dropped under BOTH policies (it hides a job), a `yes` is handed to someone making an
  immigration decision. Ambiguous text — a double negative, a discretionary "we will
  consider sponsorship" — must land `unclear`, which keeps the posting and flags it.
- "Sponsorship" has a second legal sense: US export-control licensing (ITAR/EAR,
  "without sponsorship for an export license"). That sentence says nothing about
  immigration; a whole export-controlled board used to vanish under the default policy
  because it read as a denial. The classifier now ignores a sponsorship phrase whose
  sentence is export-control language with no immigration word in it.

## Visa heuristic false-positives
<!-- added: 2026-07-20 · last_confirmed: 2026-07-31 · status: active -->
- The sponsorship heuristic used to score `yes` on a negation: a posting whose text said
  it does *not* sponsor still contained sponsorship keywords and was tagged `yes`. It no
  longer does — a bounded negation scope means an offer phrase inside a negated clause
  ("does not currently offer visa sponsorship") counts as a denial. The residual gap is
  narrower but real: a denial that matches NEITHER an offer phrase nor a denial phrase
  ("we do not offer relocation or visa sponsorship") still reads `unclear`, and a
  negation more than ~8 words from the phrase it governs is out of scope.
- Still treat a heuristic `yes` as a claim to verify against the actual JD wording before
  relying on it for a policy decision. The gate is advisory and the user is making an
  immigration decision on it.

## Filtering / scoring
<!-- added: 2026-07-13 · last_confirmed: 2026-07-31 · status: active -->
- A 7-day window across 100+ boards + keyless aggregators scans ~11k postings in ~20s
  and yields a solid shortlist; narrow with `--max-age-days 3` or widen if too thin.
- **`company-search-log.yaml`**: only log a company after a *successful* search — full board
  enumerated plus an application decision (`created` folder or `no_suitable`). Do not log
  browsing-only passes or unreachable boards (404, sign-in wall, missing ATS); those should
  be re-tried. job-search skips logged companies within `skip_within_days` (default 7);
  use `--include-recent` to override.
- `negative` keywords (gcp/azure/rust/etc.) are honest mis-fit signals — they lower
  score but never hard-filter, so strong-fit roles that merely mention them still surface.
- Keep company leveling/compensation research out of `companies.yaml`: identity/polling is
  stable registry data, while level equivalence and pay are dated. Cache the latter at
  `config.company_levels_path()` with sources + `last_verified`; live posting values win.
- Hard-filter on YOE only when the parser finds a high-confidence general requirement;
  preferred or tool-specific/contextual experience remains display-only.
- A YOE number only counts when the sentence attributes the years to the APPLICANT.
  "Our founders bring 25 years of engineering experience" is company history and reads
  identically to a requirements bullet — it used to become a 25-year minimum and drop the
  posting. A company/team/customer subject with no applicant vocabulary after it, or the
  word "combined", means no requirement was stated at all.
- Never combine hourly/annual, currencies, or geographic compensation bands. Never assume
  a missing currency, and never infer total compensation without an explicit total/OTE label.
- Never scrape Levels.fyi. Automated benchmark ingestion is file-only and requires a
  user-supplied licensed export/API source with access provenance.

## Title exclusions
<!-- added: 2026-07-13 · last_confirmed: 2026-07-19 · status: active -->
- Excluding the bare word "staff" would wrongly drop "Member of Technical Staff" — the
  IC title OpenAI/Anthropic/Perplexity use (NOT staff-level). Use `titles.exclude_neutralize`
  to strip such phrases before the exclude check runs. Verified: MTS kept, "Staff/Staff+/
  Senior Staff/Principal/Distinguished Engineer" dropped.
- Multi-city postings that include a wanted city pass a strict location filter; surface the
  matched segment in output (e.g. "Austin, TX (+4)") so it isn't mistaken for a non-match.

## Location / US gate
<!-- added: 2026-07-13 · last_confirmed: 2026-07-31 · status: active -->
- Check `is_foreign` BEFORE remote/preferred/US-abbrev, or foreign-remote roles leak:
  "remote" in `preferred` matches "Germany (Remote)", and the `\b[A-Z]{2}\b` abbrev
  check false-matches Canada (`CA`) and India (`IN`) country codes. Foreign-first wins.
- Dropped "ontario"/kept-narrow foreign tokens to avoid nuking US "Ontario, CA" /
  "Vancouver, WA"; Toronto/Montreal/Canada still catch Canadian roles.
- Some boards publish only `Distributed` as the location and put the real country
  in the title (`..., Canada`, `..., Canberra`, `..., Nordics`). Include the title
  in foreign detection before treating a generic distributed/remote marker as US.
- The title's geography REJECTS only, never grants. A region in a title
  (`..., Americas`, `..., NAmer`) is a coverage/market descriptor — it once carried
  a role that is hybrid across four non-preferred US cities through as a US-remote
  match. Positive US scope must come from the location field.
- A whole board can put a workplace WORD (`Hybrid`, `In-Office`, `Distributed`)
  where the location belongs and name the cities only inside the JD. Such a tag
  carries no geography (verdict `review` / `workplace_tag_without_geography`) and
  cannot contradict an explicit JD remote grant — the JD is the only statement of
  record. Read those postings; never relay `review` as "no match".

## Aggregators, JobSpy & LinkedIn/Indeed
<!-- added: 2026-07-13 · last_confirmed: 2026-07-19 · status: active -->
- Company boards = best signal for specific targets; aggregators = market breadth.
  Keyless defaults: Jobicy (geo=usa), RemoteOK, The Muse. Arbeitnow is EU-heavy — opt-in.
- No free official LinkedIn/Indeed API. JSearch (RapidAPI, one key) aggregates both;
  JobSpy scrapes them directly but is slow and LinkedIn 429s. Keyed sources read creds from
  env vars (ADZUNA_*, RAPIDAPI_KEY); never commit keys. `keyed_available(name)` gates
  stage-2 keyed aggregators on env-var presence so a keyless run doesn't spam source errors.
- **JobSpy Indeed is the workhorse:** fast (~1–2s per term×location), reliable, honors
  `distance` (radius miles) + per-location `is_remote`. One `{location:"City, ST", distance:40}`
  entry pulls the surrounding suburbs; add `{location:"United States", is_remote:true}` for
  the US-remote pass.
- **JobSpy noise (domain edge case):** market scrapes surface staffing-agency / mis-parsed
  employers ("Startekk Inc", blank company, "EPIC Kids") and occasional non-metro roles JobSpy
  over-tags as remote. Scoring/ranking buries most; skim the tail. Company-board hits stay the
  cleanest signal.
- AI-native curation (edge case): `ai-lab`+`ai-infra` tags already cover ~35 pure-plays; only
  hand-add the `ai-native` tag when a company is AI-first but its primary tag is
  dev-tools/consumer/data-platform (Replit, Warp, Waymo/Nuro/Zoox, Palantir). See SKILL.md
  "AI-native / AI-transitioning company fit" for the two-signal scoring model.

## Scraped remote flag is unreliable
<!-- added: 2026-07-20 · last_confirmed: 2026-07-20 · status: active -->
- Never trust the market-scraper (JobSpy) remote/workplace flag for the location gate or for
  handoff facts. In a live run *every* match came back tagged remote — including postings whose
  JD text explicitly said hybrid or on-site. Verify workplace type from the saved JD text
  before handing off a posting or recording location facts.

## Full-evidence filters and new variants
<!-- added: 2026-07-21 · last_confirmed: 2026-07-21 · status: active -->
- An ATS location can list several office hubs while the JD later offers a US-remote alternative.
  Location/workplace decisions must read the full JD, not a short prefix or location string alone;
  search, handoff metadata, and `--check-locations` must use the same assessment.
- Hybrid at a non-preferred office is not generic remote. Contradictory remote/onsite evidence and
  mixed US/foreign scope go to the review queue rather than being silently accepted or rejected.
- After a fetch or final refilter, run `validate_filter_variants.py --snapshot ...`. Known semantic
  shapes are deterministic and AI-free; an unknown structural signature is a maintenance failure
  until its real JD is reviewed and a fictional minimal corpus regression is added.
