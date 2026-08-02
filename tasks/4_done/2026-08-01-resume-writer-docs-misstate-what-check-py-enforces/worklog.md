# Worklog — 2026-08-01-resume-writer-docs-misstate-what-check-py-enforces

## 2026-08-02 — session 1 (agent, branch `docs/resume-writer-gate-truth`)

- Re-verified all four items against the code before writing anything; every one reproduced.
  Evidence in `verification.md`.
- Default taken: **correct the docs to the gate**, not the gate to the docs. The one code change
  that carries no behaviour is item 4's dead `jd.md` literal in a warning string.
- Item 1 — `SKILL.md`'s "use 1-6 direct role bullets" now says the baseline's own count is the
  ceiling and that the shipped example baseline permits zero.
- Item 2 — decided from the code that the **200-word body floor is the right side**: it is the
  constant `check_cover_letter` actually tests, and the caller was told not to change it. So
  `reference.md`'s per-paragraph minimums were wrong: 70-140 → 100-140 and 80-150 → 110-150, giving
  a 210-word floor from the two mains alone (the closing is optional, so it can never be counted
  on). Verified both directions: 175 words FAILs, 210 passes.
- Item 3 — described, not changed. The WARN is deliberate (`check_cover_letter`'s docstring keeps
  resume-only drafts valid), and promoting it would turn existing letterless folders red, so it
  went to `message-queue/needs-human/decisions/missing-cover-letter-warn-or-fail.md` with
  "leave it a WARN" as the default path. Added the case to `check.py --rules`' warn-only line too,
  since `SKILL.md` tells agents to read that dump instead of the source.
- Item 4 — proved the literal is dead (`find_jd_files` keeps only `jd-`-prefixed names) before
  editing the string.
- Eval gate: skipped, rationale recorded in the PR body and in the Definition of done. Noted the
  accumulation on `2026-07-31-resume-writer-canary-run-for-gate-honesty`.
- Left open and re-filed: the Step-6 ordering item →
  `tasks/0_backlog/2026-08-02-cover-letter-section-sits-after-the-render-step`.
