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

This folder is **entirely public** — those two files plus this README are all it may
ever hold. Your own profiles are candidate data and live in the private overlay, at
`config.search_profiles_dir()` (default `private/market/searches/`). A bare
`--profile <label>` resolves there FIRST and falls back to this folder, so a public
checkout with no overlay still runs on `example`.

## Create a new profile

`--profile` accepts a **path**, so the copy can live anywhere and this works on a
fresh clone with no config and no overlay:

```bash
cp skills/job-search/profiles/_TEMPLATE.yaml examples/market/searches/my-profile.yaml
# edit it, then:
.venv/bin/python skills/job-search/scripts/search_jobs.py \
  --profile examples/market/searches/my-profile.yaml
```

`examples/market/searches/` is tracked-but-empty and is what
`config.search_profiles_dir()` resolves to under the fresh-clone example config,
so a file placed there is also reachable by **bare label** — no path needed:

```bash
.venv/bin/python skills/job-search/scripts/search_jobs.py --profile my-profile
```

Then point `config.job_search.default_profile` at the label to make it the default.

**Keep a real profile out of the public tree.** Once you have a private overlay,
`config.search_profiles_dir()` points at `private/market/searches/` instead —
create it first, since a fresh checkout has no `private/` at all:

```bash
mkdir -p private/market/searches
cp skills/job-search/profiles/_TEMPLATE.yaml private/market/searches/my-profile.yaml
```

`*.yaml` under `examples/market/searches/` is git-ignored so a profile parked
there while you experiment cannot be committed by accident.

## Field reference

- **titles.include / titles.exclude** — title gate. A posting is a candidate if its
  title contains at least one `include` term and none of the `exclude` terms.
- **titles.primary** — optional main-list precision boundary for a specialized
  profile. When non-empty, an included title must also contain one of these
  occupation-bearing target phrases to enter the main shortlist. Matching is
  word-bounded, separator-insensitive, and allows the same short English inflections
  as other title terms; it is not literal-string equality. Prefer a complete phrase
  such as `ios engineer`, `mobile platform engineer`, or `qa automation sdet`, not
  a domain word such as `mobile`, `application`, or `quality` that can name another
  occupation. A miss is kept in the bounded occupation-review lane, never dropped.
  Leave it empty for a general search; scripts enforce the phrases the profile owns
  and never guess a global occupation taxonomy.
- **keywords.strong / good / negative** — scoring. `strong` matches in title+description
  (high weight), `good` in description (medium), `negative` lowers score (honest mis-fits).
- **location.preferred / allow_remote / us_only / require_match** — `require_match: false` keeps
  all locations but boosts preferred/remote; `true` hard-filters to them. **This block is the only
  source of the search-time location gate** — `config.yaml`'s `location_policy:` is a separate,
  draft-time gate (`handoff.py`, `status.py --check-locations`, `company_roles.py`) and editing it
  changes no search result. Always set `us_only` explicitly: the search treats an absent
  `us_only` as `false` (worldwide), while the draft-time gate treats an absent one as `true`, so a
  profile that omits it surfaces foreign roles that handoff then rejects.
- **visa** — `needs_sponsorship: true` activates the visa filter. `policy: exclude_negative`
  drops only postings that explicitly deny sponsorship; `require_positive` keeps only those
  that explicitly offer it. `h1b_transfer` / `perm_greencard` add soft scoring boosts.
- **max_age_days** — only postings published within the last N days (`null` = don't
  filter on posting age, which is also what the pipeline uses when the key is
  absent). `_TEMPLATE.yaml` ships an explicit `3`, so set it to `null` in your copy
  unless you want a 3-day recency window. **It does not apply to a company's FIRST
  search**: an employer with no row in the company-search log has no prior coverage
  to protect, so that run widens to `company_search_log.first_search_max_age_days`
  (`null` = no age gate at all). See `reference.md` § Recency filter.
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
