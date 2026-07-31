# Verification — the leak guard did not know `skill-notes`

Run from the repo root on branch `fix/03-owner-data-paths`. Absolute home paths are redacted to
`<repo-root>`; the scratch tree path is shortened to `<scratch>/plant`.

## Plant a file under the new name in a scratch tree, then run the guard

```
$ mkdir -p <scratch>/plant/skills/resume-writer/skill-notes
$ printf 'candidate-specific ordering rules\n' > <scratch>/plant/skills/resume-writer/skill-notes/ordering.md
$ git -C <scratch>/plant init -q . && git -C <scratch>/plant add -A
$ .venv/bin/python -c "<scan the planted tree with check_public.scan and print the report>"
Public-repo leak guard
  repo root:      <scratch>/plant
  tracked files:  1
  active tokens:  0 (caller-supplied)
  identity source:      real config (<repo-root>/config.yaml)

FAIL: 1 violation(s) found.

[3] Tracked files under a per-skill private-notes folder ('references_private/' / 'skill-notes/') (1):
  - skills/resume-writer/skill-notes/ordering.md

exit code would be: 1
```

## The same tree under the pre-fix rule

Re-running the identical scan with the module's matcher restored to the old
`(^|/)references_private(/|$)`:

```
PRE-FIX rule (references_private only) on the same planted tree -> ok: True | violations: 0
```

That is the whole defect: the rule AGENTS.md and `public-private-split.md` both state was
enforcing nothing at its stated purpose.

## Both names denied, and a similar name not denied

`automation/publish/tests/test_leak_guard.py::SkillNotesTests` now covers:

- `test_both_folder_names_are_flagged_by_guard` — plants
  `skills/job-search/references_private/notes.md` and `skills/job-search/skill-notes/notes.md`
  in turn; each fails the guard and is the only reported violation.
- `test_both_folder_names_are_pruned_by_exporter` — `export_public._deny_reason()` returns
  `skill-notes` for both.
- `test_a_similarly_named_file_is_not_flagged` — this repo tracks
  `tasks/…/2026-07-30-leak-guard-does-not-know-skill-notes/task.md`, whose last path segment
  merely ends in `-skill-notes`. Matching is per segment, so it is not hit; without this test the
  guard would fail on its own task file.
- `test_the_denied_names_still_name_something_real` — reads the leaf directory name from
  `config.skill_references_dir()` and asserts it is in `SKILL_NOTES_DIRNAMES`. This is the check
  the task asked to consider: the phase-5 rename would have failed here on the first commit
  after it, instead of being found by reading months later.

```
$ .venv/bin/python -m unittest discover automation/publish/tests
Ran 148 tests in 195.706s

OK
```

## The old name is kept, not replaced

`SKILL_NOTES_DIRNAMES` is an append-only union, the same discipline `_DENY_TREES` uses and
`test_deny_trees_are_append_only` pins: a stale checkout, an old branch or a restored backup can
still put `references_private/` in the public tree, and a detector that forgets the old name
fails open exactly when it matters.

## Documents updated

`AGENTS.md`, `docs/handbook/public-private-split.md` and `docs/handbook/private-overlay.md`
(two places) now state the rule by both names.

## Full gate

```
$ zsh <scratch>/gate.sh
ALL GREEN
```
