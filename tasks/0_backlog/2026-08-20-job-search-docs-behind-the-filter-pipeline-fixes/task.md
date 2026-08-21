# The job-search docs still describe the pre-#278 cap and the pre-#243 age window

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: branch `fix/filter-pipeline-reports` (2026-08-20), which fixed GH #243,
  #253, #278, #281, #285 and the progress half of #292 but was scoped out of every
  `SKILL.md` / `LESSONS.md` / `reference.md`
- **Claimed-by**:

## Goal

The job-search skill's own documents state what the pipeline now does, so no agent or
user has to read `search_jobs.py` to learn that the per-employer cap stopped
backfilling, that an explicit `--max-age-days` is no longer widened past, that the
report carries a funnel, or that an unknown profile key now warns.

## Context

Five behaviours changed in `skills/job-search/scripts/search_jobs.py` and are documented
only in code comments and the branch's commit messages:

1. **Per-employer cap (#278)** — `select_diverse` no longer backfills capped overflow to
   reach `top_k`. A shortlist can now be SHORTER than `top_k` when few employers match;
   the report header names how many rows the cap held back and from whom. Any doc saying
   the shortlist returns `top_k` rows, or describing `diversity.max_per_company` as a
   preference, is now wrong.
2. **Explicit age bound (#243)** — `company_search_log.widen_first_search` still widens
   the PROFILE's window on a company's first-ever search (owner decision 2026-08-02,
   `memory/decisions/first-search-finds-every-open-role.md`, unchanged), but a
   `--max-age-days` typed on the command line suppresses it for that run. The docs
   currently imply the widening always applies.
3. **Funnel (#253)** — the report gained a `## Funnel` section giving one terminal
   disposition per scanned posting, summing to the input, with journey-describing counts
   (word-filter rescues, widened rows, collapsed bodies) listed separately as
   diagnostics. Worth naming in the skill as the thing to read when counts look wrong.
4. **Duplicate JD bodies (#281)** — `dedupe` collapses rows whose normalized JD body is
   the same text, keeping the best-scoring copy and printing the others' employers and
   URLs under `## Duplicate JD bodies`. `MIN_BODY_FINGERPRINT_CHARS` (400) is the floor
   below which a body is never an identity.
5. **Unknown profile keys (#285)** — `PROFILE_SCHEMA` in `search_jobs.py` declares every
   key the pipeline reads; anything else prints a `Profile: UNKNOWN KEY ...` warning
   naming the nearest real key, and the warning is repeated in the report. Adding a
   profile key now means adding it to that table, which belongs in the profile docs.

Files that carry the old contract:

- `skills/job-search/SKILL.md` and `skills/job-search/reference.md` — the shortlist,
  posting-age and diversity sections.
- `skills/job-search/profiles/README.md` — the `diversity.max_per_company`,
  `max_age_days` and `company_search_log` descriptions, plus a pointer that unknown keys
  now warn and that `PROFILE_SCHEMA` is the list.
- `skills/job-search/profiles/_TEMPLATE.yaml` — the `max_per_company` and
  `first_search_max_age_days` comments.

The eval gate applies: `evals/canaries/job-search.yaml` exists, so a behavioural edit to
those documents runs the canaries before merge, or records why it did not.

## Definition of done

- The five behaviours above are stated in the skill's own documents, with no document
  still implying a backfilled shortlist or an always-on widening.
- `automation/reconcile/reconcile.py --check` exits 0.
- The job-search canary decision is recorded per `evals/README.md`.
