# Worklog — 2026-08-02-pin-the-never-delete-an-application-folder-premise

## 2026-08-02 — session 1 (agent)

- Re-verified the premise before pinning it, rather than trusting the 2026-08-02 hand sweep:
  every `rmtree`/`unlink`/`remove`/`rmdir` in a non-test module under `automation/` and
  `skills/` targets the postings cache, store debris, an export destination, a generated
  symlink, or the reconciler's queue file. The premise holds. The only path-mutating call
  inside the applications tree is `status.py:_move_application`'s `shutil.move` between two
  status folders — a status transition, both endpoints inside the root.
- Guard is `automation/shared/tests/test_application_folder_never_deleted.py`, put where the
  repo's other cross-cutting policy tests live (`test_email_git_policy.py`,
  `test_canonical_module_resolution.py`); CI already runs
  `unittest discover automation/shared/tests`, and `run_gates` picks it up as `tests-shared`,
  so no wiring was added.
- **First cut was flow-insensitive and wrong.** A module-wide name set reported
  `search_jobs.py:1157 path.unlink()` as a violation, because `path` is bound to an
  applications-root path in one function and to a cache file in another. Rewrote the taint
  pass to be scope-aware. A guard that cries wolf earns an exception list, and an exception
  list is where guards go to die — so the fix was precision, not an exemption.
- Added a name backstop for the shape the taint pass structurally cannot see: an application
  folder arriving as a function parameter, with no assignment to trace.
- The guard's own teeth are tested in-file (four plants it must catch, two legitimate
  removals it must ignore), plus a coverage assertion so a scan that silently stopped
  matching anything cannot pass as green.
- Sequencing (task DoD item 3) held: the sibling task's message was fixed first, in this same
  branch, so the guard is never merged over a live instruction telling an agent to do the
  thing the guard exists to make impossible.
