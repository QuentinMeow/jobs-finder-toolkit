# Handover — soffice-sandbox-crash-task

- **Date**: 2026-08-02
- **Task(s)**: `2026-08-02-soffice-crashes-under-codex-sandbox`

## What happened

- Nothing is half-implemented: the crash cause is established and a public P1 backlog task now carries the full evidence and acceptance criteria.
- Before the investigation, repeated LibreOffice aborts looked like an application or document problem; the macOS log proves the inherited Codex sandbox denies the LaunchServices lookup required during native app initialization.
- Before the task, the converter described every failure as a transient no-output flake and retried it; the task records how that behavior expanded four logical conversions into eight deterministic crashes.

## Where things stand

- The documentation-only branch is ready for review. The fix remains unclaimed in [`2026-08-02-soffice-crashes-under-codex-sandbox`](../../../tasks/0_backlog/2026-08-02-soffice-crashes-under-codex-sandbox/task.md).

## Decisions made for you

- Filed a public harness task because the defect is generic tooling behavior; all personal paths, report identifiers, and private job-hunt context were excluded.
- Kept the task in backlog rather than implementing the fix because the owner requested a task PR; claiming it later is reversible and visible.
- Required signal-aware fail-fast behavior while retaining the exit-0/no-PDF retry because the two failure classes have different evidence and remedies.

## If X then Y

- If a future macOS converter proves it can initialize inside the Codex sandbox, keep signal-aware reporting anyway; only the environment preflight strategy should change.
- If no reliable pre-launch sandbox marker exists, allow at most one classified probe and stop on `SIGABRT`; never restore the unconditional retry.

## Dead ends

- Treating an existing binary as usable is insufficient; that is the current preflight defect.
- Pointing at another macOS LibreOffice bundle is not evidence of sandbox escape because the bundled build still initializes the native application layer.
- Reproducing the abort again was unnecessary after the system log named the denied service.

## Needs your attention

- No new decision is required for this task PR.
- 42 pending · top: [`job-search-us-only-default-asymmetry`](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md) — inconsistent search and draft defaults can repeatedly admit roles that later cannot be drafted.
