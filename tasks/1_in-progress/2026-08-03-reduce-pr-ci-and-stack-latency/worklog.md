# Worklog — 2026-08-03-reduce-pr-ci-and-stack-latency

## 2026-08-03 — session 1 (Codex `/root`)

- Created `codex/ci-pr-latency` from `origin/main` at `47cffb2`; no prior working-tree changes existed.
- Measured representative GitHub runs: successful normal PRs currently take about 3.2–3.5 minutes after a runner starts, with 49–55 seconds of dependency and LibreOffice setup and roughly 2 minutes of serial test suites.
- Began independent CI critical-path, risk-design, and `ai-harness` comparison investigations; next is the fail-closed lane design and baseline benchmark.
- Implemented and unit-tested fail-closed path classification, always-on policy, parallel long-test lanes, three publish shards, a separate body workflow, and local `--impact-from` selection.
- Opened PR #266. Its deliberately full first run passed in 88 seconds end-to-end versus the 184-second historical PR median; policy took 28 seconds and the slowest lane 70 seconds. A later body edit ran only the 15-second body workflow and no CI workflow.
- Added `build` and `pr-body` as required GitHub Actions checks after both reported green.
- Implemented the stacked follow-up: no-op retarget detection plus a named, head-pinned atomic-prefix merge path; canary and final hosted evidence remain before merge.
