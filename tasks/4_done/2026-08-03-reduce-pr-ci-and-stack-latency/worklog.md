# Worklog — 2026-08-03-reduce-pr-ci-and-stack-latency

## 2026-08-03 — session 1 (Codex `/root`)

- Created `codex/ci-pr-latency` from `origin/main` at `47cffb2`; no prior working-tree changes existed.
- Measured representative GitHub runs: successful normal PRs currently take about 3.2–3.5 minutes after a runner starts, with 49–55 seconds of dependency and LibreOffice setup and roughly 2 minutes of serial test suites.
- Began independent CI critical-path, risk-design, and `ai-harness` comparison investigations; next is the fail-closed lane design and baseline benchmark.
- Implemented and unit-tested fail-closed path classification, always-on policy, parallel long-test lanes, three publish shards, a separate body workflow, and local `--impact-from` selection.
- Opened PR #266. Its deliberately full first run passed in 88 seconds end-to-end versus the 184-second historical PR median; policy took 28 seconds and the slowest lane 70 seconds. A later body edit ran only the 15-second body workflow and no CI workflow.
- Added `build` and `pr-body` as required GitHub Actions checks after both reported green.
- Implemented the stacked follow-up: no-op retarget detection plus a named, head-pinned atomic-prefix merge path; canary and final hosted evidence remain before merge.
- Opened PR #270. Its final head passed every hosted check; the deliberately full matrix completed in 109 seconds and the separate body job in 8 seconds.
- Added a regression-tested base-retarget filter so ordinary stack retargets do not restart the required body gate while description edits still do.
- The merge driver's live dry run re-read both PRs as open and mergeable with pinned heads. The irreversible execute request was not attempted because merging into `main` requires explicit owner authorization.
- Opened stacked probe PR #275. Its first hosted run exposed that CI compared every stacked PR with `origin/main`, so a documentation-only tip inherited the lower workflow diff and selected all lanes.
- Changed hosted classification to use the pull request event's immutable base and head SHAs plus their merge base; added a static regression test forbidding the hardcoded default-branch comparison.
- The correction run exposed a second tail: the render job's duplicate LibreOffice install stayed in `apt-get install` for more than five minutes after every non-PDF lane and the resume lane completed.
- Grouped render and resume into one hosted PDF job with a single 180-second-bounded LibreOffice transaction; retained both hard test lanes and added output/workflow regression coverage.
- PR #275's grouped correction run passed in 105 seconds end to end. The single PDF job ran both render and resume lanes in 61 seconds; the slowest non-PDF lane took 62 seconds.
- Prepared a clean process-only stacked tip to validate the corrected pull-request base range and policy-only hosted target before owner-authorized merge.
- Opened PR #277. Its hosted classifier selected no non-PDF or PDF lane; CI passed in 36 seconds end to end, with 28-second policy and 3-second stable `build` jobs. The separate body workflow passed in 9 seconds wall time.
- After explicit owner authorization, used the guarded merge driver to merge #266, #270, #275, and #277 bottom-up into the latest `main`; every merge and base retarget was independently confirmed.
- Post-merge `main` CI run `30818429618` passed the complete matrix and canonical counts in 112 seconds at `bfe24604`.
