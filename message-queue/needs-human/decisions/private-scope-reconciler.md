# Should the reconciler also validate the private overlay's process layer?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-29
- **Source**: [workspace-restructure execution plan, item 0.10](../../../docs/designs/workspace-restructure/execution-plan.md)
- **Blocking**: nothing. The overlay's new pre-commit hook already picks up an
  answer of "yes" with no further edit — it probes for the flag and uses it the
  moment it exists.
- **Default path**: no private-scope reconciler runs. The overlay hook reports the
  skip on every commit rather than staying silent about it.

## Background

Phase 0d installed `automation/hooks/overlay-pre-commit` into `private/.git/hooks/`.
Item 0.10 asked it to "run the private-scope reconciler if one applies". None
applies today, and that is by design, not by omission:

`automation/reconcile/reconcile.py`'s own docstring says its checks "validate the
PUBLIC tree only (the private overlay mirror is its own repo with its own
lifecycle)", and it hardcodes `REPO_ROOT` to this repo. Pointing it at the overlay
is therefore a change to a recorded design position, which is yours to make.

The overlay does carry the same process layer — `message-queue/`, `tasks/`,
`memory/`, `templates/`, `history/` — so the checks are meaningful there. Measured
against the overlay as it stands on 2026-07-29 (read-only dry run, nothing
written):

| check | findings |
|---|---|
| queue-schema | 0 |
| task-structure | 1 — one task in the overlay's `4_done` folder has no verification file |
| memory-schema | 0 |
| memory-index | 1 — the overlay's memory index is missing (`--fix-index` would write it) |
| handover-present | 0 |
| roadmap-fresh | 0 (the overlay has no roadmap folder — the check no-ops) |
| skill-manifests | n/a — a public-tree surface |

So switching this on TODAY would block every commit in the overlay until those two
are cleared, and only you can clear them (agents never write tracked overlay files).

## Options

### Option A — leave it off (default path)
The overlay hook keeps reporting "no private-scope reconciler applies — skipped".
No behaviour change, no risk, and the overlay's process files stay unvalidated.

### Option B — add `--root <path>` to the toolkit reconciler, you clear the two findings, then it blocks
Small change (the module already takes its roots from one constant). The hook
already probes `reconcile.py --help` for `--root` and will start using it
automatically. Cost: two fixes in the overlay first — add a verification file to
that done task, and regenerate its memory index once — otherwise your next overlay
commit is refused.

### Option C — add `--root`, but have the hook block only on findings the commit touches
A ratchet: pre-existing findings are printed but do not block; a commit that
introduces or touches a broken process file is refused. Nothing to clear first.
Cost: more logic in a shell hook, and a stale finding can linger indefinitely.

## Recommendation

**Option B.** The overlay is about to hold most of your commits, its process layer
is the same shape as the public one, and two one-time fixes is a small price for a
real gate. Option C's ratchet buys convenience by making the gate conditional,
which is the failure mode this whole phase exists to remove.

**Your answer:** ______
