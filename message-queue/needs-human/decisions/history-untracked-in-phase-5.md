# Should workspace phase 5 untrack the 48 session handovers, or leave `history/` where it is?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-29
- **Source**: [workspace-restructure execution plan, phase 5 move table](../../../docs/designs/workspace-restructure/execution-plan.md#phase-5--the-lifetime-taxonomy-inside-private)
- **Blocks**: nothing. Phase 5 proceeds on the default path below and leaves
  `history/` untouched in both repos.
- **Default path**: `history/` does **not** move in phase 5. Both repos keep their
  tracked `history/` root, the reconciler keeps its `handover-present` check and its
  `CHECK_ROOTS` entry, and the row stays open in the plan with a pointer here.
- **Cost if wrong**: ratify
- **Safe to merge because**: `history/` does not move, so no file is rewritten and no link breaks.

## Background

The phase-5 move table carries one row that is unlike every other row in the plan:

```
history/ (both repos)  ->  private/local/history/
```

`private/local/` is git-ignored. So this row does not relocate files between two
tracked locations the way the other ~764 do — it **removes them from tracking
altogether**, in both repositories at once:

| repo | tracked files under `history/` |
|---|--:|
| public toolkit | 25 (24 session folders + a README) |
| private overlay | 23 |
| **total** | **48** |

The content would survive on this machine, in an ignored directory. It would not
survive a fresh clone, and it would not be on any remote.

**This is a recorded decision already, which is why it needs your eye rather than an
agent's.** The workspace ADR lists it under Consequences: *"Session handovers move to
`private/local/history/` (never committed), so the reconciler's `handover-present`
check becomes local-only and vacuous in CI."* The reasoning was that handovers are
records of agent sessions, not owner data, and that anything unresolved in one is
supposed to have been filed as a queue item or task anyway — `AGENTS.md` says so
outright: *"A handover is a history record, never the system of record."*

Three things have changed since that was written, and together they are why this is
being re-asked rather than executed:

1. **The phase-5 task's Definition of Done never mentions `history/`.** The plan says
   move it; the task that implements the plan does not list it. Task and plan disagree
   about the phase's scope, and the phase is being executed from the task.
2. **The plan's own rule 6 reads "Never delete owner data… Migration moves things; it
   never removes them."** Untracking 48 files sits uneasily beside that sentence even
   if handovers are agent-written rather than owner-written.
3. **It is entangled with four other surfaces**, all of which must change in the same
   commit: `verify_links.py` names `history/` in both `STRICT_ROOT_PREFIXES` and
   `PLAN_OR_RECORD_SOURCES`; `automation/reconcile/reconcile.py` keys its
   `handover-present` check on `history/conversations` and maps it in `CHECK_ROOTS`
   (and the maintainer pre-commit runs `--require-roots`, so a move-only commit
   cannot be committed at all); `AGENTS.md` carries `history/` as a top-level repo-map
   row; and the handbook describes it. None of that is hard — it is just a second,
   unrelated change riding inside the largest migration in the plan.

Phase 5 has enough coupled machinery of its own (a 9-pattern `.gitignore` rewrite
guarding 83,479 ignored files, eleven config keys, ~764 file moves across two repos).
Adding the one row that is irreversible-ish and touches a documented "never remove"
rule is the kind of thing that gets waved through inside a big diff.

## Options

### Option A — leave `history/` tracked; drop the row from phase 5 (default path)
Phase 5 ships without it. The reconciler keeps a real `handover-present` gate, the
48 records stay on both remotes, and the question comes back as its own small task
whenever you want it. Cost: the private overlay's lifetime taxonomy is complete
except for one root, and the ADR's recorded consequence stays unimplemented — a
documented intent with no matching tree, which is its own kind of drift.

### Option B — execute the row inside phase 5, as its own commit pair
Both repos' `history/` trees move to the ignored `private/local/history/` in one
commit each, together with the reconciler, link-checker and `AGENTS.md` edits.
Cost: 48 files leave tracking during the phase where a reviewer is least able to
notice; `handover-present` becomes vacuous in CI on the same day the biggest
migration lands, so the backstop for "did this session write a handover" is gone
exactly when it is most useful.

### Option C — keep `history/` tracked, but only in the private overlay
The public repo's 25 records move into the overlay's tracked `history/`; the
overlay's 23 stay. Nothing becomes untracked, the public tree loses a root that
never ships in the export anyway, and `handover-present` keeps working against the
overlay. Cost: it is a third position, not what the ADR says, so it needs its own
ADR; and the reconciler would have to learn to check a root outside its own repo,
which is the open `private-scope-reconciler` question wearing a different hat.

## Recommendation

**Option A for phase 5, then decide between B and C separately.** Not because B is
wrong — you recorded it deliberately and the reasoning holds — but because it shares
no mechanism with the lifetime taxonomy and it is the only row in the table that
subtracts from a tracked history. Bundling it means the review that should ask
"do I want these 48 records to stop existing on the remote?" happens inside a diff
of several hundred renames.

If you would rather not carry an unimplemented ADR consequence, **Option C** is worth
a look: it satisfies the actual goal (handovers stop living in the public toolkit
repo, so a forced add cannot leak one) without anything becoming untracked.

**Your answer:** ______
