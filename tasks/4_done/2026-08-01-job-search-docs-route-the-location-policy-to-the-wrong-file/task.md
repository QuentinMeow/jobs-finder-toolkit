# job-search's quickstart routes the location policy to a file the search never reads

- **Priority**: P0 (blocks work)
- **Area**: job-search
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**: agent (docs/job-search-location-routing, 2026-08-02)

## Goal

An agent told "make this search US-only" edits the file the search actually reads, and the two
location gates (search-time and draft-time) are described as the two different policies they are.

## Context

`skills/job-search/SKILL.md:71-72` — in the Quickstart routine path, read on every search — says:

> The profile — not the script — holds all criteria: **location** (`config.location_policy()`:
> `metro` + `allow_us_remote` + `us_only`; the profile's own `location:` block adds
> `preferred`/`allow_remote`/`require_match`), …

The code splits it the other way round. `skills/job-search/scripts/scoring.py:309-318`:

```python
def location_ok(posting: JobPosting, profile: dict) -> bool:
    loc_cfg = profile.get("location", {}) or {}
    assessment = assess_location(
        posting.location,
        {
            "metro": loc_cfg.get("preferred") or [],
            "allow_us_remote": loc_cfg.get("allow_remote", True),
            "us_only": loc_cfg.get("us_only", False),
            "require_match": loc_cfg.get("require_match", False),
        },
```

The search builds **all four** keys from the search profile's `location:` block.
`config.location_policy()` is not called anywhere in `search_jobs.py`; its readers are
`handoff.py:852,964`, `company_roles.py:80` and `status.py:471` (`--check-locations`) — the
draft-time gate, not the search-time one.

Two concrete wrong actions:

1. An agent asked to restrict a search to the US edits `config.yaml`'s `location_policy:` and
   nothing changes, because `us_only` for the search lives in
   `config.search_profiles_dir()/<name>.yaml`. `skills/job-search/reference.md:224` states this
   correctly ("`location.us_only: true` (set in the active profile)"), and both
   `skills/job-search/profiles/example.yaml:114` and `_TEMPLATE.yaml:30` set it in the profile.
2. The two policies default in OPPOSITE directions — `automation/shared/config.py:626` defaults
   `us_only` **True**, `scoring.py:316` defaults it **False** — so a profile that omits the key
   searches worldwide and then gets its drafts rejected by `--check-locations`. Nothing documents
   that asymmetry.

The same conflation repeats at `skills/job-search/SKILL.md:269-270` ("the same location policy the
profile enforces via `config.location_policy()`") and in `company_roles.py`'s module docstring
(lines 6-8), which asserts the two paths cannot disagree.

**Second, smaller item in the same file family.** `skills/job-search/SKILL.md:86` — "**Posting age
is OFF by default** (`max_age_days: null`)" — vs `skills/job-search/profiles/_TEMPLATE.yaml:39`,
`max_age_days: 3`, while `profiles/README.md:25-29` tells you to create every new profile by
copying that template. The shipped `example.yaml:130` is `null` and `reference.md:442-444` says
opt-in, so the template is the odd one out; its own neighbouring opt-in field
(`max_years_experience: null`, line 42) shows the intended shape. An agent that copies the template
and reports "few matches" is looking at a 3-day recency gate the skill told it was off.

This is filed rather than fixed in place because correcting `SKILL.md:71-72` rewrites a Quickstart
instruction (a behavioral harness edit — run `evals/canaries/job-search.yaml` per `evals/README.md`
before merge), and because whether `scoring.py`'s `us_only` default should move to match
`config.location_policy()` is a behaviour question, not a doc question.

## Definition of done

- [ ] `skills/job-search/SKILL.md` attributes the four search-time location keys to the search
      profile, and names `config.location_policy()` as the draft-time gate
      (`handoff.py` / `status.py --check-locations`) only.
- [ ] `company_roles.py`'s docstring and `SKILL.md:269-270` no longer assert the two gates share one
      policy, or the code is changed so they do.
- [ ] The default asymmetry (`us_only` True in config, False in the search profile) is either
      removed or documented where an agent setting up a profile will see it.
- [ ] `_TEMPLATE.yaml`'s `max_age_days` matches the documented default, or `SKILL.md:86` stops
      calling it off by default.
- [ ] job-search canaries run and recorded per `evals/README.md`.
