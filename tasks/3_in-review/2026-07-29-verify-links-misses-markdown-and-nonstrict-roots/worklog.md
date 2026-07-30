# Worklog — 2026-07-29-verify-links-misses-markdown-and-nonstrict-roots

## 2026-07-29 — session 1 (agent)

- Designed before implementing. The design pass re-derived every number in the task
  file and **six of its supporting claims were wrong**, two of them in ways that would
  have produced a checker that looks principled and fixes nothing.
- The count is **23**, not 31–36, and two independent measurements agree row for row.
  The "no two checkers agree" finding was really one omission: a CommonMark code span
  may contain a newline, and every checker that masked line-at-a-time reported the two
  wrapped spans in `docs/handbook/doc-style.md` as broken. Fenced blocks — which the
  task named as the obvious culprit — contribute zero.
- **All 23 are in dated records.** Nothing in a document asserting current state was
  broken. That inverted the deliverable: not a repair campaign, a gate that is green
  today and stays green.
- Found what the task and the phase-5 plan both missed: `_instruction_files()` runs
  `git ls-files` in the **public** repo, so no file inside the overlay was ever opened.
  `SKIP_PREFIXES` filters tokens named in public docs, not which files are read — so
  phase 5's plan to prove its interview-link repair by editing that constant could not
  have worked. Overlay enumeration is in scope now and is what makes phase 5 verifiable.
- Wired the routine into CI and pre-commit. It previously ran in neither; only its unit
  tests did. A correct checker nothing executes has no teeth.
- `--require-roots` found a defect in this very change on its first run: a prefix added
  for a directory phase 5 has not created yet.
- Next: the suite (delegated), then the stack.
