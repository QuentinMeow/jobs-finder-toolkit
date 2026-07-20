# Job Search — Data Sources & Heuristics Reference

Detailed reference for the `job-search` skill. Read this when adding sources,
debugging fetchers, or tuning visa detection. Endpoints verified 2026-07-10.

## Supported ATS APIs (public, no auth for reads)

### Greenhouse
- List + descriptions: `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`
- Fields used: `title`, `location.name`, `absolute_url`, `first_published`,
  `updated_at`, `content` (HTML, **double entity-encoded** — `strip_html` decodes twice).
- Posted date: prefer `first_published`, fall back to `updated_at`.

### Ashby
- List: `https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true`
- Fields used: `title`, `location`, `secondaryLocations`, `publishedAt` (ISO w/ ms),
  `descriptionPlain` (plain text), `isRemote`, `workplaceType`, `jobUrl`, `applyUrl`,
  `isListed` (skip when `false`).

### Lever
- List: `https://api.lever.co/v0/postings/{token}?mode=json`
- Fields used: `text` (title), `categories.location`, `descriptionPlain`,
  `createdAt` (epoch **ms**), `workplaceType`, `hostedUrl`.

### SmartRecruiters
- List: `https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100`
- Detail (for description): `.../postings/{id}` → `jobAd.sections.*.text`.
- Fields used: `name`, `releasedDate`, `location.{city,region,country,remote,hybrid}`.
- Note: description requires a per-posting detail call (slower).

## Finding a company's board token

The token is the slug in the company careers URL:
- `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>`
- `jobs.ashbyhq.com/<token>`
- `jobs.lever.co/<token>`
- `jobs.smartrecruiters.com/<token>`

Tokens are not always the obvious name (e.g. Glean → `gleanwork`, Scale AI →
`scaleai`, Together AI → `togetherai`, Cursor → `cursor` not `anysphere`). Probe:

```bash
curl -s "https://boards-api.greenhouse.io/v1/boards/<guess>/jobs" | head -c 200
curl -s "https://api.ashbyhq.com/posting-api/job-board/<guess>"    | head -c 200
```

## Cross-company aggregators (span many employers per query)

Implemented in `aggregators.py`. Company boards give the best signal for specific
targets; aggregators give market-wide breadth. All normalize into `JobPosting` and
feed the same filter/score pipeline.

### Keyless (default: jobicy, remoteok, themuse)
| Source | Endpoint | Notes |
|--------|----------|-------|
| Jobicy | `https://jobicy.com/api/v2/remote-jobs?count=100&geo=usa` | US remote; `jobDescription` HTML; `pubDate`. |
| RemoteOK | `https://remoteok.com/api` (User-Agent required) | Full dump; first row is a legal notice (skipped); `date`/`epoch`. |
| The Muse | `https://www.themuse.com/api/public/jobs?page=N&category=...` | US-heavy; `contents` HTML; `publication_date`; no server-side keyword search (client-filtered). |
| Arbeitnow | `https://www.arbeitnow.com/api/job-board-api?page=N` | **EU/Germany-heavy — opt-in only**; `visa_sponsorship=true` filter; `created_at` (unix s). |

### Keyed (STAGE 2, opt-in via env vars) — includes LinkedIn/Indeed coverage
Listed in a profile's `sources.extended_aggregators`; they run only under `--stage 2`
and are skipped quietly when their key env vars are absent (`keyed_available`).
| Source | Env vars | Recency param | Notes |
|--------|----------|---------------|-------|
| Adzuna | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY` (def us) | `max_days_old` | `what`/`where` keyword+location; aggregates many boards. |
| JSearch | `RAPIDAPI_KEY` (subscribe to JSearch on RapidAPI) | `date_posted` = today/3days/week/month | **Aggregates LinkedIn + Indeed + Glassdoor** via one key; `query` keyword. |

### JobSpy scraper (site-tiered across the two stages)
Scrapes Indeed / Google / LinkedIn / Glassdoor / ZipRecruiter directly
(`pip install python-jobspy`; already in the repo venv). It is split by site tier:

- **Reliable sites (`sources.jobspy.reliable_sites`, default `[indeed, google]`) run in
  STAGE 1** — free, fast (~1–2s per term×location), rarely rate-limited.
- **Extended sites (`sources.jobspy.extended_sites`, default `[linkedin]`) run in
  STAGE 2** — LinkedIn is slow, often **429/blocks**, and lists no description unless
  `linkedin_fetch_description: true`.

Location config: `sources.jobspy.locations` is a **list** of
`{location, distance, is_remote}` dicts — one scrape per entry. `distance` is a radius
in **miles** (Indeed/LinkedIn/Glassdoor/Zip honor it; Google ignores it). Example: one
entry `{location: "City, ST", distance: 40, is_remote: false}` covers the whole metro
(the anchor city plus its surrounding suburbs) and a second
`{location: "United States", is_remote: true}` adds a US-remote pass. A bare
`jobspy.location` (single string) still works as a fallback. `results_wanted`, `max_terms`
(cap query-terms × locations × sites — each combo is one scrape), and `country_indeed`
tune volume. Recency via `hours_old` (derived from `max_age_days`). Enable with
`sources.jobspy.enabled: true` or `--jobspy`; disable per run with `--no-jobspy`. Helpers:
`build_jobspy_tasks(query_terms, jobspy_cfg, sites, max_age_days)` and `keyed_available(name)`.

### Why not a direct LinkedIn/Indeed API
Neither offers a free public job-search API for third parties (partner/publisher
programs only). Use **JobSpy** (Indeed/Google free in stage 1, LinkedIn/Glassdoor in
stage 2) or **JSearch** (RapidAPI aggregator, stage 2) instead.

## AI-native / AI-transitioning company signal (`scoring.py`)

Encodes "infra role AT an AI-native company (or one transitioning to AI)". Config in the
profile's `ai_company` block. Two signals feed both an optional filter and the score:

- **`ai_company_hits(posting, profile)`** — JD-text heuristic: `ai_company.signals`
  phrases found in title+description (LLM, frontier/foundation model, GenAI, inference/
  training infra, agentic, GPU cluster, ML/AI platform, RAG, vector database, …). Works
  on EVERY source, incl. aggregator hits from companies not in the registry.
- **Registry AI-native tag** — the caller flags a posting whose company resolves (via
  `registry.tagged_keys(ai_company.company_tags)`, default `ai-lab`/`ai-infra`/`ai-native`)
  to a tagged employer; passed to `score_posting(is_ai_native_company=...)`.
- **`ai_company_ok(...)`** — hard-filter, active only when `ai_company.require` is truthy
  (`--ai-native-only`): keep a posting iff it's a registry AI-native employer OR its JD has
  ≥1 signal. Default (soft) mode keeps everything and applies only the boost.

## US / location gate

`location.us_only: true` (set in the active profile) keeps a posting if it is
US-based, matches a preferred city, or is non-foreign remote; it drops clearly-foreign
roles (e.g. "Berlin", "London, UK", "CA-Ontario-Toronto"). This matters when you need
US work authorization / sponsorship. Detection uses US state names + uppercase 2-letter
state abbreviations (from the original string) + major US hubs, and a foreign-token
list that is checked **first** so it wins over remote/abbreviation false positives.
Set `us_only: false` to allow global results, or `require_match: true` for a hard
preferred-cities/remote filter.

## Recency filter

`posted_at` is normalized to UTC from each source's timestamp
(`first_published` / `publishedAt` / `createdAt` / `releasedDate`).
`max_age_days` drops anything older. Postings with an **unknown** date are kept
and flagged (rare) rather than dropped.

## Visa sponsorship heuristic

`visa.py` classifies the JD text into `yes` / `no` / `unclear`:

- **`no`** — an explicit denial matches (e.g. "no sponsorship", "unable to sponsor",
  "authorized to work … without sponsorship", "US citizens only", "green card required").
  Negatives are kept deliberately specific so ordinary "must be authorized to work"
  boilerplate — which even sponsoring employers use — does **not** trigger a reject.
- **`yes`** — an explicit offer matches (e.g. "we sponsor", "H-1B sponsorship",
  "visa sponsorship available", "green card sponsorship", "PERM process", "cap-exempt").
- **`unclear`** — neither; most postings. Under `policy: exclude_negative` these are
  kept; under `require_positive` they are dropped.

Soft tags (`visa_tags`): `h1b_transfer_friendly` (mentions transfer / cap-exempt),
`green_card_mentioned`. These add scoring boosts, not filters.

**This is a text heuristic. Always confirm sponsorship with the employer.**

## Optional DOL sponsorship enrichment

For a stronger visa signal, build an employer index from DOL disclosure data (real H-1B LCA +
PERM filings). This is optional and adds a scoring boost for employers with sponsorship history.
`search_jobs.py` auto-loads `data/sponsors.json` when present.

```bash
.venv/bin/python -m pip install openpyxl   # one-time
# download quarterly XLSX from dol.gov/agencies/eta/foreign-labor/performance
.venv/bin/python .agents/skills/job-search/scripts/build_sponsor_index.py \
    --lca LCA_Disclosure_Data_FY2025_Q4.xlsx --perm PERM_Disclosure_Data_FY2025.xlsx
```

`build_sponsor_index.py` parses DOL OFLC disclosure XLSX files into
`data/sponsors.json` = `{normalized_employer: {"h1b": n, "perm": n}}`.

- Source page: https://www.dol.gov/agencies/eta/foreign-labor/performance
- LCA file (H-1B/H-1B1/E-3): `LCA_Disclosure_Data_FY<YYYY>_Q<n>.xlsx` (large, ~80MB)
- PERM file (green card): `PERM_Disclosure_Data_FY<YYYY>.xlsx`
- Employer name join is fuzzy (`_norm_company` strips Inc/LLC/Labs/AI/etc.); matches
  are approximate — treat the boost as a weak signal, not proof.

## Scoring summary (see `scoring.py`)

| Signal | Effect |
|--------|--------|
| Strong keyword in title | +8 each |
| Strong keyword in description | +4 each |
| Good keyword in description | +1.5 each |
| Negative keyword (honest mis-fit) | −4 each |
| AI-native company (registry tag) | +`company_boost` (default +6) |
| AI-company JD signal | +`boost_per_hit` each (default +2), capped at `max_boost` (default +10) |
| Staff/Senior title (if targeted) | +3–4 |
| Visa `yes` | +15 |
| `h1b_transfer_friendly` tag | +5 |
| DOL employer history (if index present) | up to +10 |
| Preferred location | +5 |
| Remote/hybrid | +3 |
| Posted < 24h | +3 |

## Adding more sources

New aggregators (e.g. USAJobs, Careerjet, Jooble, Findwork, HN "Who is hiring" via
the Algolia API) can be added by writing a fetcher in `aggregators.py` that returns
`JobPosting` objects and registering it in `KEYLESS`/`KEYED`. Read any credentials
from environment variables (never commit keys). The existing filter/score pipeline
then applies automatically.

## Pipeline overview

Three kinds of sources feed one pipeline, split across two stages:

```
 STAGE 1 (reliable, every run)              profiles/<label>.yaml (criteria)
   company ATS boards (companies.yaml)               │
 + keyless aggregators (Jobicy/RemoteOK/Muse)        │
 + JobSpy Indeed/Google (radius + remote)            ▼
 STAGE 2 (--stage 2, opt-in)  ──►  normalize ──► filter (title·US/location·visa·
 + JobSpy LinkedIn/Glassdoor                          │        YOE·AI-native)
 + keyed Adzuna/JSearch (if keys)   fetch (threaded)  │
        │                          ─────────────►     ▼
        ▼               score vs profile (+AI-native) ──► dedupe ──► markdown + json
```

1. **Company ATS boards** (stage 1) — public, no-auth APIs (Greenhouse, Ashby,
   Lever, SmartRecruiters, Workday, Amazon/Apple/Meta), one entry per company in
   `companies.yaml`, selected by `tags`. Best signal for specific target companies.
2. **Cross-company keyword aggregators** — one query spans thousands of employers:
   - **Keyless (stage 1, default): Jobicy, RemoteOK, The Muse** (Arbeitnow is
     EU-heavy, opt-in).
   - **Keyed (stage 2, opt-in via env): Adzuna, JSearch** — JSearch aggregates
     **LinkedIn + Indeed + Glassdoor** through one RapidAPI key. They activate only
     when their keys are set (missing keys are skipped quietly, no error).
3. **JobSpy direct-market scraper** — pulls straight from the job boards, split by
   site tier: **reliable sites (Indeed + Google) run in stage 1**; **extended sites
   (LinkedIn, Glassdoor) run in stage 2**. Supports **radius search** (`distance`
   miles) and a **list of locations** — so one run targets your preferred metro
   (e.g. a "City, ST" anchor @ 40mi covers the surrounding suburbs) AND a
   US-remote pass. Needs `pip install python-jobspy` (already installed in the venv);
   LinkedIn is slow and often 429s, which is why it's stage 2.

- **Filters**: title gate, optional `max_years_experience` (drops JDs only when a
  high-confidence general required-YOE minimum exceeds the cap; preferred or
  tool-specific/contextual YOE is display-only), US/location gate (`us_only` drops clearly-foreign roles —
  important when you need US sponsorship), visa policy, an optional **AI-native gate**
  (`--ai-native-only`), plus a **blacklist + already-considered + recently-searched**
  skip (§ Skip logic).
- **AI-native company fit**: postings get a score boost when the company is a
  registry AI-native employer (tagged `ai-lab`/`ai-infra`/`ai-native`) OR the JD text
  reads AI-native/AI-transitioning (LLM, frontier/foundation model, GenAI, inference/
  training infra, agentic, GPU cluster, …). Soft by default (keeps breadth); pass
  `--ai-native-only` to hard-filter to AI-native/AI-transitioning employers.
- **Level fit**: a posting whose parsed Google-equivalent level sits *outside* the
  profile's `seniority.target` band is demoted (per ladder step, `seniority.fit_weight`,
  default 6.0; `0` disables), so a `[mid, senior]` search isn't topped by staff+/entry
  roles. In-band and unknown levels are untouched. Optionally set `years_experience`
  (with `seniority.yoe_fit_weight`) to also demote roles whose required YOE over-reaches.
- **Shortlist diversity**: the ranked top-K applies a per-employer cap
  (`diversity.max_per_company`, default 3; `--max-per-company N`, `0` disables) so a
  single company with many open reqs can't dominate; thin searches still backfill to
  the full top-K.
- **Posting age is NOT filtered by default.** `max_age_days` is opt-in (`null` in the
  default profile): an open role is worth considering regardless of when it was posted.
  Pass `--max-age-days N` (or set a number in the profile) only when you specifically
  want "what was posted in the last N days". Do **not** confuse this with the 7-day
  **company re-search** window (`company_search_log.skip_within_days`) below — that skips
  a company you already fully searched recently, and has nothing to do with posting age.
- **Visa**: JD text is scanned for sponsorship signals (§ Visa sponsorship heuristic).
  Labels are `yes` / `no` / `unclear` and are **heuristic — always confirm with the employer**.
- **Output**: `<discoveries_dir>/<YYYYMMDD>-<profile>.md` (ranked table with match
  reasons plus normalized level, required YOE, posted salary/total compensation, and an
  approximate Google-equivalent level range). The discoveries dir is config-derived
  (`config.discoveries_dir()`, `applications/1_discoveries/` by default).

> **LinkedIn / Indeed have no free official API.** The realistic routes are the
> **JobSpy scraper** (free; Indeed/Google in stage 1, LinkedIn/Glassdoor in stage 2)
> or **JSearch** (RapidAPI aggregator, one key — stage 2). Indeed via JobSpy is the
> reliable default; LinkedIn and keyed APIs are stage 2 (§ Stage 2 setup).

A stage-1 market-scan run scans ~12k postings (100+ boards + keyless aggregators +
JobSpy Indeed/Google) in ~15–20s; stage 2 adds LinkedIn + keyed APIs and is slower.

## Search flags

All overrides beat profile values (`search_jobs.py`):

```bash
# STAGE 2: also LinkedIn/Glassdoor (JobSpy) + keyed Adzuna/JSearch (only if keys set)
... --profile example --stage 2

# only AI-native / AI-transitioning employers (hard filter, not just a boost)
... --profile example --ai-native-only

# widen/narrow the freshness window / change ranking depth
... --profile example --max-age-days 3 --top-k 30

# quick run: skip the JobSpy scraper (company boards + keyless aggregators only)
... --profile example --no-jobspy

# only postings that EXPLICITLY offer sponsorship (stricter)
... --profile example --visa-policy require_positive

# restrict to specific company tags from companies.yaml
... --profile example --company-tags ai-lab,ai-infra,ai-native

# choose KEYLESS aggregators explicitly (override profile)
... --profile example --aggregators jobicy,remoteok,themuse

# aggregators only, skip company boards
... --profile example --no-companies

# also emit machine-readable JSON
... --profile example --json-out /tmp/matches.json

# re-search companies logged within the last 7 days (still skips blacklist)
... --profile example --include-recent

# RE-FILTER the last fetch instead of re-fetching: widen the window, change top-k,
# or re-emit JSON in seconds (fetch-affecting flags like --stage/--aggregators refused)
... --profile example --refilter latest --max-age-days 7 --top-k 60
```

## Skip logic (blacklist + already-considered + recently-searched)

`search_jobs.py` filters results against the canonical company registry
(`companies.yaml`) plus two logs under `<applications_root>/0_profile/` (config-derived
via `config.applications_root()`, `applications/` by default). Company identity for all
three checks is resolved through the registry (`scripts/registry.py`), so a board's
canonical name matches a log/blacklist entry written under an alias or ATS token (e.g.
`Arize` == `Arize AI` == `arizeai`). Companies absent from the registry fall back to
their normalized name, so aggregator-only employers still match.

- **Blacklist (in `companies.yaml`)** — every posting from a registry entry carrying a
  `blacklist:` reason (matched on the company's name, aliases, or ATS token) is dropped.
  Always applied. Blacklisted companies we never poll are identity-only rows (no
  `ats`/`token`).
- **`applications-log.yaml`** — postings already generated/considered are dropped, matched
  by URL, else by `(company, role)`. This is auto-generated from every application folder
  by `.agents/skills/application-tracker/scripts/status.py --sync-log`; keep it fresh so searches don't
  re-surface work you've already done. A *new* role at an already-applied company still surfaces (only the exact
  posting is skipped).
- **`company-search-log.yaml`** — after the above, postings from companies whose **last
  successful search** is within `skip_within_days` (default **7**, read from the file) are
  dropped. A successful search means the company's full board was enumerated and you made an
  application decision (created folder(s) **or** decided no suitable role). Browsing-only or
  unreachable boards are **not** logged. `created` rows are upserted by `--sync-log`; record
  `no_suitable` with `--log-search` (see `AGENTS.md`).

The run prints how many postings it skipped (`Skipped N blacklisted + M already-considered +
K recently-searched`) and notes the counts in the output header. Pass `--include-considered`
to re-surface already-logged postings; pass `--include-recent` to ignore the company search
log (blacklist still applies). Override the window with `--search-log-skip-days N` or
`company_search_log.skip_within_days` in the profile.

## Stage 2 setup: LinkedIn/Glassdoor + keyed aggregators

There is no free official LinkedIn/Indeed API. The skill covers them via the
JobSpy scraper and (optionally) keyed aggregators, split across the two stages:

- **Indeed + Google (JobSpy) — STAGE 1, on by default in a market-scan style profile.**
  Free, no key, fast, rarely rate-limited. Configured under `sources.jobspy`
  (`reliable_sites`, `locations` with radius, `results_wanted`, `max_terms`). This is
  the reliable market-wide, direct-from-board layer that runs every use case.
- **LinkedIn + Glassdoor (JobSpy) — STAGE 2 (`--stage 2`).** `sources.jobspy.extended_sites`.
  Slower and often 429s; keep `max_terms` modest. LinkedIn lists no description unless
  `linkedin_fetch_description: true` (much slower).
- **JSearch (aggregates LinkedIn + Indeed + Glassdoor) — STAGE 2.** Subscribe on
  RapidAPI, then it activates automatically in stage 2 (listed in
  `sources.extended_aggregators`):
  ```bash
  export RAPIDAPI_KEY=...
  ... --profile example --stage 2
  ```
- **Adzuna (aggregator) — STAGE 2.** Free key at developer.adzuna.com:
  ```bash
  export ADZUNA_APP_ID=... ADZUNA_APP_KEY=...
  ... --profile example --stage 2
  ```

Keys are read from environment variables and never stored in the repo. Stage 2
keyed aggregators whose keys are missing are skipped quietly (no error).

## AI-native company tagging

The profile's `ai_company` block encodes "Kubernetes/infra role **AT an AI-native
company** (or one transitioning to AI)". Two complementary signals (scoring model in
§ AI-native / AI-transitioning company signal):

- **Registry tag** — a posting whose company is tagged `ai-lab`/`ai-infra`/`ai-native`
  in `companies.yaml` gets `ai_company.company_boost`. Works for boards AND aggregator
  hits whose employer is in the registry (e.g. Databricks, NVIDIA, CoreWeave).
- **JD-text heuristic** — each `ai_company.signals` phrase found in the JD (LLM,
  frontier/foundation model, GenAI, inference/training infra, agentic, GPU cluster, …)
  adds `boost_per_hit` up to `max_boost`. Source-agnostic, so fresh Indeed/LinkedIn
  hits from companies NOT in the registry still surface when the JD reads AI-native.

Default is a **soft boost** (keeps breadth). To **hard-filter** to AI-native /
AI-transitioning employers only, pass `--ai-native-only` (or set
`ai_company.require: true` in the profile). Add an `ai-native` tag to a company in
`companies.yaml` when it's AI-first but its primary tag is something else
(e.g. Replit/Warp = `dev-tools`, Waymo/Zoox = `consumer`, Palantir = `data-platform`).

## Managing target companies

`companies.yaml` is the canonical company registry — the single source of truth for
company identity, ATS poll config, `tags`, and the blacklist. To add a company to poll,
find its ATS board slug (the path segment in its careers URL, e.g.
`boards.greenhouse.io/<slug>`, `jobs.ashbyhq.com/<slug>`, `jobs.lever.co/<slug>`),
add an entry with `tags`, then validate:

```bash
.venv/bin/python .agents/skills/job-search/scripts/validate_companies.py
```

Fix or remove any `FAIL`/`EMPTY` entries. Re-run periodically since boards move.

**To blacklist a company** (never consider it), add a `blacklist: "<reason>"` key to its
entry. If you don't poll it, add an identity-only row with just `name`, `aliases`, and
`blacklist:` (omit `ats`/`token`); `validate_companies.py` and the fetch pipeline skip
rows without `ats`. Add `aliases` only where an aggregator's company name differs from
the board name (the resolver already derives match keys from `name` + `token`).

## Leveling cache — reusable company leveling + compensation

Keep reusable leveling research separate from `companies.yaml`: that registry owns stable
identity/polling data, while level mappings and compensation are approximate and dated.
The active cache is `config.company_levels_path()` (by default
`company-levels.yaml` beside the configured profile; the public example is
`examples/profile/company-levels.example.yaml`).

This reference cache is a **separate, richer** database from the flat application
`meta.yaml`: it keeps `schema_version: 2` (the company-levels cache file format — a different
file from `meta.yaml`, whose only supported schema is v3) with per-fact provenance so its
sourced facts stay auditable. Application enrichment consumes it only for **level/YOE** (the normalized
seniority word and approximate Google-equivalent float range) when a posting omits them;
the flat `meta.yaml` salary always comes from the posting itself (USD/year). Resolution
order within the cache is `live_jd > employer_official > market_benchmark >
generic_heuristic`; explicit `manual_override: true` wins, otherwise higher-tier or fresher
same-tier facts refresh older data. For popular companies, store each employer level's
aliases/title patterns, normalized seniority, approximate Google-equivalent float range,
typical required-YOE range, and optional base/stock/bonus/total-compensation ranges as
distinct facts—never derive total. Every fact records provider, URL, retrieval date,
geography, confidence, method, sample size/statistic when available, and access/licensing
method. Keep geographic bands separate under `bands` with `location_patterns`.

Import only user-supplied/licensed files; the importer never fetches the web:

```bash
# Dry run by default; accepts normalized YAML, JSON, or CSV. DEST = config.company_levels_path().
.venv/bin/python scripts/maintenance/import_company_levels.py INPUT <DEST>
# Persist only after review:
... --write
```

Never schedule or implement public Levels.fyi scraping. Automated Levels.fyi imports
require a user-supplied licensed export or licensed API access recorded in provenance.
Employer postings are the first source; employer-authored ladders are second.
