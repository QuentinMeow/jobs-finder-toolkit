# Reduce PR, CI, and stacked-merge latency

- **Priority**: P0 (blocks work)
- **Area**: harness
- **Source**: Owner request in the 2026-08-03 CI-latency session
- **Claimed-by**: Codex `/root`

## Goal

Make routine pull requests and reviewed stacks reach a mergeable state substantially faster without weakening public-data, email-safety, review, or correctness guardrails.

## Context

The current GitHub Actions workflow runs dependency installation, LibreOffice installation, every test suite, example rendering, exporter tests, and whole-tree guards for every pull request, including documentation-only changes. The same full workflow runs again on each `main` update, and stacked changes can multiply that cost. Work must be isolated on `codex/ci-pr-latency` because a separate stress-testing agent may use another worktree. Reuse proven ideas from `~/code/ai-harness/` where they fit, but preserve this repository's fail-closed review and leak rules.

## Definition of done

- Record current GitHub job and step timings and a local stage-level baseline.
- Add a tested, fail-closed change classifier that maps ordinary diffs to the smallest safe test lanes and sends unknown or high-risk changes to the full suite.
- Keep irreversible/supply-chain policy gates always blocking while making unrelated long-running render and test lanes conditional or manual.
- Parallelize independent required lanes so the critical path is the slowest relevant lane rather than the sum of all suites.
- Add a deliberate, verified fast path for merging fully reviewed native stacks atomically.
- Validate documentation-only, targeted-code, shared-infrastructure, and full/manual scenarios; publish the implementation in reviewable PRs and record remote timing evidence.
