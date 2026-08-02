# `status.py --check-locations` still reports a mixed-location folder as `ok`

- **Priority**: P1 (this round)
- **Area**: tracker
- **Source**: adversarial audit #3 finding 3, the half deliberately left out of
  branch `wip/26-handoff-defects` (see that PR's Design section).
- **Claimed-by**: agent (branch `wip/35-pipeline-parse-defects`)

## Goal

Make the tracker's location gate answer the same question `handoff.py` now
answers — "does EVERY posting in this folder satisfy the policy?" — so a
multi-role application holding one US and one foreign posting stops reporting
`ok / metro`, and AGENTS.md's named verification command (`status.py
--check-locations`) agrees with the gate that created the folder.

## Context

`skills/application-tracker/scripts/status.py::app_location_assessment` (~line
356) already assesses **each** `jobs:` entry with its own `jd_file`, then rolls
the results up **best-match-wins**:

```python
for assessment in assessments:
    if assessment.decision == "match":
        return assessment
```

`check_locations` (~line 687) scores the folder on that single returned
assessment, so one Seattle posting makes a London sibling in the same folder
report `match / metro`, and the command exits 0. `app_locations` (~line 330),
which supplies the `LOCATIONS` column, has the same shape one level down: it
pools every posting's `location` and only falls back to the JD `Location:` lines
when meta.yaml records **none at all**, so a blank-location posting is invisible
in the output as well as in the verdict.

The argument for worst-wins is in the branch's PR: AGENTS.md's location policy
governs a **posting** ("only draft a role whose `location` matches"); a folder is
just the container one resume covers, so an any-matches rollup answers "could I
take some job at this employer?" — the wrong question for the multi-role folder
`handoff.py` builds by default. `review` must keep NOT failing the check: a
genuinely unknown location blocking legitimate work is the expensive direction.

**Why it was not done in that branch.** handoff gates *creation*, so its blast
radius is folders that do not exist yet and every case is reachable from
fixtures. The tracker gates the owner's *existing corpus*: flipping the rollup
changes the verdict of applications already on disk, and the size of that change
is only measurable against `config.applications_root()` under `private/`, which
that branch could not read. Ship it with a measurement, not on inference.

Related but distinct: `tasks/0_backlog/2026-07-31-jd-body-declared-locations`
covers extracting geography from JD **body prose**. This task changes only the
per-folder rollup and the per-posting JD-file fallback, both over
`extract_jd_locations`, the strict extractor that already serves JD files the
pipeline writes.

## Definition of done

- `app_location_assessment` returns the WORST posting verdict (`no_match` beats
  `review` beats `match`), and `check_locations` names the offending posting(s)
  by role in its row/JSON output rather than collapsing the folder to one
  category.
- A blank-`location` posting is assessed from its own `jd_file` (mirroring
  `handoff.job_locations`), not skipped because a sibling recorded a location.
- `review` still does not fail the command; `unreadable` still does.
- A test fixture with one metro posting and one foreign posting in one folder
  reports `mismatch` and exits non-zero — and fails against the pre-change code.
- Before/after counts recorded from a real run over
  `config.applications_root()` (how many folders change verdict, and each one
  named), so the owner sees the blast radius before the exit code changes.
- `skills/application-tracker/scripts/tests` and `automation/shared/tests` pass.
