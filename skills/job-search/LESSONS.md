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
- Greenhouse `content` is double entity-encoded HTML — the ONLY such source. Read it with
  `strip_html(..., entity_encoded=True)`; every other source is single-encoded and must not
  get that flag, or a `&lt;` in JD prose ("teams of &lt; 12") becomes a real `<` and the tag
  stripper eats the rest of the element (a sponsorship denial included).
- Ashby exposes `descriptionPlain` directly (no HTML parsing needed) and `isListed:false`
  postings should be skipped.

## Visa filtering
<!-- added: 2026-07-13 · last_confirmed: 2026-07-31 · status: active -->
- Keep the negative phrase list specific. Generic "must be authorized to work in the US"
  is boilerplate used even by sponsoring employers — matching it would wrongly reject
  almost everything. Only explicit denials should yield `no`.
- `unclear` is the safe fallback and where most postings land: a `no` is dropped under BOTH
  policies (it hides a job), a `yes` goes to someone making an immigration decision. Default
  `exclude_negative` keeps `unclear`; `require_positive` is for a hard guarantee only (few
  results). Treat any `yes` as a claim to verify against the JD wording — the gate is advisory.
- "Sponsorship" has a second legal sense: US export-control licensing (ITAR/EAR, "without
  sponsorship for an export license"). That sentence is not an immigration denial and is
  ignored — a whole export-controlled board used to vanish under `exclude_negative` because it
  read as one. Mechanism: reference.md, "How polarity is decided".

## Visa heuristic false-positives
<!-- added: 2026-07-20 · last_confirmed: 2026-07-31 · status: active -->
- Polarity is structural, not lexical: an offer phrase inside a bounded negation scope ("does
  not currently offer visa sponsorship") is a denial, which stopped the heuristic scoring `yes`
  on a negation. Two gaps stay live: a denial matching NEITHER list ("we do not offer
  relocation or visa sponsorship") reads `unclear`, and a negation >~8 words away is out of scope.
- **An offer and a LIMIT ON that offer are not a denial.** `not (for EVERY x)` negates a
  universal and entails that some x ARE sponsored; `does not sponsor` is the universal negation.
  "We do sponsor visas… however not for every role" is a sponsor, and grading it `unclear` made
  `require_positive` return zero against the clearest sponsor in an 11.7k-posting scan. A scope
  limit only REMOVES a denial, never creates an offer, so "we can't sponsor everyone" alone
  stays `unclear`. Two shapes it must NOT catch, both still `no`: `at all` intensifies a denial,
  and a quantifier BEFORE the cue is a requirement subject ("ALL roles require work auth…").
  Only DISTRIBUTIVE quantifiers count (`every`/`each`/`guarantee`): bare `all` reads
  collectively too, so "…sponsor visas for ALL new hires" is a flat denial — read as a limit it
  DELETED the denial and an unrelated positive graded the row `yes`/high. "Only removes a denial"
  is true of the evidence lists, NOT the verdict. Ambiguous quantifier => keep the denial.
- Grading is by OFFER STRENGTH: unhedged offer > hedged offer > silence, a scope limit moves
  nothing, a flat denial beats everything. So a hedged offer ("limited sponsorship may be
  available", "case-by-case", "at our discretion") and a double negative both land `unclear`,
  and a denial beside an offer of either strength is a conflict (review), never a silent drop.

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
- Excluding the bare word "staff" would wrongly drop `Member of <X> Staff` — the IC title
  family OpenAI/Anthropic/Perplexity use, which is NOT staff-level. `titles.exclude_neutralize`
  strips it BEFORE the exclude check, and listing any ONE spelling declares the whole family:
  boards write Technical / Data / Research / Applied Research / "the Technical" for the same
  title, and a live "Member of Data Staff" was hard-dropped while Technical sailed through. A
  level word in front still classifies and still excludes on its own, so
  Staff/Staff+/Senior Staff/Principal/Distinguished Engineer all stay dropped.
- Multi-city postings that include a wanted city pass a strict location filter; surface the
  matched segment in output (e.g. "Austin, TX (+4)") so it isn't mistaken for a non-match.

## Location / US gate
<!-- added: 2026-07-13 · last_confirmed: 2026-07-31 · status: active -->
- Check `is_foreign` BEFORE remote/preferred/US-abbrev, or foreign-remote roles leak:
  "remote" in `preferred` matches "Germany (Remote)", and the `\b[A-Z]{2}\b` abbrev
  check false-matches Canada (`CA`) and India (`IN`) country codes. Foreign-first wins.
- Dropped "ontario"/kept-narrow foreign tokens to avoid nuking US "Ontario, CA" /
  "Vancouver, WA"; Toronto/Montreal/Canada still catch Canadian roles.
- The title's geography REJECTS only, never grants. Some boards publish only `Distributed` as
  the location and put the real country in the title (`..., Canada`, `..., Canberra`,
  `..., Nordics`), so read the title for foreign scope before treating a generic
  distributed/remote marker as US. But a region in a title (`..., Americas`, `..., NAmer`) is a
  coverage/market descriptor — it once carried a role hybrid across four non-preferred US
  cities through as a US-remote match. Positive US scope must come from the location field.
- A remote signal says how the work is done, never where. A location field can hold a workplace
  WORD instead of a place (`Hybrid`, `In-Office`, `Distributed`, bare `remote`) with the cities
  only inside the JD; such a field carries no geography, cannot contradict an explicit JD remote
  grant (the JD is then the only statement of record), and a bare mode word is no US signal — a
  foreign agency's posting scored `us_remote` on the single word `remote`. Nor is a JD grant
  geography: "this is a remote role BUT you must reside in <Metro>" was a confident `us_remote`
  match, three of four confident matches in one live re-check. Both now resolve to `review` or
  to the metro the JD actually named. Verdict table + the two deliberate guardrails
  (`Anywhere`/`Worldwide`, `Remote (Indianapolis)`): reference.md, "When a remote signal does
  NOT grant US scope". Read those postings; never relay `review` as "no match".

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
