# Does the merge-then-answer queue redesign apply to the private overlay?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-01
- **Source**: [the queue schema this question is about](../../../templates/queue/decision.md)
- **Blocks**: nothing. The public tree ships the new schema either way; this only decides
  whether the overlay follows.
- **Default path**: **public tree only for now.** The overlay's queue keeps its current
  shape; no agent migrates overlay items or edits overlay templates.
- **Cost if wrong**: ratify
- **Safe to merge because**: the default writes nothing in the overlay at all — it is a
  second git repo, and this PR does not touch it. Adopting later is the same mechanical
  backfill run against that tree.

## Background

This PR adds two required keys (`Cost if wrong`, `Safe to merge because`) to the public
decision schema, retires `Blocking:` as a stop signal in favour of `Blocks:` prose, and
adds `message-queue/ANSWERS.md` as the owner's batch answering surface.

The private overlay is a **separate git repo** mounted at `private/`. It has its own
`message-queue/`, `tasks/`, evals, and pre-commit hooks — and, critically, **no
reconciler**. `automation/reconcile/reconcile.py` resolves its root from `__file__` and
checks `REPO_ROOT / "message-queue"`, so it never sees the overlay's queue. Whether a
private-scope reconciler should exist is itself an open item
(`private-scope-reconciler.md`, filed 2026-07-29, deferred by you).

That is what makes this a real question rather than a formality: **adopting the schema in
the overlay would give it required keys that nothing enforces.** That is precisely the
failure mode this redesign exists to fix — `Blocking: yes` was a documented rule with no
mechanism, and it stayed dead for the life of the repo because nothing ever checked it.

The overlay's queue is live: its `needs-human/clarifications/` folder holds three open
items today, so this is not a hypothetical tree.

## Options

### Option A — public tree only, for now (the default path)

The overlay keeps its current queue shape until it has a reconciler.

- No unenforced schema is introduced anywhere.
- Keeps this PR's blast radius inside one repo, which matters because the overlay has
  substantial uncommitted owner state.
- Cost: two divergent queue formats. An agent working across both must remember which tree
  it is in. Bounded by the fact that the overlay's items are read by the same agents that
  read this contract.

### Option B — adopt in both now

Backfill the overlay's items and copy the templates across.

- One format everywhere; no divergence to remember.
- Cost: the keys are advisory in the overlay indefinitely, and the backfill would touch a
  tree that currently has a large amount of uncommitted owner work in it — including
  pending deletions. Editing it without your involvement is not safe.

### Option C — adopt in both, gated on the private-scope reconciler

Answer `private-scope-reconciler.md` first; if a reconciler ships there, adopt the schema
in the same change.

- Enforcement and schema arrive together, which is the only combination that has worked.
- Cost: couples this to an item you already deferred once. It may sit for a while.

## Recommendation

**Option A now, Option C as the real answer.** The divergence cost is small and visible;
the cost of a required-but-unchecked key is exactly the bug being fixed. If you want one
format everywhere, the honest sequencing is to decide `private-scope-reconciler.md` first
and let the schema follow enforcement rather than lead it.

**Your answer:** ______
