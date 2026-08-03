# Verification — 2026-08-01-the-async-stop-condition-cannot-be-produced

Closed 2026-08-02 as **superseded**, not as implemented. The task's own
`## 2026-08-01 — superseded in place by PR #188` note records that; this file
verifies the premise is actually gone from the tree.

## The premise no longer exists anywhere

The task exists because `AGENTS.md` and `docs/handbook/collaboration-modes.md`
set the async stop condition as the literal sentinel `Blocking: yes`, which the
decision template could never produce. Re-run today over exactly the files the
task names:

```
$ grep -n "Blocking" AGENTS.md docs/handbook/collaboration-modes.md templates/queue/*.md
$ echo "EXIT=$?"
EXIT=1
```

Exit 1, no output: the word does not appear in the contract, the handbook page,
or any queue template. PR #188 renamed the field to `Blocks:` and moved stop
authority to the `AGENTS.md` Guardrails, which halt one action rather than a
batch — so the task's own DoD bullets 1-2 are moot rather than met.

DoD bullet 3 is **not literally satisfied, and that is fine**:

```
$ grep -rn 'Blocking: yes' AGENTS.md docs/ templates/ message-queue/; echo "EXIT=$?"
message-queue/needs-human/decisions/does-merge-then-answer-apply-to-the-private-overlay.md:30
message-queue/needs-human/decisions/process-weight-what-to-cut.md:261, :276, :278
message-queue/needs-human/decisions/blocks-rename-supersedes-the-stop-condition-task.md:20, :22, :41
EXIT=0
```

All seven hits are the retired rule being **quoted** inside decision items that
discuss its removal (one of them appends *"`Blocking: yes` no longer exists"*).
None is a live `- **Blocking**: yes` field. The bullet was written to catch a
sentinel nothing could produce; what survives is prose about that sentinel, which
is exactly what a superseded record should contain.

## DoD 4 — the reconciler is clean

```
$ .venv/bin/python automation/reconcile/reconcile.py --check; echo "EXIT=$?"
reconcile: OK (9 checks clean)
EXIT=0
```

## Where the trace lives, per `tasks/README.md`

`tasks/README.md` requires a superseded task to leave a one-line trace before it
is dropped. It has two: the in-place `## 2026-08-01 — superseded in place by
PR #188` section in `task.md` (untouched by this closure — no text above it was
changed), and the live owner question
`message-queue/needs-human/decisions/blocks-rename-supersedes-the-stop-condition-task.md`,
which can still reverse the supersession. If the owner answers Option B or C
there, this task's fix ships after all and the folder moves back — a `git mv`,
which is why closing it now is reversible.
