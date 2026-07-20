---
name: job-search
visibility: public
description: Discover and rank fresh job postings that match a candidate profile, filtering by role, keywords, location, recency, and visa sponsorship (H-1B transfer / PERM / green card). Use when the user asks to find, search for, or discover matching jobs, check what's newly posted, or filter openings by sponsorship or posting date.
---

# Job Search Skill

Fetch live job postings from many sources at once — 100+ company ATS boards, plus
market-wide keyword aggregators, plus **direct-from-market boards (Indeed/Google,
and LinkedIn/keyed APIs in stage 2)** — filter them against a reusable
**job-matching profile** (role titles, keywords, location + radius, recency,
US/visa policy, **AI-native-company fit**), score and rank them, and write a
ranked shortlist the user can act on with the `resume-writer` and
`application-tracker` skills.

**Two search stages** (see "How It Works"):
- **Stage 1 — reliable tier (default, every use case):** company ATS boards +
  keyless aggregators + JobSpy on Indeed/Google. Free, no API keys, fast (~15–20s),
  rarely rate-limited. This is the market-wide, time-sensitive baseline.
- **Stage 2 — extended tier (`--stage 2`, opt-in):** everything in stage 1 plus
  JobSpy on LinkedIn/Glassdoor and keyed aggregators (Adzuna/JSearch) that activate
  only when their API keys are set.

## When to Use

Use this skill when the user asks to:
- Find or discover jobs matching their background
- See what's been posted recently (e.g. "in the last 3 days")
- Filter openings by visa sponsorship (H-1B transfer, PERM / green card)
- Filter by role, seniority, location, remote, or specific companies
- Refresh their target-company shortlist

## Before You Start

1. Read `AGENTS.md` for repo guardrails (traceability, no fabrication).
2. Read this skill's `LESSONS.md` for operational knowledge.
   - **Personalization / private overrides:** if this skill folder has a
     `references_private/` directory, read every file in it — those candidate-specific
     notes and examples OVERRIDE the generic examples in this SKILL.md. When it is
     absent (public / example mode), use the generic examples here and take all
     candidate specifics from `config` and the profile.
3. Confirm the profile: profiles live in `profiles/<label>.yaml` (default:
   `config.job_search.default_profile`). If the user wants different criteria, edit or
   copy a profile — do NOT hardcode criteria into scripts.
4. This skill only surfaces postings with a real `source` + `url`. Never invent
   a posting; every row must be traceable to a fetched listing.
5. **Scratch stays in `tmp/`** — ATS/API probe scripts in `tmp/ats_scripts/`, fetched
   career-page HTML/JSON in `tmp/web_artifacts/`; never the repo root or this skill's
   `scripts/`. If a probe proves reusable, promote it into `scripts/`. See `AGENTS.md` →
   "Scratch & Temporary Files".
6. **Subagent cap:** at most **8 subagents total** per request — see `AGENTS.md` →
   "Subagent Budget".

## How It Works

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

Three kinds of sources feed one pipeline, split across two stages:

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
  skip (see below).
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
- **Visa**: JD text is scanned for sponsorship signals (see `reference.md`). Labels
  are `yes` / `no` / `unclear` and are **heuristic — always confirm with the employer**.
- **Output**: `<discoveries_dir>/<YYYYMMDD>-<profile>.md` (ranked table with match
  reasons plus normalized level, required YOE, posted salary/total compensation, and an
  approximate Google-equivalent level range). The discoveries dir is config-derived
  (`config.discoveries_dir()`, `applications/1_discoveries/` by default).

> **LinkedIn / Indeed have no free official API.** The realistic routes are the
> **JobSpy scraper** (free; Indeed/Google in stage 1, LinkedIn/Glassdoor in stage 2)
> or **JSearch** (RapidAPI aggregator, one key — stage 2). Indeed via JobSpy is the
> reliable default; LinkedIn and keyed APIs are stage 2 (see below).

## Skipping blacklisted + already-considered + recently-searched postings

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

## Workflow: Run a Search

### Step 1 — Pick / confirm the profile and filters

The default profile (`config.job_search.default_profile`) encodes the candidate's
requirements — edit `profiles/<label>.yaml` to change any of them:
**location** governed by the configured location policy (`config.location_policy()`:
`require_match` + `allow_remote` + `us_only`); **roles** the candidate's target titles
(with keyword scoring on the same themes); **seniority** the allowed band (e.g.
staff+/principal/manager titles excluded); **experience** drop JDs that state a minimum
above `max_years_experience` (keep if unstated); and **visa** the candidate's
sponsorship policy (e.g. `policy: exclude_negative` when sponsorship is required).
**Posting age is not filtered** (`max_age_days: null`) — every currently-open matching
role is considered regardless of post date; pass `--max-age-days N` only for an explicit
"posted in the last N days" run. (The only default 7-day window is
`company_search_log.skip_within_days`, which skips companies already searched in the last
7 days — not posting age.) To change scope, edit `profiles/<label>.yaml` or pass overrides.

### Step 2 — Run the search

```bash
# Run your configured default profile (evergreen company-board sweep; the shipped
# demo profile is `example` — replace with your own label):
.venv/bin/python .agents/skills/job-search/scripts/search_jobs.py --profile example

# A WIDENED market-scan style profile adds keyless aggregators + JobSpy Indeed/Google
# (your preferred metros @40mi + US-remote), last 7 days, AI-native boost; build one
# from profiles/_TEMPLATE.yaml:
.venv/bin/python .agents/skills/job-search/scripts/search_jobs.py --profile example
```

Common overrides (flags beat profile values):

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
```

The script prints the ranked table and writes it to the configured discoveries dir
(`config.discoveries_dir()`; `<discoveries_dir>/<YYYYMMDD>-<profile>.md`). A
stage-1 market-scan run scans ~12k postings (100+ boards + keyless aggregators +
JobSpy Indeed/Google) in ~15–20s; stage 2 adds LinkedIn + keyed APIs and is slower.

## LinkedIn / Indeed Coverage (the two stages)

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

## AI-native / AI-transitioning company fit

The profile's `ai_company` block encodes "Kubernetes/infra role **AT an AI-native
company** (or one transitioning to AI)". Two complementary signals:

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

### Step 3 — Present results

Show the top matches with company, title, score, level/Google-equivalent range, required
YOE range, salary, total compensation, age, visa label, and *why* each matched. `?` means
the posting/reference did not provide the fact; never fill it from guesswork. Call out visa
`unclear` rows as needing confirmation. Group or highlight by fit if helpful.

### Step 4 — Hand off to the pipeline

When the user picks a posting, hand off:
- **`resume-writer`** → create `applications/6_drafted/<slug>/` with `meta.yaml` at the root
  and the generation inputs in `source/` (one `source/JD-<job title>.md` per posting plus
  `source/tailored.yaml`), then tailor. `meta.yaml` is always `job_metadata_schema_version: 3`
  with a uniform **`jobs:` list — one entry per posting, even a single role.** Record each
  posting's **`location`**, `url`, and `posted_date` in its `jobs:` entry — only hand off
  postings that passed the location filter (per `config.location_policy()`). Carry the search
  result's per-posting `workplace`, `sponsorship`, `job_level`, `required_yoe`, and
  `salary_range` (the structured facts are the flat `{min, max, confidence, source}` shape;
  `workplace` and `sponsorship` are single words) into that posting's `jobs:` entry, then run
  `status.py --enrich-metadata <folder>` after saving the full JD to fill any missing
  facts and consult the reusable company cache for level/YOE. After creating the draft,
  run `.agents/skills/application-tracker/scripts/status.py --sync-log` so this posting is added to
  `applications-log.yaml` and the company is recorded in `company-search-log.yaml`, then
  confirm the draft with `.agents/skills/application-tracker/scripts/status.py --check-locations`.
  Every `jobs:` entry must carry an exact `jd_file`; never pair roles and JDs by index or
  sorted filename.
- If you reviewed a company's board and decided **no suitable role**, record it:
  `.venv/bin/python .agents/skills/application-tracker/scripts/status.py --log-search "<Company>" --outcome no_suitable`
- **`application-tracker`** → record metadata; the user moves the folder to
  `applications/5_applied/` once submitted (status is the folder).

## Managing Target Companies

`companies.yaml` is the canonical company registry — the single source of truth for
company identity, ATS poll config, `tags`, and the blacklist. To add a company to poll,
find its ATS board slug (the path segment in its careers URL, e.g.
`boards.greenhouse.io/<slug>`, `jobs.ashbyhq.com/<slug>`, `jobs.lever.co/<slug>`),
add an entry with `tags`, then validate:

```bash
.venv/bin/python .agents/skills/job-search/scripts/validate_companies.py
```

Fix or remove any `FAIL`/`EMPTY` entries. Re-run periodically since boards move.

### Reusable company leveling + compensation reference

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

### Re-check a single company's live board (location verdict)

To re-search **one** employer — e.g. to decide whether a drafted application still has a
policy-matching role, or should be moved to `ignored/` — use `company_roles.py`.
It fetches that company's live ATS board and prints every open posting with the
location verdict from this skill's vendored `_vendor/location.py` (a byte-identical copy of
the toolkit's `scripts/shared/location.py` — the same location policy the profile enforces
via `config.location_policy()`). It does **not** apply the role/seniority/visa title gate — it lists everything so
you can judge role fit yourself, and its remote signal is a heuristic (some ATSs, e.g.
SmartRecruiters, over-report `remote`), so always confirm a candidate's true location from
the actual posting/JD before acting.

```bash
# Company already in companies.yaml (resolve by name / alias / token)
.venv/bin/python .agents/skills/job-search/scripts/company_roles.py --name Anyscale
# Only the postings that match the configured location policy
.venv/bin/python .agents/skills/job-search/scripts/company_roles.py --name Sentry --match-only
# Ad-hoc company not in the registry (derive ats+token from its careers URL)
.venv/bin/python .agents/skills/job-search/scripts/company_roles.py \
    --company CodeRabbit --ats ashby --token coderabbit
# Dump one posting's full JD text (for writing source/JD-<title>.md)
.venv/bin/python .agents/skills/job-search/scripts/company_roles.py --name Sentry --jd "Control Plane"
```

**To blacklist a company** (never consider it), add a `blacklist: "<reason>"` key to its
entry. If you don't poll it, add an identity-only row with just `name`, `aliases`, and
`blacklist:` (omit `ats`/`token`); `validate_companies.py` and the fetch pipeline skip
rows without `ats`. Add `aliases` only where an aggregator's company name differs from
the board name (the resolver already derives match keys from `name` + `token`).

## Optional: Employer Sponsorship History (DOL)

For a stronger visa signal, build an employer index from DOL disclosure data
(real H-1B LCA + PERM filings). This is optional and adds a scoring boost for
employers with sponsorship history:

```bash
.venv/bin/python -m pip install openpyxl   # one-time
# download quarterly XLSX from dol.gov/agencies/eta/foreign-labor/performance
.venv/bin/python .agents/skills/job-search/scripts/build_sponsor_index.py \
    --lca LCA_Disclosure_Data_FY2025_Q4.xlsx --perm PERM_Disclosure_Data_FY2025.xlsx
```

`search_jobs.py` auto-loads `data/sponsors.json` when present. See `reference.md`.

## Files

| Path | Purpose |
|------|---------|
| `profiles/<label>.yaml` | Search criteria (roles, keywords, location + radius, visa, recency, `ai_company`, `sources`/stage config); the default label comes from `config.job_search.default_profile` |
| `profiles/<label>.yaml` | Your own search profiles. Two useful styles: an **evergreen company-board sweep** (JobSpy off, no posting-age filter, AI-native soft boost) and a **widened two-stage market scan** (JobSpy Indeed/Google over your preferred metros @40mi + US-remote, last 7 days; `--stage 2` adds LinkedIn + keyed APIs) |
| `profiles/example.yaml` | Generic general-software-engineer example profile (copy + tune) |
| `profiles/_TEMPLATE.yaml` | Template for a new profile |
| `companies.yaml` | Canonical company registry — identity, ATS poll config, tags (incl. the `ai-lab`/`ai-infra`/`ai-native` AI-native family), blacklist |
| `config.company_levels_path()` | Dated reusable company level/YOE/base/total-comp reference; defaults beside the configured profile and stays separate from the identity registry |
| `scripts/registry.py` | Registry loader + resolver (canonical name, blacklist, poll targets, `tagged_keys` for the AI-native set) |
| `scripts/search_jobs.py` | Main pipeline (two-stage fetch → filter → score → rank → output); `--stage`, `--ai-native-only`, `--no-jobspy`, `--max-per-company`, `--top-k` |
| `scripts/sources.py` | Company ATS fetchers (Greenhouse / Ashby / Lever / SmartRecruiters / Workday / Amazon / Apple / Meta) |
| `scripts/aggregators.py` | Cross-company sources (Jobicy/RemoteOK/Muse/Arbeitnow keyless; Adzuna/JSearch keyed) + JobSpy (site-tiered, radius + multi-location); `build_jobspy_tasks`, `keyed_available` |
| `scripts/visa.py` | Sponsorship phrase detection |
| `scripts/scoring.py` | Filters + scoring (incl. `ai_company_hits`/`ai_company_ok` + AI-native-company boost) |
| `scripts/validate_companies.py` | Check that company tokens still resolve (skips identity-only rows) |
| `scripts/company_roles.py` | Re-check ONE company's live board with a location-policy verdict (single-company re-search + JD dump) |
| `scripts/build_sponsor_index.py` | Optional DOL sponsorship enrichment |
| `scripts/_vendor/{location,config,layout,job_metadata}.py` | **Generated** byte-identical copies of `scripts/shared/{location,config,layout,job_metadata}.py` (keep this skill self-contained; `config.py` supplies paths and `job_metadata.py` extracts/validates the structured handoff fields). Do not edit — regenerate with `scripts/vendoring/sync_vendored.py`; see `scripts/_vendor/README.md` |
| `reference.md` | Data-source endpoints, field notes, visa-phrase rationale |
| `<applications_root>/0_profile/company-search-log.yaml` | Last successful full-company search per employer (config-derived path under `config.applications_root()/0_profile/`; 7-day default skip; see above) |

## Guardrails

- **Profiles hold criteria, scripts stay generic.** Tune `profiles/*.yaml`; don't
  bake a person's criteria into code.
- **Visa detection is advisory.** `yes`/`no`/`unclear` come from text heuristics;
  always tell the user to confirm sponsorship with the employer.
- **No fabricated postings.** Every result must carry a real `source` + `url`.
- **Respect the sources.** Public read APIs only; keep the default company set
  modest and don't hammer endpoints (the script fetches once per run).
- **Self-contained skill.** Scripts here import their siblings and the vendored
  `_vendor/` copy only — never repo-root toolkit Python. To change the location rule,
  edit `scripts/shared/location.py` and run `scripts/vendoring/sync_vendored.py`; never
  edit `scripts/_vendor/location.py` directly (the pre-commit drift check will reject it).
