# Verification — 2026-08-20-workspace-git-status-command

## Synthetic Git-state matrix

```
$ .venv/bin/python -m unittest discover automation/workspace/tests -v
test_compact_view_shows_every_worktree_and_branch_with_truthful_state ... ok
test_optional_private_repository_is_included_only_when_it_is_git ... ok
test_queries_do_not_depend_on_the_callers_current_directory ... ok
test_renames_are_one_changed_path_and_verbose_shows_both_names ... ok
test_toolkit_guard_refuses_an_unrelated_repository ... ok
test_verbose_view_adds_files_commits_remotes_and_redacts_credentials ... ok

Ran 6 tests in 1.114s
OK
```

The fixtures cover clean/dirty/staged/modified/untracked paths, renames,
detached worktrees, local-only and cached-remote-only refs, merged/unmerged
state, synchronized/ahead/behind/diverged/missing upstreams, credential
redaction, an absent private overlay, and invocation from another directory.

## Public export

```
$ .venv/bin/python -m unittest automation.publish.tests.test_export_enumeration
Ran 22 tests in 5.481s
OK
```

The suite created a fresh public export and confirmed that the dashboard and
its tests ship with the documentation that names them.

## Repository gates after implementation commit `736c240`

```
$ .venv/bin/python automation/gates/run_gates.py --lane policy,maintenance,publish --jobs 4
running 21 gates (lane: policy,maintenance,publish, jobs: 4)
...
tests-workspace            0  PASS     1.2s  local/gates/tests-workspace.log
tests-publish-export       0  PASS    11.0s  local/gates/tests-publish-export.log
leak-guard-tree            0  PASS     1.6s  local/gates/leak-guard-tree.log

ALL GREEN (21 gates)
```

## Live public + private check, launched outside the repository

```
$ cd /private/tmp
$ <REPO_ROOT>/automation/workspace/status.py -v --no-color
GIT WORKSPACE  2 repositories · 2 worktrees · 0 dirty · 3 local + 2 cached remote branches
Remote state is cached; no fetch was performed.
...
PUBLIC · jobs-finder-toolkit
  1 worktree · 0 dirty · 2 local + 1 cached remote branches
...
PRIVATE · private
  1 worktree · 0 dirty · 1 local + 1 cached remote branches
```

The absolute repository prefix is redacted above; the command was run from
`/private/tmp` and exited 0. No skill instruction files changed, so the
risk-based skill canary gate does not apply.

## Required agent preflight follow-up

```
$ ./automation/workspace/status.py -v --no-color
GIT WORKSPACE  2 repositories · 2 worktrees · 1 dirty · 3 local + 2 cached remote branches
...
PUBLIC · jobs-finder-toolkit
  1 worktree · 1 dirty · 2 local + 1 cached remote branches
...
PRIVATE · private
  1 worktree · 0 dirty · 1 local + 1 cached remote branches
```

The command exited 0 after the contract edit and exposed both repository states
in the first view. `automation/metrics/instruction_budget.py --strict` also
exited 0 after the root instruction grew from 293 to 300 lines.

## One-line default follow-up — 2026-08-26

The normal command now emits exactly one line and hides cached remote-only refs:

```text
$ ./automation/workspace/status.py --no-color
ACTION: public main diverged: 3 local-only commits, 2 remote-only commits · 1 of 2 worktrees dirty · 1 local work branch
```

That live line was captured while this repair branch was checked out and dirty;
the worktree and branch counts therefore prove the summary reacts to in-progress
work. `-v` still rendered the complete two-worktree, local/cached-remote branch,
file, commit, and remote inventory.

The full workspace suite covers the new one-line `ACTION` and `OK` states,
cached-remote omission, pluralization, private-overlay redaction in the new
output mode, and every existing detailed-inventory and cleanup behavior:

```text
$ .venv/bin/python -m unittest discover automation/workspace/tests -v
Ran 206 tests in 103.542s
OK
```
