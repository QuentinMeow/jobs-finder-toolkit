# The "Level (Google eq.)" column claims occupations nobody ever mapped

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GH #288, comments 1 and 2 (the half `fix/jd-metadata-extraction` could not own)

## Goal

The discovery table stops printing a Google engineering-ladder equivalent for a
role whose occupation has no evidence-backed mapping to that ladder, and prints
an occupation-neutral seniority label instead.

## Context

`fix/jd-metadata-extraction` fixed the PEOPLE-MANAGER half of #288: a
management title now resolves to a management scope (`line_manager`,
`senior_manager`, `director`, `executive`) in
`automation/shared/job_metadata.py`, and those scopes carry no Google
equivalent, so `skills/job-search/scripts/search_jobs.py::_format_level`
renders e.g. `line manager (?)`.

The issue's later comments report the same misleading claim for occupations
that are not management at all, and those are still live on `main`:

- `Enterprise Account Manager` renders `senior (L5.0-L5.8)`;
- `Principal Partner Account Manager` renders `principal (L8.0-L8.8)` — an
  alliances role requiring 12+ years, not an L8 engineering-equivalent;
- a `Registered Nurse L&D` posting renders `entry (L3.0-L3.8)`.

Reproduce with the repo venv:

    .venv/bin/python -c "
    import sys; sys.path.insert(0, 'automation/shared')
    from job_metadata import analyze_job_metadata
    for t in ('Enterprise Account Manager', 'Principal Partner Account Manager',
              'Registered Nurse L&D'):
        print(t, analyze_job_metadata(company='X', title=t,
              description='5+ years of professional experience required.')['job_level'])
    "

Two constraints the fix must respect:

- the IC scopes themselves are correct for engineering roles and must not move —
  `analyze_job_metadata` and `scoring.level_fit_delta` both speak that scale;
- the column LABEL lives in `search_jobs.py` (`"| # | Score | Company | Title |
  Level (Google eq.) | ..."`, ~line 860) and the per-row rendering in
  `_format_level`, so the honest fix probably belongs there — either an
  occupation-neutral column when the active profile is non-engineering, or a
  per-row suppression driven by an occupation read. `job_metadata` already
  supplies the raw seniority word; it does not know the profile's occupation.

Whatever is chosen, "entry/mid/senior" as bare words is defensible; "L3.0-L3.8"
attached to a nursing role is not.

## Definition of done

- A non-engineering posting never renders an `L<n>` equivalent it has no
  documented mapping for; the seniority evidence it DOES have is still shown.
- Fixtures for an IC engineer, an account-management role and a clinical role,
  in `skills/job-search/scripts/tests/` or the filter-variant corpus, pin the
  difference.
- `.venv/bin/python automation/gates/run_gates.py --lane job-search` exits 0.
