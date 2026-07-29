# Worklog — 2026-07-28-workspace-phase-3-review-gate

<Append-only, newest at bottom, one entry per session. Keep entries short:
what moved, what's next, what surprised you.>

## 2026-07-29 — session 1 (agent)

- Bookkeeping only: the work was already implemented and pushed as PR #85
  (branch `phase-3/review-gate`, three commits on top of
  `phase-0d/link-checker-and-hooks`) before this session started. Moved the
  task from `0_backlog/` to `3_in-review/` and set `Claimed-by`.
- The task's own "Blocking preconditions" section required Phase 0 to be
  merged before starting. It records "Phase 0 merged" as already true, but
  as of this session none of phase-0's PRs (#81–#84) are actually merged to
  `main` yet — they're open, stacked underneath this branch. Left the
  precondition text untouched per instructions; flagging the discrepancy
  here rather than editing the task's own claim.
- Commits on `phase-3/review-gate`:
  - `92abe36` "Add the public-change review gate". New
    `automation/publish/review_gate.py` + `automation/publish/
    review_ledger.yaml`, watching every tracked file except the ledger
    itself (excluding `memory/`, `tasks/`, `message-queue/`, `history/` per
    the owner's answered decision). Distinguishes shallow-clone, ledger-out-
    of-sync, and not-applicable-in-this-history failure modes; pre-commit
    re-verifies the last 5 rows, CI runs `--verify-all`. 39 new gate tests.
  - `ef2d0a3` "Redact the owner's application history from the public tree".
    The gate's first real run caught real employer names, alias splits, a
    vendor name, and a verbatim recruiter email that a prior merged PR (#80)
    had put into `design/`, backlog tasks, an ADR, and a queue item — none
    of which the identity-token leak guard catches, since company names
    aren't identity tokens. Replaced with the shape each example needed
    without the real content. This is the concrete argument for the gate
    existing.
  - `97a7303` "Acknowledge the phase-3 review range" — ledger-only commit
    that closes the branch's own review range without re-triggering the
    gate.
- Surprise: the gate caught a real leak in a PR (#80) that had already
  merged and passed every other existing check — exactly the failure mode
  phase 3 exists to close. Worth noting in case anyone assumed the leak
  guard alone was sufficient.
- Verified on `chore/workspace-phase-bookkeeping` (based on
  `phase-4/remove-inbound-symlinks`, which carries this branch) — see
  `verification.md`.
