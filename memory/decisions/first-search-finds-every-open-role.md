# A company's first-ever search finds every open role, not just the fresh ones

- **Status**: decided
- **Date**: 2026-08-02
- **Decided by**: owner

## Context

Two scripts under `skills/job-search/scripts/` answer "what is open at this company?" and
disagree by design. `search_jobs.py` applies a date gate that drops any posting older than the
profile's `max_age_days`; `company_roles.py --match-only` applies location and match filters and
no recency filter at all.

For a **recurring** search the age gate is the product — re-surfacing month-old reqs every run is
noise. For a company that has never been searched there is no "recurring": the whole board is new
information, and the gate silently discards roles that are still live on the employer's ATS purely
because they were posted a while ago. The two scripts then answer differently about the same
company, and the one an agent reaches for first is the one that drops them.

The cost is missed opportunities rather than tidiness. Two postings were confirmed lost this way —
US-remote, carrying no visa denial, matching on every other gate, still open on the employer's
ATS, one older by a wide margin and one by about six weeks. Neither reached a draft, and nothing
recorded that they had been dropped. The instances are overlay data and are not named here.

## Decision

**A company's first-ever automated search finds all available roles.** The profile's recency gate
does not apply to a run against a company that has never been searched, and older roles from that
run are matched by default rather than set aside. Every later run against that company narrows to
the profile's `max_age_days`.

In the owner's words: *"For a first search we always find all available roles, and match older
roles by default."*

"Never searched" is read off the company-search log (`config.company_search_log_path()`), which
already records the last successful full-company search per employer — a company with no row has
never been searched. The widened window is printed in the run's header, so the output says why it
looks different from a repeat run.

## Alternatives considered

- **Leave it and hand-run a wide refilter on a first search** — zero code, but it relies on an
  agent remembering to do the wide pass on exactly the run where nobody has established a
  baseline, and a missed first-search role is recorded nowhere as missed. The answer's own
  phrasing ("we *always* find all available roles") rejects "remember to".
- **Make the two scripts agree by giving `company_roles.py --match-only` the same recency gate** —
  cheapest to reason about, and the one option that makes the loss complete rather than
  recoverable: the roles simply stop being visible anywhere.

## Consequences

- A first search returns a larger, older set that needs curation. That is accepted deliberately:
  coverage is the product on run one, freshness on every run after it.
- Two runs of the same command against the same company can legitimately return different sets.
  That is now intended behaviour, not a defect report.
- The first-search test leans on a log that can be wrong. The company-search log is upserted by
  `status.py --sync-log` / `--log-search`, so a company recorded under a different name variant
  reads as never-searched and gets a second wide run. That is the safe direction for this error to
  fall — over-collection, not silent loss.
- Implementation and the matching skill-doc contract are filed as
  `tasks/4_done/2026-08-02-first-search-widens-the-recency-window/`.
- **Revisit if** the wide first set becomes unmanageable in practice. The lever then is a bounded
  first-search window (a large explicit number of days), never a return to the profile default on
  run one — that is the behaviour this decision replaced.
