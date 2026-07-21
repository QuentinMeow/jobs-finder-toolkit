---
name: job-search
visibility: public
description: Discover and rank fresh job postings that match a candidate profile, filtering by role, keywords, location, recency, and visa sponsorship (H-1B transfer / PERM / green card). Use when the user asks to find, search for, or discover matching jobs, check what's newly posted, or filter openings by sponsorship or posting date.
---

# Job Search Skill

Fetch live job postings from many sources at once — 100+ company ATS boards, market-wide keyword
aggregators, and direct-from-market boards (Indeed/Google; LinkedIn + keyed APIs in stage 2) —
filter them against a reusable **job-matching profile** (role titles, keywords, location + radius,
recency, US/visa policy, AI-native-company fit), score and rank them, and write a ranked shortlist
the user can act on with the `resume-writer` and `application-tracker` skills.

**Two stages.** **Stage 1 (default, every run):** company ATS boards + keyless aggregators
(Jobicy/RemoteOK/Muse) + JobSpy on Indeed/Google — free, no API keys, fast (~15–20s), rarely
rate-limited; the market-wide, time-sensitive baseline. **Stage 2 (`--stage 2`, opt-in):**
everything in stage 1 plus JobSpy on LinkedIn/Glassdoor and keyed aggregators (Adzuna/JSearch)
that activate only when their API keys are set. Pipeline internals, per-source endpoints, and
Stage-2 key setup live in `reference.md`.

## When to Use

Use this skill when the user asks to:
- Find or discover jobs matching their background
- See what's been posted recently (e.g. "in the last 3 days")
- Filter openings by visa sponsorship (H-1B transfer, PERM / green card)
- Filter by role, seniority, location, remote, or specific companies
- Refresh their target-company shortlist

For a single named company's live board (not a market search), jump to **Re-check one company**.

## Quickstart: Run a Search

This is the complete routine path — an ordinary search needs nothing below it.

**Generation mode.** Read `config.generation_mode()` — `token_saving` (default) or `full`.
- **token_saving (default)** *is* this routine path — run the pipeline directly (no search
  subagent for a routine run), `--refilter` the snapshot to widen/re-emit instead of re-fetching,
  scope the run to the profile(s) asked for, and add no unprompted extra sweeps.
- **full (opt-in)** lifts those discretionary caps — a search subagent that investigates anomalies
  and reads pipeline source when results look wrong, deeper multi-source verification, and
  second-profile / additional-market sweeps **when the user asks**.
- **Hard gates are IDENTICAL in both modes and never relax:** blacklist + already-considered +
  recently-searched skip logic, the location gate, `meta.yaml` schema validation on handoff,
  no-fabricated-postings, and JD-text verification before handoff run the same regardless of mode.
  Mode changes how much *context and iteration* you spend, never which *checks* run.
- A user's explicit instruction in the moment outranks the config mode (either direction). Never self-escalate to `full` — the mode changes only via config or an explicit user request.

### Before you start
1. Read `AGENTS.md` (traceability, no fabrication) and this skill's `LESSONS.md` (hard-won
   operational edge cases — visa phrasing, title/location false-matches, source noise). The
   lessons bind at the steps below. Don't re-read files already in your context.
2. **Private overrides:** if this skill folder has a `references_private/` directory, read every
   file in it — those candidate-specific notes OVERRIDE the generic examples here. When it is
   absent (public / example mode), take all candidate specifics from `config` and the profile.
3. **Never invent a posting.** Every surfaced row must trace to a fetched listing with a real
   `source` + `url`; use `?` for any fact the posting did not provide, never a guess.
4. **Scratch stays in `tmp/`** — probe scripts in `tmp/ats_scripts/`, fetched HTML/JSON in
   `tmp/web_artifacts/`; never the repo root or `scripts/`. See `AGENTS.md` → "Scratch & Temporary
   Files".
5. **Subagent cap: at most 8 subagents total** per request — see `AGENTS.md` → "Subagent Budget".

### Step 1 — Confirm the profile and filters
Profiles live in `profiles/<label>.yaml`; the default is `config.job_search.default_profile`
(shipped demo: `example`). The profile — not the script — holds all criteria: **location**
(`config.location_policy()`: `metro` + `allow_us_remote` + `us_only`; the profile's own `location:` block adds `preferred`/`allow_remote`/`require_match`), **roles/keywords**,
**seniority** the allowed band, **experience** (drop JDs stating a minimum above
`max_years_experience`; keep if unstated), and **visa** policy (e.g. `policy: exclude_negative`
when sponsorship is required). To change scope, edit `profiles/<label>.yaml` or pass a flag
override — never hardcode criteria into scripts. Scope the run to the profile(s) the user asked
for; add no unprompted extra sweeps.

- **Seniority band:** a `[mid, senior]` profile demotes staff+/principal/manager/entry titles
  (per-step `seniority.fit_weight`, default 6.0; `0` disables) so they can't top the list.
  `exclude_neutralize` (e.g. `member of technical staff`) strips a phrase BEFORE the exclude
  check runs, so **Member of Technical Staff — the IC title OpenAI/Anthropic/Perplexity use — is
  KEPT, not dropped as "staff"** (MTS is NOT staff-level). If a user conflates the word "staff"
  with staff-level seniority, explain the distinction rather than dropping every "staff" title.
- **Posting age is OFF by default** (`max_age_days: null`): every currently-open matching role
  counts regardless of post date. Pass `--max-age-days N` only for an explicit "posted in the last
  N days" run. Do **not** confuse this with the 7-day **company re-search** window
  (`company_search_log.skip_within_days`), which skips companies you already fully searched
  recently — it has nothing to do with posting age.
- Each run also skips **blacklisted + already-considered + recently-searched** companies (identity
  resolved through the registry); the counts print in the run summary. `--include-considered` /
  `--include-recent` override; the blacklist always applies. Detail: `reference.md` § Skip logic.

### Step 2 — Run the search
```bash
# Stage 1 (default): your configured profile (the shipped demo profile is `example`)
.venv/bin/python .agents/skills/job-search/scripts/search_jobs.py --profile example
```
Default stdout is a ~5-line run summary + a compact top-K table (rank, company, title, score,
level, age, visa, URL). **Read that table — do not `cat` the discoveries file.** The full Markdown
report is written to `<discoveries_dir>/<YYYYMMDD>-<profile>.md` (`config.discoveries_dir()`,
`applications/1_discoveries/` by default). Use `--print-full` for the full-report stdout dump
**only** when the user asks for it or a validation needs it.

**Filter-variant gate.** A normal search never silently discards contradictory or unclassified
high-stakes evidence: it preserves those postings in the `Review:` JSON path printed in the run
summary. After every fresh fetch (and after a refilter used to make a final shortlist), run the
deterministic snapshot audit on the printed `Snapshot:` path:
```bash
.venv/bin/python .agents/skills/job-search/scripts/validate_filter_variants.py \
  --snapshot tmp/search_cache/<printed-snapshot>.json --profile example
```
Known location/workplace, sponsorship, title/seniority, and YOE shapes pass without AI. Exit 1
means the report under `tmp/filter_variant_reports/` contains a new or conflicting structural
variant: verify it against the real JD, update the deterministic classifier, and add only a
fictional minimal regression to `filter_variants/corpus.yaml` before relying on that filter.

Every fetch also writes a pre-filter snapshot to `tmp/search_cache/` (gitignored). **To widen the
freshness window, change top-k, or re-emit JSON after a search, re-filter — never re-fetch:**
```bash
# reuses the snapshot, anchors posting age to its fetch time; refuses snapshots >6h old (--allow-stale)
... --profile example --refilter latest --max-age-days 7 --top-k 60 --json-out /tmp/m.json
```
Widen the freshness window stepwise this way. `--refilter` refuses fetch-affecting flags
(`--stage`/`--aggregators`) — those need a real re-fetch. Pull one JSON field rather than dumping
records, e.g. the top 5 URLs:
`python -c "import json;print(*[r['url'] for r in json.load(open('/tmp/m.json'))][:5],sep='\n')"`

Common overrides (flags beat profile values):
```bash
... --profile example --stage 2                       # + LinkedIn/Glassdoor + keyed APIs (if keys set)
... --profile example --max-age-days 3                 # explicit "last 3 days"
... --profile example --visa-policy require_positive    # only EXPLICIT sponsorship (stricter)
... --profile example --ai-native-only                 # hard-filter to AI-native / AI-transitioning employers
... --profile example --no-jobspy                      # company boards + keyless aggregators only
... --profile example --json-out /tmp/matches.json       # machine-readable JSON (needed for handoff)
# exhaustive opt-in registry cohort: board-only, no top-K/per-company truncation
... --profile example --company-batches ai-expansion-01 --no-aggregators --all-matches \
    --json-out tmp/matches.json
```
More flags (`--company-tags`, `--aggregators`, `--no-companies`, `--max-per-company`,
`--include-recent`, `--search-log-skip-days`): `reference.md` § Search flags.

Rows with `poll_batch` in `companies.yaml` are deliberately excluded from ordinary profile runs;
select them explicitly with `--company-batches`. Use `--no-aggregators --all-matches` for an
exhaustive target-board cohort without unrelated market sources or shortlist truncation.

**Visa:** with `--visa-policy require_positive`, only postings with an EXPLICIT sponsorship signal
pass — warn the user this yields few results, and do **not** silently widen back to
`exclude_negative` to pad the count. Labels are `yes` / `no` / `unclear` and are **heuristic —
always confirm with the employer.** Generic "must be authorized to work in the US" boilerplate is
NOT a sponsorship denial (sponsoring employers use it too), so it never yields `no`. See
`reference.md` § Visa sponsorship heuristic.

### Step 3 — Present results
Show the top matches with company, title, score, level/Google-equivalent range, required YOE range,
salary, total compensation, age, visa label, and *why* each matched. `?` means the posting did not
provide the fact; never fill it from guesswork. Call out visa `unclear` rows as needing employer
confirmation. Group or highlight by fit if helpful.

### Step 4 — Verify candidates, then hand off
Before committing any selected posting to the pipeline, **verify its facts against the real JD
text** — two LESSONS bind here:
- **Workplace type:** never trust the scraper/ATS `remote` flag. In a live run *every* JobSpy match
  came back tagged remote — including JDs whose text said hybrid or on-site. Confirm workplace type
  from the JD text before handing off a posting or recording location facts.
- **Visa:** a heuristic `yes` can fire on a negation ("unable to sponsor", "does not offer
  sponsorship") whose text still contains sponsorship keywords. Treat any `yes` as a claim to
  verify against the actual JD wording before relying on it for a policy decision.

Fetch a candidate's JD text **verbatim** with `--digest` — the flag saves the full JD to disk
exactly as before AND, **at fetch time**, prints a compact deterministic **digest** that LOCATES the
gate-relevant lines (title/level, workplace/location signal lines, visa/sponsorship sentences). Verify
the workplace/visa/location/title gates **from the printed digest**; open the saved verbatim JD only
when the digest is ambiguous or a gate signal is missing from it — the digest is a locator, never a
verdict (contract: `reference.md` § JD digest). **`--digest` is a fetch-time aid only: for a JD file
already saved on disk (e.g. one `handoff.py` fetched), read the file directly — do not re-run
`fetch_jd` or rebuild a digest for it.** E.g. a posting not yet scaffolded:
```bash
.venv/bin/python .agents/skills/job-search/scripts/fetch_jd.py <URL> --out tmp/web_artifacts/jd.md --digest
```
If that page is JS-rendered (fetch_jd warns "JavaScript-rendered" / tiny output), recover the verbatim
JD from the ATS API via `company_roles.py --jd` instead of accepting a partial scrape; if no fetch works
at all (e.g. HTTP 403), save the scraper-extracted text with a non-verbatim provenance note — see
reference.md § "Recovering a JD when the page fetch is unusable".
Only hand off postings that passed the location policy (`config.location_policy()`). Then, for
**each** selected posting, scaffold its folder with `handoff.py` (needs `--json-out` from Step 2):
```bash
.venv/bin/python .agents/skills/job-search/scripts/handoff.py \
    --json /tmp/matches.json --select "rank 1"   # or --select "Company/Title"
```
For a deliberately exhaustive, verified JSON set, `--all --report
tmp/handoff-report.json` applies the same per-row scaffold plus a live-folder/log duplicate
preflight and continues with an auditable result for every row.

It creates `applications/6_drafted/<slug>/`, saves `source/JD-<job title>.md` **verbatim** (via
`fetch_jd`), and writes a schema-v4 `meta.yaml` carrying the row's `status: "drafted"`, `location`,
`url`, `posted_date`, `workplace`, `sponsorship`, `job_level`, `required_yoe`, and `salary_range` —
so nothing is hand-transcribed (refuses to overwrite an existing folder). `meta.yaml` is always
`job_metadata_schema_version: 4` with a uniform **`jobs:` list — one entry per posting, even a
single role** (each entry created `status: "drafted"`) — and every entry carries an exact
`jd_file`; never pair roles and JDs by index or sorted filename. If `handoff.py` reports gaps, run
`.agents/skills/application-tracker/scripts/status.py --enrich-metadata <folder>` to fill missing
facts (it consults the reusable company cache for level/YOE).

Then hand off — **do not tailor here:**
- **`resume-writer`** → tailors the scaffolded folder (add `source/tailored.yaml`).
- **`application-tracker`** → records metadata; the user moves the folder to
  `applications/5_applied/` once submitted; the folder is the derived overall status (rollup).

After creating a draft, run `.agents/skills/application-tracker/scripts/status.py --sync-log` so the
posting lands in `applications-log.yaml` and the company in `company-search-log.yaml`, then confirm
with `... status.py --check-locations`. If you reviewed a company's board and decided **no suitable
role**, record it:
`.venv/bin/python .agents/skills/application-tracker/scripts/status.py --log-search "<Company>" --outcome no_suitable`

## Re-check one company (single-company location verdict)

To re-search **one** employer — e.g. to decide whether a drafted application still has a
policy-matching role, or should be moved to `ignored/` — use `company_roles.py`, **NOT** the full
search pipeline. It fetches that company's live ATS board and prints every open posting with the
location verdict from this skill's vendored `_vendor/location.py` (a byte-identical copy of the
toolkit's `scripts/shared/location.py` — the same location policy the profile enforces via
`config.location_policy()`). It does **not** apply the role/seniority/visa title gate — it lists
everything so you judge role fit yourself — and its remote signal is a heuristic (some ATSs, e.g.
SmartRecruiters, over-report `remote`), so always confirm a candidate's true location from the
actual JD before acting.

```bash
# company in companies.yaml (resolve by name / alias / token); --match-only shows only policy-matching roles
.venv/bin/python .agents/skills/job-search/scripts/company_roles.py --name Cloudflare --match-only
# dump one posting's full JD text verbatim (for writing source/JD-<title>.md)
.venv/bin/python .agents/skills/job-search/scripts/company_roles.py --name Sentry --jd "Control Plane"
# ad-hoc company not in the registry (derive ats+token from its careers URL)
.venv/bin/python .agents/skills/job-search/scripts/company_roles.py --company CodeRabbit --ats ashby --token coderabbit
```

Company identity resolves through the registry (canonical name / alias / ATS token). **Foreign-
location correctness is built in:** the foreign check runs BEFORE the US-abbrev check, so two-letter
country codes like `CA` (Canada) / `IN` (India) do not leak a foreign role as US.

## More (see reference.md)

An ordinary search stops above. Reach for `reference.md` only for these:

| Need | Where |
|------|-------|
| Pipeline internals, per-source endpoints, JobSpy radius/multi-location, level-fit & diversity | `reference.md` § Pipeline overview |
| Full search-flag override list | `reference.md` § Search flags |
| Skip logic (blacklist / already-considered / recently-searched), registry identity resolution | `reference.md` § Skip logic |
| Stage-2 setup (LinkedIn/Glassdoor via JobSpy; Adzuna/JSearch keys) | `reference.md` § Stage 2 setup |
| AI-native two-signal scoring; when to add the `ai-native` tag | `reference.md` § AI-native company tagging |
| Managing `companies.yaml` (add a board token, validate, blacklist) | `reference.md` § Managing target companies |
| Reusable company leveling + compensation cache (`config.company_levels_path()`) | `reference.md` § Leveling cache |
| Optional DOL sponsorship enrichment (`build_sponsor_index.py`) | `reference.md` § Optional DOL sponsorship enrichment |
| Visa / US-location / recency heuristics; scoring weights | `reference.md` (Visa, US/location, Recency, Scoring) |

## Files

| Path | Purpose |
|------|---------|
| `profiles/<label>.yaml` | Search criteria (roles, keywords, location + radius, visa, recency, `ai_company`, `sources`/stage config); default label = `config.job_search.default_profile`. Two useful styles: an **evergreen company-board sweep** and a **widened two-stage market scan** (see `profiles/_TEMPLATE.yaml`) |
| `profiles/example.yaml` | Generic general-software-engineer example profile (copy + tune) |
| `companies.yaml` | Canonical company registry — identity, ATS poll config, tags (incl. the `ai-lab`/`ai-infra`/`ai-native` family), blacklist |
| `config.company_levels_path()` | Dated reusable company level/YOE/base/total-comp reference; separate from the identity registry (see reference.md § Leveling cache) |
| `scripts/search_jobs.py` | Main pipeline (two-stage fetch → filter → score → rank → output); `--stage`, `--ai-native-only`, `--no-jobspy`, `--max-per-company`, `--top-k`, `--max-age-days`, `--visa-policy`, `--refilter latest`, `--print-full` |
| `scripts/company_roles.py` | Re-check ONE company's live board with a location-policy verdict (single-company re-search + JD dump) |
| `scripts/fetch_jd.py` | Fetch one posting page and save its readable text **verbatim** (`<URL> --out <path>`; no summarization) |
| `scripts/handoff.py` | Scaffold an application folder from one selected search row (`--json <search.json> --select <"rank N"\|"Company/Title">`): folder + verbatim JD (via `fetch_jd`) + schema-v4 `meta.yaml` (each posting `status: "drafted"`); validates before exit, refuses to overwrite |
| `scripts/validate_companies.py` | Check that company tokens still resolve (skips identity-only rows) |
| `scripts/validate_filter_variants.py` | Check the deterministic corpus and strictly audit a private pre-filter snapshot; exits nonzero with label stubs for new/conflicting high-stakes variants |
| `filter_variants/corpus.yaml` | Public-safe fictional regressions for location/workplace, sponsorship, title/seniority, and required YOE |
| `scripts/build_sponsor_index.py` | Optional DOL sponsorship enrichment (see reference.md) |
| `scripts/registry.py` | Registry loader + resolver (canonical name, blacklist, poll targets, `tagged_keys` for the AI-native set) |
| `scripts/_vendor/*.py` | **Generated** byte-identical copies of `scripts/shared/*.py` (keep this skill self-contained). Do not edit — regenerate with `scripts/vendoring/sync_vendored.py`; see `scripts/_vendor/README.md` |
| `reference.md` | Pipeline internals, data-source endpoints, field notes, visa/scoring rationale, company management |
| `<applications_root>/0_profile/company-search-log.yaml` | Last successful full-company search per employer (config-derived; 7-day default skip — see Step 1) |

## Guardrails

- **Profiles hold criteria, scripts stay generic.** Tune `profiles/*.yaml`; never bake a person's
  criteria into code.
- **Visa detection is advisory.** `yes`/`no`/`unclear` come from text heuristics; always tell the
  user to confirm sponsorship directly with the employer.
- **No fabricated postings.** Every result must carry a real `source` + `url`; `?` for missing
  facts, never a guess.
- **Respect the sources.** Public read APIs only; keep the default company set modest and don't
  hammer endpoints (the script fetches once per run).
- **Never scrape Levels.fyi.** Automated leveling/benchmark ingestion is file-only and requires a
  user-supplied licensed export/API source recorded in provenance (see reference.md § Leveling cache).
- **Self-contained skill.** Scripts here import their siblings and the vendored `_vendor/` copy
  only — never repo-root toolkit Python. To change the location rule, edit
  `scripts/shared/location.py` and run `scripts/vendoring/sync_vendored.py`; never edit
  `scripts/_vendor/location.py` directly (the pre-commit drift check will reject it).
