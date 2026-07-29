# Handover — workspace-restructure-design

- **Date**: 2026-07-28
- **Task(s)**: `2026-07-28-workspace-phase-0…8-*` (backlog, unclaimed)

## What happened

- Designed the workspace layout across several iterations, each attacked by independent
  subagents. Two candidate designs were measured and rejected before the third; the owner
  settled the topology on 2026-07-28.
- **Settled:** the public repo stays the working root, the private overlay stays a git-ignored
  mount at `private/`, and nothing is hidden from agents. Defense is two layers — naming
  (every private path says `private/`, which requires deleting the eight symlinks that break
  it today) and detection (a review gate that fails until a public change is acknowledged in a
  tracked ledger).
- Private data is reorganised by lifetime: `me/` permanent role-agnostic, `companies/<key>/`
  permanent per company, `applications/` disposable, plus `market/`, `store/`, `skills/`, the
  private process folders, and `local/`. No `vendors/` root — an interview-running firm is a
  company.
- Two `AGENTS.md` guardrails added: agents never delete owner data under any condition, and a
  handover is a history record rather than the system of record.

## Where things stand

- Design family is three docs: `README.md` (target layout), `review-gate.md` (the gate spec),
  `execution-plan.md` (the self-contained implementation spec, written for a fresh agent).
- **11 backlog tasks**, one per phase plus two prerequisites. Each carries explicit blocking
  preconditions with a STOP-and-file rule rather than a default.
- **Phase 0 is unblocked and P0** — it repairs four gates that currently report success while
  inspecting nothing, including a reproduced case where the publish guard prints "Safe to
  publish" over a file containing the owner's real name.
- Decision recorded in `memory/decisions/workspace-layout-public-root-plus-review-gate.md`.
- Gates green: reconciler, leak guard, verify-links, vendor drift, instruction budget.

## Needs your attention

- [Workspace layout review](../../../message-queue/needs-human/reviews/workspace-restructure-plan.md)
  — answered and folded; open only until the owner confirms nothing was mis-folded, then safe
  to delete.
- [Decision: logs as store projections](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  — pre-existing, unrelated, still open.
- Eight items in the private queue mirror (3 decisions, 3 clarifications, 2 reviews) remain
  open from earlier sessions; none were touched.
