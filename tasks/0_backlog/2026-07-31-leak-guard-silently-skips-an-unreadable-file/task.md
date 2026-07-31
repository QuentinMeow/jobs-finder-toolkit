# The leak guard silently skips any file it cannot read, including a broken symlink

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: re-filed 2026-07-31 from `2026-07-21-tree-instructions-validator`, which was deleted — this was the one item in it with a live consequence
- **Claimed-by**:

## Goal

Stop `check_public.py` from reporting a clean tree when a file in that tree was never inspected.

## Context

`_read_text()` returns `None` on `OSError`, and the caller treats `None` as "nothing to scan" and
moves on. A **broken symlink**, a permissions failure, or an I/O error therefore produces a file
that is counted as walked but never read, and the guard still prints
`OK: no public-repo leaks detected. Safe to publish.`

That is the same fail-open shape as the four gates repaired in
`2026-07-31-four-gates-that-inspected-nothing` — which fixed four *different* checks and does not
touch this one. The distinction that matters: returning `None` for a **binary or non-UTF-8** file
is correct and must stay (there is genuinely no text to scan); returning `None` for a file the
process could not *open* is not, because the guard has no idea what was in it.

**Verify-with**:

```bash
grep -n 'def _read_text' -A 12 automation/publish/check_public.py
# and, as a planted defect: create a broken symlink under a scanned tree, then
.venv/bin/python automation/publish/check_public.py
```

## Definition of done

- [ ] An unreadable file (broken symlink / `OSError`) is a **finding**, not a silent skip — the
      guard names the path and exits non-zero
- [ ] A binary or non-UTF-8 file still skips quietly; that path is not regressed
- [ ] A planted-defect test proves both directions: the broken symlink fails the guard, the
      binary file does not
- [ ] The summary line reports how many files were actually read, so "clean" can be distinguished
      from "inspected nothing"

## Why the rest of the tree-instructions validator was dropped

The task this was carved out of proposed a five-check validator over the folder-scoped
`AGENTS.md` tree. Re-measured 2026-07-31, that tree is: **2 tracked `AGENTS.md`** (the root and
`docs/designs/AGENTS.md`, the only leaf, 8 lines) and **zero `agents-references/` directories
anywhere**, so two of its five checks have no subjects at all. Its own owner-decided ADR,
`memory/decisions/tree-instruction-growth-policy.md`, mandates *reactive* leaf creation, which
deliberately holds that surface near zero. Two of its remaining claims were also found false:
`instruction_budget.py` **does** discover the leaf (`_iter_targets` walks the tree for
`AGENTS.md`, and `docs/designs/AGENTS.md` appears in the report), and the exporter follows the
`CLAUDE.md -> AGENTS.md` shim **on purpose**, documented in `_copy_tree`'s docstring, so that the
exported tree works in a checkout without symlink support. This item was the only one left.
