# A `merge-tree` CONFLICT reads as `merged` in the status dashboard

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: adversarial audit of `automation/workspace/`, 2026-08-21 (finding
  "D3"); found while fixing the cleanup planner on branch
  `fix/i3-cleanup-evidence`, which closed it for the PLANNER only

## Goal

`automation/workspace/status.py` must not print `merged` for a branch whose
content exists nowhere in the base ref. Today it does, for every conflict class
git resolves by keeping the base's side verbatim.

## Context

`status._merged_state` (`automation/workspace/status.py:605-606`):

```python
if result.returncode in (0, 1) and _OID_RE.match(head):
    return "merged" if head == base_tree else "unmerged"
```

`git merge-tree --write-tree` exits **1** for a CONFLICTING merge and still
prints a tree. For every conflict class git resolves by keeping OUR side
verbatim — a file git auto-detects as binary (any NUL byte), a path carrying
`binary` or `-merge` in `.gitattributes`, a submodule pointer that diverged —
the printed tree **is** the base tree, so `head == base_tree` and the branch
reads `merged`. The code's own comment says exit 1 means "merging would change
main"; the code does not act on it.

Measured: a branch that regenerates a tracked binary file which main also
changed reads `merged`; a branch advancing a submodule pointer to a commit main
does not have (and which is not an ancestor of main's) reads `merged`.

**Live exposure**: this repository tracks 22 files containing NUL bytes — the
DOCX and PDF resumes and cover letters under `examples/`, the JPG screenshots,
and the `.json.zst` store blobs. Any branch regenerating one of those while main
also touched it is mislabelled. The `.gitattributes` variant is latent rather
than live (the root file currently carries only comments), but adding
`*.docx binary` — an entirely natural thing to do in a repo that renders DOCX —
turns it on.

**What is already fixed, and what is not.** `automation/workspace/cleanup.py`
now runs its OWN containment probe (`cleanup.Containment`) which answers exit 1
as NOT contained, and no destructive line is written without it — so the planner
no longer proposes deleting such a branch (`BinaryAndSubmoduleAreNotContainedTests`
in `automation/workspace/tests/test_cleanup.py` pins both shapes). The
DASHBOARD is untouched and still prints the wrong word, which is a
human-facing correctness problem in its own right and the reason this task
exists. Fixing `status.py` would also let the two probes collapse back into one.

Note `fix/i2-status-truth` was working in `status.py` at the same time; check
whether it already landed a fix before starting.

## Definition of done

- `status._merged_state` returns `unmerged` (or the unknown state, if the author
  prefers to fail closed) when `git merge-tree --write-tree` exits 1;
- `automation/workspace/tests/test_status.py` gains a fixture with a conflicting
  BINARY file and one with a diverged SUBMODULE pointer, asserting the dashboard
  does not say `merged`;
- `.venv/bin/python -m unittest discover automation/workspace/tests` exits 0;
- consider collapsing `cleanup.Containment` back onto `status._merged_state`
  once the two agree, or record why the planner keeps its own probe.
