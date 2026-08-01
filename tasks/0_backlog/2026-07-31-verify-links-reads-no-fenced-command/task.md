# verify-links reads no fenced command, so runnable docs rot in total silence

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: session 2026-07-31, split out of the retired-roots / message-queue tiering PR
  on `wip/08-stale-design-paths`
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Give `automation/gardener/verify_links.py` a pass that reads paths out of fenced code
blocks, so a copy-pasteable command naming a file that no longer exists is at least
counted, and decide per source tier whether it gates.

## Context

`_mask_fences` blanks every ` ``` ` block before either pass runs. That is correct for
the two passes that exist — a fence full of illustrative markdown must not be read as
links — but it means **fenced content is the one surface with no counter at all**. A
stale path there is not advisory, not permitted, not unrecognised: it is in no bucket.

The live instance that prompted this. `docs/designs/filtering-variant-safeguards/execution-plan.md:339`
and `:372` both carry a "Stage gate" block a maintainer is meant to paste:

```
.venv/bin/python automation/maintenance/gardener/gardener.py verify-links
```

`automation/maintenance/` was split into `automation/` by 031e05d, so that line has
exited with `No such file or directory` since the split. Thirty tracked lines still
name `automation/maintenance/`; the ones in prose are now visible (this session added
`RETIRED_ROOTS`, which tiers a retired root followed by a path), but the ones inside
fences remain invisible, because no pass reaches them.

Why it was split out rather than done in that PR:

- It needs real shell tokenization, not a regex. A command line mixes flags, `--flag=path`,
  `$VAR`, `python -m module` (not a path), quoted paths, heredocs and pipes. Guessing which
  token is a path is the whole difficulty, and guessing wrong fails OPEN or floods the
  report.
- It needs a fence-language policy. ` ```bash ` blocks are commands; ` ```text `,
  ` ```yaml ` and the untagged fences full of illustrative trees in `templates/` and
  `docs/handbook/doc-style.md` are not, and several deliberately show paths that must not
  exist.
- It changes what `_mask_fences` is for. That function carries a careful argued docstring
  about why CommonMark's indented code block is deliberately NOT masked; a second reader
  of fences has to be reconciled with it rather than bolted beside it.

Python docstrings in `automation/**/*.py` have the same gap — `check_public.py` and
`review_gate.py` both name paths in theirs — but the source enumeration is `git ls-files
'*.md'`, so no `.py` file is read at all. Decide whether that is in scope here or a third
task.

Tiering should follow the rule the rest of the module already uses: fate is decided by
what the SOURCE document is for. A dead command in `docs/handbook/` (reference) is a
maintainer about to hit an error and should gate; the same block inside `tasks/4_done/`
is a record of what was run that day and must stay permitted.

## Definition of done

- [ ] `.venv/bin/python automation/gardener/verify_links.py` reports the two
      `filtering-variant-safeguards/execution-plan.md` stage-gate lines, in a named class,
      with `automation/gardener/gardener.py` suggested as the successor.
- [ ] A fence whose content is illustrative rather than runnable (an untagged tree in
      `templates/`, a ` ```text ` block) produces no finding — covered by a test.
- [ ] The tier rule holds: a dead command in a reference doc is fatal, the same command in
      `tasks/4_done/` is permitted. One test each.
- [ ] `python -m unittest discover automation/gardener/tests` passes, and the repo run is
      still `0 broken` or every finding it newly surfaces is repaired in the same PR.
- [ ] A decision recorded on whether `.py` docstrings join the source set.
