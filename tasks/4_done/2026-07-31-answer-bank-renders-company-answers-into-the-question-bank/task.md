# `answer_bank.py --render` writes company answers into the question bank, not the company folder

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: doc-vs-code audit finding folded into `skills/behavioral-interview-prep/SKILL.md`
  (PR "the instruction surface matches the code"); pre-scoped as PR 7 of the phase-8 plan
- **Claimed-by**: records-match-the-tree pass, 2026-08-02 (retro-closure; see verification.md)

## Goal

`answer_bank.py --render` puts a company-prefixed answer where the tree actually keeps it —
`config.companies_root()/<key>/derived/<slug>.md` — instead of back in the question bank,
so the SKILL.md no longer has to carry a "move the file afterwards" caveat.

## Context

`skills/behavioral-interview-prep/scripts/answer_bank.py` resolves every output to
`source.parent.parent / f"{output['slug']}.md"` (`output_targets_for`, ~line 647), i.e. always
`question-bank/<slug>.md`, because the sources live in `question-bank/sources/`.

The lifetime taxonomy moved the company-prefixed answers out of that folder:
`memory/decisions/interview-material-moves-by-company-only.md` records "19 company-prefixed →
`companies/<key>/`", and the overlay's question bank now holds `_general_*` files only. So a
`--render` today recreates the 19 files in the wrong tree and silently stales the real ones.

The routing rule is mechanical: a `_general_*` slug keeps the question-bank target; any other
slug's pre-hyphen prefix is a company key that already matches an existing company folder.
The duplicate-output-owner check (~line 887) and its tests resolve the same paths and move with it.

This is a **behaviour change to a generator that writes into the owner's private tree**, so it
wants its own review and an owner OK before it lands. Agents never delete or overwrite owner
data: the fix must not touch the 19 real files, only where new renders land.

## Definition of done

- [ ] `output_targets_for` routes a company-prefixed slug to
      `config.companies_root()/<key>/derived/<slug>.md` and leaves `_general_*` in the question bank.
- [ ] The duplicate-owner check compares the same resolved targets; unit tests cover both branches
      and a cross-tree collision.
- [ ] `.venv/bin/python -m unittest discover -s skills/behavioral-interview-prep/scripts/tests`
      passes, and a dry `--render` against a fixture tree writes no file outside its target.
- [ ] The "Known gap" paragraph and the `§ File Location` caveat in
      `skills/behavioral-interview-prep/SKILL.md` are deleted in the same PR.
- [ ] Canaries for `behavioral-interview-prep` run and are recorded (`evals/README.md`) — this is
      a behavioural edit, and it also covers the path corrections that skipped ahead of it.
