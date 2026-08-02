# Two publish tests go red in a git worktree where `private/` is a symlink

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: measured 2026-08-02 while running `run_gates.py` over the nine-rung defect
  stack from a `.claude/worktrees/` checkout; reproduced identically on `main` at `f360aec`
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

`.venv/bin/python -m unittest discover automation/publish/tests` should pass in a
maintainer's **worktree** checkout the same way it passes in the primary checkout, or the
two tests below should say plainly that they require the primary checkout instead of
failing with an assertion that reads like a real leak-guard defect.

## Context

A `git worktree` has no `private/`, no `config.yaml` and no generated runtime skill
adapters — those are all git-ignored, per-checkout artifacts. The natural way to give a
worktree an overlay is to symlink the primary checkout's, and that is what makes these two
fail:

- `test_export_destination.DestinationRefusalOrderingTests.test_the_cli_refuses_dest_private_before_the_arming_gate`
  asserts the refusal message names `<this checkout>/private`. The CLI resolves the real
  path, so with a symlinked overlay it correctly names the **primary** checkout's
  `private/` and the assertion fails on a string comparison. The refusal itself fired, at
  the right time, for the right reason — only the path in the message differs.
- `test_skill_manifests.LiveTreeTests.test_private_skills_reach_the_runtime_from_the_overlay`
  fails with `.agents/skills/<name> missing — run bootstrap_overlay.py`. A fresh worktree
  has no generated adapters, and the message already names the fix; the test just has no
  precondition guarding it.

This is the same family as the defect `fix/commands-that-fail-on-a-healthy-repo` closed for
`verify-links` (`279847c`): a gate that is red on a green tree in a maintainer checkout
because it read the overlay under conditions its author did not have. That one was fixed by
passing the flag the pre-commit hook already passed. There is no equivalent flag here.

**Neither test is red in CI**, which has no overlay at all — both suites exit 0 with the
overlay unmounted (40 tests, `OK (skipped=1)`), so nothing is blocked and no PR is at risk.
The cost is that a maintainer working in a worktree cannot get a clean `run_gates.py`, and
must diff the failures against `main` by hand to learn they are environmental. Doing that
by hand is exactly the manual step `run_gates.py` was built to remove.

Note that a symlinked `private` is also **not** matched by `.gitignore`'s `private/` entry
(trailing slash matches a directory, not a symlink), so it shows as untracked — the same
shape as `tasks/4_done/2026-08-01-gitignore-venv-does-not-cover-a-symlink`. Fixing that
entry may belong with this task; it is the reason a worktree run needs explicit pathspecs
on every `git add`.

Three options, in the order they seem worth trying — none chosen, this is a P2:

1. Give both tests a precondition: skip unless `private/` is a real directory and the
   adapters exist. Cheapest, and honest — a skip says "not applicable here", which is what
   is true.
2. Compare resolved paths in the destination test (`Path.resolve()` on both sides) so a
   symlinked overlay passes for the right reason. Fixes one test, not the other.
3. Have `bootstrap_overlay.py` support a worktree — generate the adapters and accept a
   symlinked overlay as mounted. Most work, and the only one that makes a worktree a
   first-class maintainer checkout rather than a special case.

## Definition of done

- From a `.claude/worktrees/` checkout with `private/` symlinked to the primary checkout's
  overlay, `.venv/bin/python automation/gates/run_gates.py --group both` exits 0, **or**
  the two tests skip with a message naming the precondition they need.
- Whichever way it goes, the primary-checkout behaviour is unchanged: both tests still
  fail if the export CLI stops refusing a `private/` destination, or if the runtime
  adapters genuinely go missing. Prove that by planting each defect and watching it go red.
