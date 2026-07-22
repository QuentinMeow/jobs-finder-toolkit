# Job-matching profiles

Each `<label>.yaml` in this folder is one **search profile** — a reusable set of
role targets, keyword weights, location/remote preferences, visa policy, and
recency filter. The general `SKILL.md` stays profile-agnostic; all candidate- and
search-specific tuning lives here so you can keep several profiles side by side
(e.g. `default`, `staff-only`, `remote`). The profile used when `--profile` is
omitted comes from `config.job_search.default_profile`.

## Files

| File | Purpose |
|------|---------|
| `example.yaml` | A generic, ready-to-copy general software-engineer profile |
| `_TEMPLATE.yaml` | Starting point for a new profile |

Add your own `<label>.yaml` here (kept out of the public toolkit) and point
`config.job_search.default_profile` at it.

## Create a new profile

```bash
cp skills/job-search/profiles/_TEMPLATE.yaml \
   skills/job-search/profiles/my-profile.yaml
# edit it, then:
.venv/bin/python skills/job-search/scripts/search_jobs.py --profile my-profile
```

## Field reference

- **titles.include / titles.exclude** — title gate. A posting is a candidate if its
  title contains at least one `include` term and none of the `exclude` terms.
- **keywords.strong / good / negative** — scoring. `strong` matches in title+description
  (high weight), `good` in description (medium), `negative` lowers score (honest mis-fits).
- **location.preferred / allow_remote / require_match** — `require_match: false` keeps all
  locations but boosts preferred/remote; `true` hard-filters to them.
- **visa** — `needs_sponsorship: true` activates the visa filter. `policy: exclude_negative`
  drops only postings that explicitly deny sponsorship; `require_positive` keeps only those
  that explicitly offer it. `h1b_transfer` / `perm_greencard` add soft scoring boosts.
- **max_age_days** — only postings published within the last N days (`null` = don't
  filter on posting age).
- **ai_company** — AI-native / AI-transitioning company fit. `signals` = JD-text phrases
  (each found adds `boost_per_hit`, capped at `max_boost`); `company_tags` = registry tags
  (e.g. `ai-lab`/`ai-infra`/`ai-native`) whose employers get `company_boost`. `require: true`
  (or `--ai-native-only`) hard-filters to AI-native/AI-transitioning employers; default is
  a soft boost that keeps breadth.
- **sources.company_tags** — which companies from `companies.yaml` to search (by tag).
- **sources.aggregators** — keyless cross-company aggregators run in STAGE 1
  (jobicy/remoteok/themuse; arbeitnow is EU-heavy).
- **sources.extended_aggregators** — keyed aggregators (adzuna/jsearch) that run only in
  STAGE 2 (`--stage 2`) and only when their API-key env vars are set.
- **sources.jobspy** — the direct-market scraper. `enabled`, `reliable_sites`
  (STAGE 1, e.g. `[indeed, google]`), `extended_sites` (STAGE 2, e.g. `[linkedin]`),
  `locations` (list of `{location, distance, is_remote}` — `distance` is a radius in miles),
  `results_wanted`, `max_terms`, `country_indeed`, `linkedin_fetch_description`.

**Two search stages:** stage 1 (default) = company boards + keyless aggregators + JobSpy
reliable sites (free, fast, no keys). Stage 2 (`--stage 2`) also runs JobSpy extended sites
(LinkedIn/Glassdoor) + keyed aggregators. Run a quick company-only pass with `--no-jobspy`.
