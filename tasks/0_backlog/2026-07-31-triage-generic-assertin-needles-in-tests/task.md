# Triage ~30 tests whose `assertIn` needle may be satisfied by unrelated output

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: the wider sweep run while fixing
  `automation/gardener/tests/test_roadmap_staleness.py`, 2026-07-31 — one confirmed
  vacuous assertion there was fixed; these are the unverified lookalikes
- **Claimed-by**:

## Goal

Decide, for each listed test, whether its `assertIn` needle can be satisfied by output
the test is not actually asserting about — and fix the ones that can.

## Context

A confirmed defect in `test_a_fresh_roadmap_says_current` asserted `assertIn("current",
report)` where `"current"` also appears in the printed path
`docs/roadmap/current-state.md`. It passed while the routine reported `STALE`, so the
test asserted nothing. It is fixed.

A grep of `test_*.py` for short or generic needles returned roughly 40 hits. Four of the
closest lookalikes were checked individually and are **sound** — record them here so
nobody re-checks them:

- `skills/resume-writer/scripts/tests/test_tailoring_card.py:253` — `"current"` appears
  only in the success branch of `build_tailoring_card.py --check`.
- `skills/job-search/scripts/tests/test_handoff.py:510` — `"STALE"`, paired with an
  exact-empty-string check on the fresh case.
- `skills/github-workflow/scripts/tests/test_check_pr_body.py:147` — `"OK"`, backed by an
  explicit `returncode == 0` assertion.
- `automation/shared/tests/test_store_validation.py:138` — `"WARNING"`; the pass branch
  prints a disjoint `"fixture size OK"`.

The remaining ~30 were **not** individually verified. They live in
`test_snapshot_refilter.py`, `test_jobspy_warning.py`, `test_handoff.py`,
`test_fetch_jd.py`, `test_build_postings.py`, `test_filter_variants.py`,
`test_skip_log_writers.py`, `test_resume_schema.py`, `test_store_validation.py:126`, and
`test_company_index.py:538`.

The check is mechanical and takes about a minute each: break the code under test so the
assertion *should* fail, and confirm it does. A test that still passes is vacuous.

Do not mass-rewrite. Most of these will be fine, and a needle that reads generically is
not itself a defect — only one that a non-target string can satisfy is.

## Definition of done

- [ ] Every listed test either confirmed discriminating (break-it-and-watch-it-fail) or
      rewritten so it is
- [ ] Any test found vacuous has a note in its docstring or the PR body saying what it
      was silently passing on
- [ ] `.venv/bin/python -m unittest discover` green across the affected suites
