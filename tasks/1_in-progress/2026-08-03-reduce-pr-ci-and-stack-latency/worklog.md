# Worklog — 2026-08-03-reduce-pr-ci-and-stack-latency

## 2026-08-03 — session 1 (Codex `/root`)

- Created `codex/ci-pr-latency` from `origin/main` at `47cffb2`; no prior working-tree changes existed.
- Measured representative GitHub runs: successful normal PRs currently take about 3.2–3.5 minutes after a runner starts, with 49–55 seconds of dependency and LibreOffice setup and roughly 2 minutes of serial test suites.
- Began independent CI critical-path, risk-design, and `ai-harness` comparison investigations; next is the fail-closed lane design and baseline benchmark.
