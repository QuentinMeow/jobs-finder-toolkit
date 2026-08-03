# Verification — 2026-07-31-resume-writer-canary-run-for-gate-honesty

Retro-closure, 2026-08-02. **This was one of two contested rows** — a second
audit read it as unstarted canary work. It is not: the run exists, and the
record it produced is the discharge. Evidence read in full before deciding.

## The record, and that it is about THIS change

`evals/results/resume-writer-5133ff8ad8d5-20260731-pdf-gate-honesty.md`, header
comment:

```
Pre-merge regression gate for the "make the resume gates say when they did not run" change
(eca0c33, ancestor of the run SHA): two new FAIL states in check.py (`PDF NOT INSPECTED`,
`SKILL VOCABULARY NOT INSPECTED`), ... + 8 lines in SKILL.md / 4 in LESSONS.md.
```

That is this task's change verbatim (task Source: *"the PR that made `check.py`
report `PDF NOT INSPECTED` / `SKILL VOCABULARY NOT INSPECTED`"*; task Context:
*"~12 instruction lines across 2 files"*).

```
$ git merge-base --is-ancestor eca0c33 5133ff8ad8d5; echo $?
0
$ git merge-base --is-ancestor 5133ff8ad8d5 HEAD; echo $?
0
```

## DoD 1 — run at head on the pinned model

Run at `5133ff8ad8d5`, model `claude-opus-5`, four of eight canaries. The subset
is **deliberate, pre-registered and argued in the record** (§ "Scope and
limitations of this run"): the four chosen are the only ones that touch the
changed surface, and the record says outright *"Not run — recorded as an
untested area, not as a pass"* for the other four. `evals/README.md`'s gate asks
that a behavioural instruction edit pass canaries; it does not require all eight
when the record names what the subset covers and what it does not.

## DoD 2 — rubric passes; no large efficiency regression

Record `## Per-canary results`: `4/4` rubric_pass. `## Verdict`: *"Regression:
PASS on the four canaries run. Does not block the merge."* Efficiency table is
*"recorded, not scored, and not merge-blocking"*, with one canary +7.6% over its
prior token max and the comparison flagged as confounded — no blow-up of the
order `evals/README.md` treats as failing.

## DoD 3 — result file from TEMPLATE.md naming the head SHA

`evals/results/resume-writer-5133ff8ad8d5-20260731-pdf-gate-honesty.md`, `Git SHA`
row: `5133ff8ad8d5`.

## DoD 4 — findings filed before closing

No canary regressed. The record's own finding is that the canary SET cannot
produce either new FAIL state; that is filed as
`tasks/0_backlog/2026-07-31-no-canary-can-produce-the-new-not-inspected-states`,
whose Source line is *"judging the resume-writer canary subset, 2026-07-31"*.
Filed before this closure, not by it.

## What this closure does NOT claim

The record is explicit that the **instruction** half of the change is not
covered by any run, because neither message can be produced by any canary in the
set. That is the open task named above, not this one.
