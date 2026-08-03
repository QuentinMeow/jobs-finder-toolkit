# Workspace layout: keep the public repo as the working root; defend by naming + a review gate

- **Status**: decided
- **Date**: 2026-07-28
- **Decided by**: owner
- **Correction (2026-08-02, forward-link — the Consequences text below is left intact
  because an ADR is immutable)**: the third Consequences bullet states as accomplished fact
  that "Session handovers move to `private/local/history/` (never committed)". That move
  never happened and is not planned. Handovers are still written to
  `history/conversations/<YYYY-MM-DD>-<slug>/` per `AGENTS.md`, the reconciler's
  `handover-present` check still reads `history/conversations`, and 35 handovers are tracked
  (`git ls-files 'history/conversations/*/handover.md' | wc -l`, 2026-08-02) — several dated
  after this ADR. Whether `history/` moves at all is still open in
  [`message-queue/needs-human/decisions/history-untracked-in-phase-5.md`](../../message-queue/needs-human/decisions/history-untracked-in-phase-5.md),
  whose default path is "`history/` does **not** move". Write your handover to
  `history/conversations/`; do not follow that bullet.

## Context

Two questions were open: whether to invert the topology so the private overlay becomes the
working root (with public content reached through symlinks), and how to stop an agent putting
personal content into the published repo.

Three rounds of adversarial review measured the inversion. Its safety claim did not hold —
the symlink direction blocks staging a *public* file into the *private* repo, which is
harmless, while the actual leak (private text written into a public file) passes straight
through and leaves the working root's `git status` empty. Its costs were large and concrete:
`.venv` unreachable, `rg`/`find`/`grep` blind to public code by default (`rg X public/`
returns nothing — only `--follow` or naming each link works), `getcwd()` escaping the working
root so config discovery silently loads the example persona, `git worktree` breaking while
reporting clean, and no git hooks on the repo that would host most commits.

## Decision

**The public repo stays the working root.** The private overlay remains a git-ignored mount
at `private/` with its own remote. Nothing is hidden from agents; instructions route them
into `private/` for real data, as `config.*_path()` already does.

Preventing writes to public files is explicitly **not** a goal — agents need that access to
use and develop the toolkit. Defense is two layers:

1. **Naming carries the instruction.** Every private path contains `private/`. The eight
   symlinks that currently break this — four `skills/job-search/profiles/<personal-name>.yaml`
   whose *filenames are personal tokens in the public tree*, two
   `references_private/`, and two overlay-only skill trees — are deleted and replaced by config accessors
   and runtime adapter entries pointing at `private/skills/`.
2. **Detection after the fact.** A review gate: every commit touching the public tree fails a
   test until a row is appended to a tracked ledger recording the commit range, file count, a
   recomputed digest of the diff, and a finding. Runs in `pre-commit` and CI.

Inside `private/`, data is organised by lifetime: `me/` (permanent, role-agnostic),
`companies/<key>/` (permanent per company, including how they interview), `applications/`
(disposable), plus `market/`, `store/`, `skills/`, the private process folders, and `local/`
for never-commit.

Four supporting calls made the same day:

- **No `vendors/` root.** An interview-running firm is a company — it has its own loop and
  its own question set — so it gets a `companies/<key>/` like any employer.
- **Agents never delete owner data**, under any condition. The taxonomy's job is to make the
  *user's* `rm -rf` safe, not to authorise an agent's. Recorded as an `AGENTS.md` guardrail.
- **The review gate watches every tracked public file except its own ledger**, and one row may
  cover a commit range. An agent may sign its own review; a human row is required only when
  the advisory detector fires.
- **A handover is a history record, not the system of record.** Anything unresolved gets its
  own queue item, task, or design file carrying full context, because the handover is
  local-only. Recorded as an `AGENTS.md` rule.

## Alternatives considered

- **Private repo as working root, public via a `toolkit/` or `public/` symlink door** — lost
  on measured cost; its one real benefit (no personal-token filename in the public tree) is
  delivered by the config accessors above with no topology change.
- **Per-leaf `.private` / `.local` directory markers** — lost because `*.private/` does not
  ignore a symlink (git treats one as a file), and markers collide with the task-ID regex and
  the skill-name-equals-directory invariant.
- **Blocking writes to public files** — rejected as a goal; it would break the toolkit's own
  development.
- **An automated PII detector as a blocker** — lost on measurement: cross-referencing public
  files against private company names matches 51 of 177 tokens, led by ordinary English words
  (`canonical`, `writer`, `render`, `lambda`). It survives as an advisory hint inside the
  gate.

## Consequences

- The daily developer experience is unchanged: `.venv`, `rg`, `git status`, `git worktree`,
  config discovery, and the existing hooks all keep working.
- Every toolkit commit needs a review-ledger row. If that rate becomes painful, the relief is
  batching one row across a commit range — not narrowing what the gate watches, since the
  excluded paths (`memory/`, `tasks/`, `history/`) are where prose about real work is written.
- Session handovers move to `private/local/history/` (never committed), so the reconciler's
  `handover-present` check becomes local-only and vacuous in CI.
- Applications become genuinely disposable only once the skip-log stops being derived from
  the application folders; until then, deleting one and re-syncing re-opens the posting.
- Revisit if the review-gate row rate proves unworkable in practice, or if a leak reaches the
  public remote despite both layers.

Design: [`docs/designs/workspace-restructure/`](../../docs/designs/workspace-restructure/README.md).
