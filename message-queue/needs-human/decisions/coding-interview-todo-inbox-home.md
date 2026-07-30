# Where does the coding-interview screenshot inbox live after phase 5?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-29
- **Source**: [workspace-restructure execution plan, phase 5 move table](../../../docs/designs/workspace-restructure/execution-plan.md#phase-5--the-lifetime-taxonomy-inside-private)
- **Blocking**: nothing. Phase 5 proceeds on the default path.
- **Default path**: the inbox stays exactly where it is. Your drop folder does not
  move and neither private skill changes the path it polls.

## Background

Two private skills poll one untracked directory for screenshots you drop into it
during a coding interview. The execution plan's move table has a row for it that
reads, in full, "keep as-is — an **untracked** screenshot inbox two private skills
poll; moving it orphans them."

That reasoning does not survive phase 5, because **both of those skills are being
edited by this phase anyway.** Six other lines across their `SKILL.md` and
`reference.md` name the interview tree as a write target and have to be repointed at
`companies/<key>/` regardless — if they were not, an agent would keep recreating the
old tree after the migration. So "moving it orphans them" is no longer the cost it
was when the row was written; the cost is one more line in an edit already happening.

What the row does buy, and it is not nothing: **your muscle memory.** This is a
folder you drag files into under time pressure, mid-interview. That is a bad moment
to discover a path changed.

What it costs is that phase 5 does not finish the job it exists to do. The interview
tree's 552 tracked files all leave; this one untracked directory keeps
`interviews/company-specific/` alive as a two-level husk holding nothing else. A root
that is retired everywhere except one hidden corner is exactly the state the phase-2
record warns about — the leak guard's deny rule, the link checker's skip list, and
every doc sentence that says "the interviews tree" all stay half-true, and the next
person to read them cannot tell which half.

## Options

### Option A — leave it (default path)
Zero risk to your workflow. `private/interviews/company-specific/TODO/` survives as
the only thing under a root the phase otherwise empties, and the docs describing that
root keep a footnote forever.

### Option B — move it to `private/me/interviews/practice/TODO/`
`me/interviews/practice/` is a directory the design already defines, and this is
material that is yours rather than any company's, so it is the taxonomically right
home. Both skills' polling lines change in the same commit. Cost: the path you drag
to is different from tomorrow, and if you have a Finder sidebar shortcut or an alias
pointing at the old one, it breaks silently — the folder is untracked, so nothing
warns you.

### Option C — move it, and leave a symlink at the old path
Muscle memory keeps working, the tree is clean, both skills poll the new path. Cost:
this repo deleted its last eight symlinks in phase 4 on the grounds that a symlink
hides which repo a path belongs to, so adding one back needs a reason better than
convenience — and the leak guard would need to learn it is benign.

## Recommendation

**Option A while this is pending, Option B when you answer.** The husk is a real cost
but a documentation-shaped one, and it is reversible at any time; changing a folder
you use under interview pressure without telling you first is not the kind of thing
to slip into a 764-file migration. If you say B, it is a two-line change plus a
`mv`, and it can land any time after phase 5 — it does not need to be in it.

Option C is listed for completeness and is not recommended: phase 4 removed every
inbound symlink in this repo for reasons that still apply.

**Your answer:** ______
