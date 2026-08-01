# .gitignore's `.venv/` does not cover a `.venv` SYMLINK, so a worktree can commit one

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: hit while working a fix in a git worktree
  (branch `fix/45-us-remote-residency`, 2026-08-01). Owner spotted it and asked
  for it to be filed rather than fixed in that PR.
- **Claimed-by**:

## Goal

Decide and apply how `.venv` should be ignored so that the symlink form — which
the worktree workflow produces — cannot be committed, and say so wherever that
workflow is described.

## Context

`.gitignore:4` reads `.venv/`. The trailing slash restricts the pattern to
DIRECTORIES. A git worktree has no `.venv` of its own, so the working practice is
to link the main checkout's interpreter in:

```bash
ln -s /path/to/main/checkout/.venv <worktree>/.venv
```

Git treats a symlink as a FILE, not a directory, so `.venv/` does not match it.
Verify with `git check-ignore -v .venv` inside such a worktree: it exits 1 (no
pattern matched) and `git status --porcelain` shows `?? .venv`.

Why it matters beyond tidiness: the link's target is an absolute path containing
the owner's home directory. Committed, it is broken for every other checkout AND
it carries a personal token in a place the leak guard is not certain to catch —
`automation/publish/check_public.py` scans file CONTENTS, and a symlink's blob is
its target path rather than text the scanners walk. Any agent that reaches for
`git add -A` in a worktree commits it.

The mechanical fix is one character (`.venv/` -> `.venv`), which then matches both
the directory and the symlink. It is deliberately NOT being applied on the branch
that found this, because it comes with an owner call that is worth making
explicitly:

- Should the worktree workflow (create a worktree, link `.venv`, run the gates,
  close the ledger) be documented at all — in `docs/handbook/` or `CONTRIBUTING.md`
  — given that it is currently passed agent-to-agent in prompts? If it is
  documented, the `.gitignore` line and the "stage explicitly, never `git add -A`"
  rule belong in the same place.
- Or should the link be avoided entirely — `ledger_close.py` is the only consumer
  that needs `<root>/.venv/bin/python` to exist (it composes the interpreter path
  from its `root` argument); an `--python` argument there would remove the reason
  to create the link at all.

## Definition of done

- `.gitignore` ignores a `.venv` symlink as well as a `.venv` directory, verified
  by `git check-ignore -v .venv` exiting 0 in a worktree that has one.
- Either the worktree workflow is documented with the staging rule, or
  `ledger_close.py` takes an interpreter argument so no link is needed — whichever
  the owner picks in the decision above.
- No tracked file named `.venv` exists anywhere in the repo (`git ls-files | grep
  -c '^\.venv$'` is 0).
