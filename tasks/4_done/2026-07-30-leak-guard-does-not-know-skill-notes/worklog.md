# Worklog — the leak guard did not know `skill-notes`

## 2026-07-31 — session 1 (agent)

- Confirmed the gap by planting `skills/<skill>/skill-notes/x.md` in a scratch git tree: the
  pre-fix rule passed it, the new rule fails it.
- Made `SKILL_NOTES_DIRNAMES` an append-only union of `references_private` and `skill-notes` in
  `check_public.py`, and taught `export_public._deny_reason()` both names.
- Added the "the denied names still name something real" test the task suggested — it ties the
  deny list to `config.skill_references_dir()`, so the next rename fails a test instead of
  silently disarming the guard.
- Also had to pin the negative case: this repo tracks a task folder whose name ends in
  `-skill-notes`, so segment-anchored matching is load-bearing.
- Next: none.
