# `github-workflow/SKILL.md` sits at exactly 600 of 600 lines

- **Priority**: P2 (someday) — nothing is broken; the next edit to this file is
- **Area**: harness
- **Source**: the stack merge that brought the local gate runner and the two-track merge
  runbook into one branch, 2026-08-02
- **Claimed-by**:

## Goal

Give `skills/github-workflow/SKILL.md` real headroom by consolidating it, so the next
person to add a line does not have to choose between breaking a gate and deleting a
domain edge case.

## Context

Two branches independently added a section to this file: the gate runner's "Running the
gates locally" (17 lines) and the two-track merge correction (+72 lines). Merged, they
put the file at 607 against the 600-line budget in
`automation/metrics/instruction_budget.py`, and `--strict` failed.

That was resolved the right way — the gate-runner section was compressed to seven lines
and its detail moved into `skills/github-workflow/reference.md`, which has no budget —
but the result is **600 of 600, zero headroom**. The budget report already says the
quiet part: *"Plan the next substantive edit to this file as a consolidation pass, not
an addition."*

`AGENTS.md` forbids the tempting shortcut: harness self-edits are delta-only, and
**consolidation never deletes a domain edge case**. So this is a real editing job, not a
trim. The material most likely to move is anything that is reference rather than routine
— `reference.md` exists now and is the destination.

Two other files in the tree are in the same position and could be done in one pass:
`skills/application-tracker/SKILL.md` (542/600) and `skills/company-research/SKILL.md`
(568/600) are both flagged NEAR.

## Definition of done

- [ ] `.venv/bin/python automation/metrics/instruction_budget.py --strict` reports
      `github-workflow/SKILL.md` under 90% of budget (≤ 539 lines), so it stops being
      flagged NEAR.
- [ ] Every line removed from `SKILL.md` is either genuinely redundant or present in
      `reference.md` — diff the two and show that no edge case was dropped.
- [ ] The `github-workflow` canary set passes, since this is a behavioral-surface edit
      to a skill that has one.
