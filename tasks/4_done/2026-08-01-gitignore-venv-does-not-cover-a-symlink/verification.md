# Verification — 2026-08-01-gitignore-venv-does-not-cover-a-symlink

Retro-closure, 2026-08-02. Two of three bullets shipped earlier; the third is
discharged by the reading below plus one correction made in the closing commit.
Read the third section before treating this as fully clean.

## DoD 1 — `.gitignore` ignores a `.venv` symlink as well as a directory

`.gitignore:4-9` at HEAD:

```
# No trailing slash: `.venv/` matches only a DIRECTORY, and a git worktree is
# usually given its interpreter as a SYMLINK named .venv. That symlink is not
# ignored, shows as untracked, and its blob is an absolute path under the
# owner's home dir — which the leak guard cannot catch, because it scans file
# CONTENTS and a symlink has none to scan.
.venv
```

The trailing slash is gone and the reason is written at the site. Verified with a
real symlink in this worktree, which is the exact reproduction the task specified:

```
$ ln -s <main-checkout>/.venv .venv
$ git check-ignore -v .venv; echo "EXIT=$?"
.gitignore:9:.venv	.venv
EXIT=0
$ rm -f .venv
```

Exit 0 (was exit 1 before the fix), and the matching pattern is named.

## DoD 3 — no tracked file named `.venv`

```
$ git ls-files | grep -c '^\.venv$'
0
```

## DoD 2 — "document the worktree workflow with the staging rule, OR give `ledger_close.py` an interpreter argument"

**Option B is impossible: `ledger_close.py` does not exist.**

```
$ ls automation/publish/
check_public.py  export_public.py  review_gate.py  review_ledger.yaml
sync_skill_manifests.py  tests
$ find . -name "ledger_close*" -not -path "./.git/*"
(no output)
```

Option A is what the tree carries. `skills/github-workflow/SKILL.md:429` is the
staging rule (`git add <the paths this commit changes>   # explicit pathspecs;
never -A or .`), and `:573-580` carries the worktree recipe.

**One correction made in the closing commit:** the sentence that justified the
staging rule at `SKILL.md:434-435` still read

```
`git add -A` is wrong here for a reason beyond tidiness: `.gitignore` lists
`.venv/`, which does not cover a `.venv` **symlink**, so `-A` stages it.
```

— a claim about `.gitignore` that DoD 1 made false. It is replaced with a reason
that is true at HEAD. Without that, closing this task would have left the repo
asserting the very defect it fixed.

**Honest residual:** the task framed DoD 2 as an owner call between A and B. The
owner never answered; B's subject no longer exists; A is what shipped. The task
is closed on A having shipped, which is reversible by a `git mv` back if the
owner disagrees.

## Eval gate

`skills/github-workflow/SKILL.md` edit: **skipped with rationale** — mechanical,
one sentence, corrects a factual claim about `.gitignore`. No routine, gate,
verdict, or step semantics changed, so no `evals/README.md` MUST-run trigger
fires.
