# Should the search-time and draft-time `us_only` defaults be made to agree?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-02
- **Source**: [job-search docs route the location policy to the wrong file](../../../tasks/4_done/2026-08-01-job-search-docs-route-the-location-policy-to-the-wrong-file/task.md)
- **Blocks**: nothing. The docs now describe both defaults, so no agent is misled while this is open.
- **Default path**: change nothing. `skills/job-search/SKILL.md`, `reference.md`,
  `profiles/README.md`, `_TEMPLATE.yaml` and `company_roles.py` now state which surface defaults
  which way and which one the search honours. No default value moves until this is answered.
- **Cost if wrong**: recurring-loss
- **Safe to merge because**: nothing was written and no default changed. The branch touches only
  prose, one YAML comment block, one canary expectation string, and one handbook row; reverting the
  commit restores the prior text exactly.

## Background

The job-search pipeline has two location gates, and they read two different files.

- **Search-time** — `skills/job-search/scripts/scoring.py::location_ok` builds its whole policy
  from the active search profile's `location:` block:
  `us_only=loc_cfg.get("us_only", False)`, `require_match=loc_cfg.get("require_match", False)`.
- **Draft-time** — `handoff.py`, `skills/application-tracker/scripts/status.py --check-locations`
  and `company_roles.py` read `automation/shared/config.py::location_policy()`, which sets
  `us_only=lp.get("us_only", True)` and returns no `require_match` key at all, so
  `automation/shared/location.py`'s own default `require_match: True` applies.

`config.location_policy()` is never called from `search_jobs.py`. The two surfaces therefore
default in opposite directions. Measured on this branch (`scoring.location_ok` and
`handoff.row_location_verdict` against `"Berlin, Germany"`, both keys absent):

```
config.yaml location_policy.us_only : absent
search profile location.us_only     : absent
  config.location_policy()['us_only'] resolves to : True
  SEARCH gate  scoring.location_ok(Berlin)        : KEEP
  DRAFT gate   handoff.row_location_verdict()     : mismatch (foreign)
```

Flipping the profile key flips the search verdict; flipping `config.yaml` never does. The live
consequence: a profile that omits `us_only` searches worldwide, the foreign rows reach the
shortlist, and handoff then refuses them — per run, and silently until someone reads the drop
report. Both shipped profiles (`example.yaml`, `_TEMPLATE.yaml`) set `us_only: true` explicitly, so
the default only bites a hand-written or partial profile.

This is a behaviour question, not a doc question, which is why the documentation PR did not settle
it: either default is defensible, and moving either one changes which postings a user sees.

## Options

### Option A — Change nothing; keep both defaults documented

The docs now name both defaults and the file each gate reads. No behaviour moves.
Pro: zero risk; both shipped profiles already set the key, so the gap only affects profiles that
omit it. Con: the trap stays live for hand-written profiles, and every new reader has to learn it.

### Option B — Make the search default `us_only: True`

Change `scoring.py` to `loc_cfg.get("us_only", True)`, matching `config.location_policy()` and
`automation/shared/location.py`. Pro: one default across the toolkit; a profile that forgets the key
gets the same US-only scope the draft gate will demand, so the two stop disagreeing.
Con: it silently narrows any existing profile that relies on the current `False` to search
worldwide — an intentional global search written as an omission would quietly go US-only. Needs a
job-search canary run, and existing overlay profiles should be checked for an omitted key first.

### Option C — Make the draft default `us_only: False`

Change `config.location_policy()` to `lp.get("us_only", False)`. Pro: also unifies them.
Con: wrong direction for a gate whose purpose is to stop out-of-policy applications being drafted;
a `config.yaml` with no `location_policy:` block would stop rejecting foreign roles. This weakens a
guardrail (`AGENTS.md` → Location policy) to fix a naming problem.

### Option D — Make the key required in a search profile

Fail the profile load when `location.us_only` is absent, so no default is needed at search time.
Pro: removes the trap without choosing a direction. Con: a hard failure on every existing profile
that omits it; needs a migration pass over overlay profiles.

## Recommendation

**Option B**, in its own PR with the job-search canaries run. It aligns the search with the two
defaults that already agree (`config.location_policy()` and `location.py`), and the direction it
picks is the conservative one: a forgotten key produces a narrower search, not out-of-policy rows
that the next gate throws away. Before merging it, grep the overlay's profiles in
`config.search_profiles_dir()` for an omitted `us_only` and set it explicitly in any that rely on
today's `False`, so no existing search silently narrows. Option A is the honest fallback if you
would rather not touch search behaviour at all.

**Your answer:** ______
