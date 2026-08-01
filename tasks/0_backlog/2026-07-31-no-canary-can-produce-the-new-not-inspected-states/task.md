# No canary in the resume-writer set can produce either new NOT INSPECTED state

- **Priority**: P2 (someday)
- **Area**: benchmarks
- **Source**: judging the resume-writer canary subset, 2026-07-31 — the judge's verdict on
  whether the run was adequate evidence
- **Claimed-by**:

## Goal

Give the two new render-gate failure states real behavioural coverage, or record a decision
that their unit tests are the accepted coverage — so the eval gate stops being asked a
question it structurally cannot answer.

## Context

A change added two FAIL states to the render gate: `PDF NOT INSPECTED` (the PDF gates did
not run) and `SKILL VOCABULARY NOT INSPECTED` (the profile's `## Skills` section did not
parse). Eight SKILL.md lines document them, including guidance that deliberately cuts
against Step 7.

Four of the eight `resume-writer` canaries were run against that change and all four passed.
The judge's finding is the useful part: **running the other four would have added nothing**,
because *no canary in the set, all eight included, can put the tool into either state.* Every
canary uses a healthy fixture with a well-formed profile and a working converter, so the
happy path is well covered and the new failure paths are covered only by unit tests.

That is a gap in the canary set, not in the run scope. It matters because the instruction
half of the change — what an agent is told to do when it meets one of these states — has
never been exercised by an agent.

Two candidate canaries, both cheap:

- Hide the converter (`JOBHUNT_SOFFICE` pointed at a nonexistent path) and assert the agent
  reports the PDF gates as not run rather than reporting success.
- Supply a profile whose `## Skills` section cannot be parsed and assert the agent stops
  rather than proceeding against an empty vocabulary — the exact silent-empty-blocklist bug
  the parser unification fixed.

The second is the more valuable of the two: an empty Never list means the gate that exists to
keep blocklisted skills off a resume passes everything, and it does so quietly.

## Definition of done

- [ ] Either two new entries in `evals/canaries/resume-writer.yaml` covering the two states,
      with rubrics written the way the existing entries are
- [ ] Or a recorded decision (PR body or `memory/decisions/`) that the shipped unit tests are
      the accepted coverage for these states, with the reason
- [ ] If canaries are added, one run recorded per `evals/README.md`
- [ ] `rw-tailor-single-posting`'s bullet 5 reviewed while here: its Step 7 format clause is
      unexercisable on that fixture (the queue is legitimately empty), so it has never been
      evaluated in any run. Either give it a fixture that triggers the queue or drop the
      clause and let `rw-skill-category-question-batch` own it.
