# A gardener test reads the owner's real profile when run without a config pin

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: workspace phase 6 implementation, 2026-07-30 (found while adding gardener tests)
- **Claimed-by**: agent, 2026-07-31 (branch `fix/03-owner-data-paths`; work complete, in review)

## Goal

Make `automation/gardener/tests` private-safe on its own, so a bare
`unittest discover` cannot resolve into the owner's overlay.

## Context

`automation/gardener/tests/test_skill_drift.py::test_run_is_report_only_and_exits_zero`
calls `skill_drift.run()` with no `JOBHUNT_CONFIG` pin. On a maintainer checkout the
ambient `config.yaml` resolves the accessors into `private/`, so the test reads the
owner's real baseline and profile and prints a drift report about them to stdout.

It is read-only, and CI is unaffected because CI has no overlay mounted — which is
exactly what makes it easy to miss. Every other suite in the repo pins a temp config;
this one relies on the overlay being absent.

Two fixes, either acceptable: pin `JOBHUNT_CONFIG` at a fixture config the way the
job-search suites do, or make the test assert against a temp tree it builds itself.
Prefer whichever matches the sibling suites in the same folder.

While you are there: `automation/gardener/tests` currently reports
`OK (expected failures=1)`. Confirm that expectation is still the right one rather than a
leftover — phase 5 already converted one stale `@unittest.expectedFailure` into a real
assertion after it flipped to UNEXPECTED SUCCESS.

## Definition of done

- [ ] `.venv/bin/python -m unittest discover -s automation/gardener/tests` with an overlay
      mounted and no `JOBHUNT_CONFIG` set resolves no path under `private/`
- [ ] Proved by asserting the resolved accessor paths inside the test, not by inspection
