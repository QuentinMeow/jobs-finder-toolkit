# `automation/shared/tests` cannot collect in the primary checkout, and passes in every worktree

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: measured 2026-08-22 while establishing a gate baseline for the workspace
  lifecycle work (PRs #357–#361); reproduced on `main` at `02fa203`
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

The same test command produces the same verdict in the primary checkout and in a linked
worktree — or, if it cannot, it says which checkout it requires instead of aborting with
an error that reads like a real defect. Today an agent and the owner run the identical
command and get opposite answers, and neither can reproduce the other.

## Context

Measured, same machine, same interpreter, same command
(`.venv/bin/python -m unittest discover automation/shared/tests`):

| checkout | `private/` | result |
|---|---|---|
| primary `/…/jobs-finder-toolkit` | present | **exit 1**, 71 lines, **no unittest verdict at all** — collection aborts with `ConfigNotFound`. ZERO tests execute. |
| any linked worktree | absent | **exit 0**, `Ran 871 tests`, OK |

Cause: `private/` is git-ignored, so it exists ONLY in the primary checkout; a linked
worktree never has it. With the overlay mounted and no `config.yaml`, `_vendor/config.py`
REFUSES to fall back to the fictional `config.example.yaml` — correctly, because accepting
it would silently disarm the leak guard by making the identity tokens fictional. With no
overlay present, that same fallback is accepted and everything passes.

Why this is worth a P1 rather than a footnote:

1. **Every agent works in a worktree, so every agent sees green.** The owner, standing in
   the primary checkout, sees a suite that will not start. This is not a disagreement about
   a result — it is a disagreement about whether the suite ran.
2. It is the same defect class as `run_gates.py` reporting `ALL GREEN (0 gates)` on an empty
   lane set (fixed in #360) and as a checkout drifting 88 commits behind `origin/main`
   unnoticed (fixed in #357): **work verified against an environment nobody is standing in.**
   Three independent instances of one shape in a single session.
3. An agent that DID work in the primary checkout would see a permanent red it did not cause
   and cannot fix. Its only adaptations are to ignore red or to stop running the suite. Both
   are visible in this repo's history.

Related but NOT the same, and it should not be closed as a duplicate:
`tasks/0_backlog/2026-08-02-publish-suite-red-in-a-worktree-checkout/` is the inverse case —
two `automation/publish` tests going red **in a worktree** whose `private/` is a symlink.
That one is worktree-red; this one is primary-red and worktree-green. A fix for either may
inform the other; neither subsumes it.

Constraints on any fix:

- The refusal itself is correct and must not be weakened. Accepting the fictional config
  while a real overlay is mounted is what would disarm the leak guard.
- An agent must NOT author `config.yaml`. It holds the owner's real identity; a fabricated
  one arms the leak guard against the wrong tokens, which is worse than no guard. Restoring
  it is an owner action — but "the owner should restore a git-ignored file" is not a fix
  that survives the next fresh clone, which is why this is filed rather than just reported.
- `memory/decisions/config-discovery-example-fallback.md` records the discovery order this
  behaviour comes from. Read it before changing the order.

## Definition of done

- [ ] `.venv/bin/python -m unittest discover automation/shared/tests` reaches a unittest
      verdict (`Ran N tests` + OK/FAILED) in the primary checkout — not an aborted
      collection — with the overlay mounted and no `config.yaml`. Whatever it reports,
      it reports having run.
- [ ] If the suite genuinely requires a configured checkout, the failure names that
      requirement and the remedy, and is distinguishable from a leak-guard defect.
- [ ] A test or gate asserts the primary-checkout and worktree verdicts agree, so this
      cannot silently reopen.
- [ ] The leak guard is still armed by a real `config.yaml` and still refuses the fictional
      fallback while an overlay is mounted — verified by a test that fails if that refusal
      is removed.
