# The LibreOffice apt install flakes the pdf-tests job, and it takes `build` down with it

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: 2026-08-03 — first CI run of PR #300 (run `30824355749`). `pdf-tests` failed with
  exit code 124 in `Install LibreOffice once for PDF lanes`, before a single test ran; `build`
  failed because `PDF_TESTS_RESULT: failure`. `gh run rerun --failed` passed the same commit,
  with the same step taking 1m4s. Nothing in that PR's diff touches `.github/`, LibreOffice, or
  the render/resume lanes.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

A PR whose diff has nothing to do with PDF rendering stops failing CI because an apt transaction
on the runner was slow. Either the install stops being on the critical path of every full run, or
its bound stops being a coin flip — decided deliberately, not by raising a number until it stops.

## Context

`.github/workflows/ci.yml` installs LibreOffice for the PDF lanes in one step:

```yaml
- name: Install LibreOffice once for PDF lanes
  run: sudo timeout 180s sh -c 'apt-get update && apt-get install -y libreoffice-writer'
```

The 180-second bound and the single-install grouping are both deliberate, from
`tasks/4_done/2026-08-03-reduce-pr-ci-and-stack-latency/`. That task's own
`verification.md` already recorded the underlying behaviour: a representative install took 31
seconds, but one observed job "remained in `Install LibreOffice for PDF lanes` for more than five
minutes … this was package-manager tail latency, not test execution". So the bound was chosen
knowing the tail exists; what was not settled is what happens when the tail wins.

What it costs when it does: `pdf-tests` is a `needs:` of `build`, and `build` is the repository's
stable required check, so an apt timeout presents as a red required check on an unrelated PR. The
only recovery today is a human noticing and re-running, and the re-run is not free — it re-runs
the whole failed set.

Two facts worth carrying into the fix:

- **A longer timeout is not obviously the answer.** The bound exists so a hung apt fails fast
  instead of burning the job's full allowance. Raising it to cover a five-minute tail trades a
  fast red for a slow one.
- **Retry and cache are the two real shapes.** Retrying the step (or the job) absorbs the tail
  without extending the bad case. Caching the package — or moving to a runner image or container
  that already has `libreoffice-writer` — removes the transaction from the critical path
  entirely, which is the only option that also makes the lane faster. Note that `render` and
  `resume` are the only lanes that need it, and both are already grouped into this one job.

Out of scope: changing what the PDF lanes verify. `check.py`'s one-page PDF validation runs only
where LibreOffice exists, and that must stay true in CI — this is about how the binary gets there.

## Definition of done

- [ ] `pdf-tests` no longer fails on package-manager tail latency: either the install is retried
      or removed from the critical path, with the choice and its trade-off written in the workflow
      next to the step (the current comment explains the grouping, not the bound)
- [ ] `automation/gates/tests/test_run_gates.py`'s workflow assertions still pass — that test pins
      "exactly one LibreOffice install, a 180-second bound, and both render and resume
      invocations", so any change here updates the pin deliberately rather than breaking it
- [ ] One full-matrix CI run observed green on a PR that touches the render/resume lanes, with the
      install step's duration recorded
