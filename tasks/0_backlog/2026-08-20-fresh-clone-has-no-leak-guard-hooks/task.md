# A fresh clone pushes with no local leak guard until someone runs bootstrap

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: session 2026-08-20, cluster C11 (leak-guard usability, issue #307)
- **Claimed-by**:

## Goal

Make it impossible to work in a clone of this repository for any length of time
without noticing that the local leak guard is not installed — either by
installing the hooks automatically, or by making the absence loud. Today the
absence is silent, and silence reads exactly like "the guard is running".

## Context

Git never clones hooks. `.git/hooks/` is created fresh per clone and holds only
the `*.sample` files, so a brand-new checkout has **zero** active hooks. The
tracked hook sources live in `automation/hooks/` and are copied into place only
when someone runs:

```
.venv/bin/python automation/bootstrap_overlay.py
```

That step is documented — `CONTRIBUTING.md:36`, `docs/handbook/repo-map.md:56` —
but it is opt-in, and nothing detects that it was skipped.

What that means in practice:

- `automation/hooks/pre-commit` runs the staged-index leak guard
  (`check_public.py --staged`). Not installed ⇒ commits are unscreened.
- `automation/hooks/pre-push` runs the **armed** leak guard over every outgoing
  ref's immutable tree. Not installed ⇒ pushes are unscreened.
- Both hooks are the entire local half of the "tracked bytes must be
  publishable" invariant in `AGENTS.md`.

Verified this session on the actual checkout: `git config core.hooksPath` is
unset and `.git/hooks/` contains the two managed hooks only because bootstrap
was run here at some point. A clone that skips it gets neither.

**CI is the real backstop and it is intact.** `.github/workflows/ci.yml:90` runs
the policy gate lane with `JOBHUNT_PERSONAL_TOKENS` supplied from a repository
secret, so an armed leak-guard run does happen before anything merges. The gap
is therefore "local gate is opt-in by installation", not "nothing checks" — but
a leak that reaches a pushed branch is already public on the remote, and the
pre-push hook exists precisely because CI runs too late for that.

Options worth weighing (not a decision — this task is where that happens):

1. Have a cheap, always-run entry point (the gates runner, or a `git config
   core.hooksPath automation/hooks` shipped instruction) install or point at the
   hooks, so it cannot be forgotten.
2. `core.hooksPath` set once by bootstrap, so hook UPDATES also propagate — the
   current copy-in-place design silently keeps a stale hook after the tracked
   source changes.
3. A loud, non-blocking warning from a command people already run, naming the
   exact bootstrap line.

Option 1 or 2 changes clone-time behaviour, so it deserves the owner's eye
before it ships; a `message-queue/needs-human/decisions/` item may be the right
first move.

## Definition of done

- [ ] A clone that has not run bootstrap either has the hooks active or is told
      so by a command a contributor already runs, naming the fix command.
- [ ] `git config core.hooksPath` behaviour (or the copy-in-place equivalent) is
      covered by a test under `automation/hooks/tests/`.
- [ ] `CONTRIBUTING.md` and `docs/handbook/repo-map.md` describe whatever the
      new behaviour is, and stop implying the hooks are simply present.
