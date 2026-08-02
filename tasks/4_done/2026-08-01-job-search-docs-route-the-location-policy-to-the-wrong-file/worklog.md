# Worklog — 2026-08-01-job-search-docs-route-the-location-policy-to-the-wrong-file

## 2026-08-02 — session 1 (agent, branch `docs/job-search-location-routing`)

- Re-verified all three defects against the code before editing. All three were live:
  `scoring.py::location_ok` builds `metro`/`allow_us_remote`/`us_only`/`require_match` from the
  search profile's `location:` block; `config.location_policy()` is never called from
  `search_jobs.py`; `config.py` defaults `us_only` True while `scoring.py` defaults it False;
  `_TEMPLATE.yaml` ships `max_age_days: 3` against a documented default of `null`.
- Found a fourth surface carrying the same mis-attribution: `evals/canaries/job-search.yaml`
  graded an agent as correct for repeating "the same policy the profile enforces via
  `config.location_policy()`". Corrected the expectation string.
- Scope held to documentation and attribution. `scoring.py`, `config.py`,
  `automation/shared/location.py`, and every default value are untouched. `_TEMPLATE.yaml` keeps
  `max_age_days: 3`; only comments were added around it.
- DoD item 3 (the `us_only` default asymmetry) is **documented, not removed** — resolving it moves
  which postings a search returns, which is an owner decision, filed at
  `message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md` with options, a
  recommendation, and a default path of "change nothing".
- DoD item 4 satisfied by the second branch of its own "or": `SKILL.md` and `reference.md` now name
  both the pipeline default (`null`, off) and the template's explicit `3`, instead of the template
  value moving.
- DoD item 5 (canaries): discharged in the **skipped** form per `evals/README.md` — the SKILL.md
  edit is a factual source-of-truth correction with no behavioural change, so no canary run.
- Proof rather than assertion: a scratch matrix ran `scoring.location_ok` and
  `handoff.row_location_verdict` over all nine combinations of `config.yaml` and profile
  `us_only` values. The search verdict tracks the profile in all nine and the config in none.
  Output recorded in `verification.md`.
