# resume-writer's docs misstate what `check.py` enforces, in both directions

- **Priority**: P1 (this round)
- **Area**: resume-writer
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**: agent session 2026-08-02 (`docs/resume-writer-gate-truth`)

## Goal

Every threshold and gate the resume-writer docs state is the one `check.py` actually applies, so an
agent that writes to the documented numbers passes on the first render and does not report a folder
as validated when it holds no cover letter.

## Context

Four items, verified against `skills/resume-writer/scripts/check.py` on this branch.

1. **Direct-bullet range is not the whole rule.** `skills/resume-writer/SKILL.md:226` — "Use 1-6
   direct role bullets and 1-4 bullets per named project." That quotes `DIRECT_BULLETS_RANGE`
   (`check.py:102`) but omits `check_structure`'s harder constraint at `check.py:505-511`:

   ```python
   if base_direct and not direct:
       c.fail(f"{label} dropped all direct role bullets from the approved baseline")
   if len(direct) > len(base_direct):
       c.fail(f"{label} added direct role bullets: {len(direct)} vs baseline {len(base_direct)}")
   ```

   The real ceiling is the BASELINE's own count. With the shipped
   `examples/me/baseline.example.yaml` (projects only, zero direct bullets), adding any direct
   bullet — the obvious move on a SPARSE page — hard-FAILs the render. `check.py --rules` states the
   real rule; `SKILL.md` reads as a grant of a range.

2. **The cover-letter template's minimums are below the body floor.**
   `skills/resume-writer/reference.md:279` asks for a first main paragraph of 70-140 words and
   `:285` a second of 80-150, but `check.py:148` is
   `COVER_TOTAL_WORD_RANGE = (200, 450)`. Both paragraphs at their documented minimums total 150;
   even with the optional 25-45-word closing that is 175-195, under the 200-word FAIL floor. A
   letter that satisfies every per-paragraph rule in the template fails the render. (`SKILL.md:359`
   has the same arithmetic hole but prints the total alongside; `reference.md` is the file that
   hands the agent concrete targets to write to.)

3. **A missing cover letter is a WARN, not the FAIL the docs imply.**
   `skills/resume-writer/reference.md:236-237` — "`render.py`/`check.py` validate a cover letter for
   every role" — vs `check.py:613-616`, where a missing per-role bundle calls `c.warn(...)`, so a
   render with zero cover letters exits 0 and prints `✓ all checks passed (N warning(s))`.
   `AGENTS.md:214-216` makes "One cover letter per JD" a hard guardrail, so an agent trusting the
   doc reports a folder as validated with no letters in it. Either the doc drops the word "validate"
   or the check is promoted to a FAIL — a behaviour change, hence a task rather than an edit.

4. **A `check.py` warning names a filename the pipeline ignores.** `check.py:417` — `c.warn(f"Weak/
   Selective skill {tok!r} used but no JD file (jd.md / JD-*.md) …")` — vs
   `skills/resume-writer/SKILL.md:136` and `docs/handbook/application-folders.md:108`, which forbid a
   bare `jd.md`, and `layout.find_jd_files`, which only matches `jd-` prefixed names. An agent
   debugging that warning creates the one file nothing reads. This one is in code, so it needs a
   `skills/resume-writer/scripts/` change, not a doc edit.

Also seen, lower value and grouped here so they are not re-found: `reference.md:543` says "the most
JD-relevant bullet per project (reorder within the 2-3 without rewriting)" while
`BULLETS_PER_PROJECT = (1, 4)` (`check.py:103`) and the same file at `:180-183` explicitly sanctions
light rephrasing; and `SKILL.md:302-347` puts the cover-letter/bundle authoring section AFTER Step 6
("Render + Validate"), so an agent following the numbered steps in order renders before any bundle
exists and burns one of its 1-2 permitted render cycles — the ordering is stated correctly at
`:347`, just too late to help.

Items 1-3 and the two extras are `SKILL.md`/`reference.md` edits: behavioral, so
`evals/canaries/resume-writer.yaml` must run and be recorded per `evals/README.md` before merge.

## Definition of done

- [x] `SKILL.md`'s direct-bullet line states the baseline cap, not only `DIRECT_BULLETS_RANGE`.
- [x] `reference.md`'s per-paragraph word targets cannot sum below `COVER_TOTAL_WORD_RANGE[0]`.
- [x] The missing-bundle case is described exactly as the code treats it, or the code is promoted to
      FAIL and both surfaces say so. — took the FIRST branch: the docs (and `check.py --rules`)
      now state the WARN as a limitation. The promotion is an owner decision, filed at
      `message-queue/needs-human/decisions/missing-cover-letter-warn-or-fail.md`.
- [x] `check.py:417`'s message names only `JD-*.md`.
- [x] resume-writer canaries run and recorded per `evals/README.md`; `render.py` + `check.py` green
      on `examples/applications/6_drafted/example-corp-senior-software-engineer/`. — render/check
      green (see `verification.md`). Canaries **skipped with a recorded rationale**, which is what
      the risk-based rule in `evals/README.md` allows for this edit shape: every change is
      "correcting … labels to match code reality", 2 instruction files, 21 added / 10 removed
      lines (5 of them numeric substitutions). Debt
      accumulates onto `tasks/0_backlog/2026-07-31-resume-writer-canary-run-for-gate-honesty`,
      which is annotated to cover it.

Split out, not done here: the Step-6 ordering item from the "Also seen" paragraph is now
`tasks/0_backlog/2026-08-02-cover-letter-section-sits-after-the-render-step`. It is a restructure,
which is a MUST-run under the eval gate, so it does not belong in a skip-discharged change.
