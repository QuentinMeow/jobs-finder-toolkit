# The layout estimator says OVERFLOW on the example that renders as one page

- **Priority**: P1 (this round)
- **Area**: resume-writer
- **Source**: 2026-08-02 session fixing commands that fail on a healthy repo — measured, not
  fixed, because the fix is a judgement call and another branch is editing this skill
- **Claimed-by**:

## Goal

Close the gap between what `estimate_layout.py` tells an agent and what the renderer actually
does, so an agent following the documented protocol stops trimming real content off a resume
that already fits on one page.

## Context

Measured on the repo's own shipped example, at `main` (`f360aec`), with the tracked example
config:

```bash
JOBHUNT_CONFIG=config.example.yaml .venv/bin/python \
  skills/resume-writer/scripts/estimate_layout.py \
  examples/me/applications/6_drafted/example-corp-senior-software-engineer/
# EXIT=1
#   TOTAL est 739pt / 734pt budget (44 content lines)
#   OVERFLOW: predicted 2 pages (est 739pt > 734pt budget). Cut ~2 bullet lines …

JOBHUNT_CONFIG=config.example.yaml .venv/bin/python \
  skills/resume-writer/scripts/check.py \
  examples/me/applications/6_drafted/example-corp-senior-software-engineer/
# EXIT=0
#   ✓ all checks passed (0 warning(s))
```

The shipped PDF is exactly one page, and `check.py` — the authoritative gate, which enforces
"exactly one page" — passes it with zero warnings. The estimate is 0.7% over a 734.4pt budget.

Two of the three surfaces already know this:

- `skills/resume-writer/LESSONS.md` (Pre-render layout budget) states it outright: "the
  shipped example estimates ~739pt yet renders exactly 1 page, so the gate fires only beyond
  the noise band".
- `skills/resume-writer/scripts/render.py` implements that band — it aborts only when the
  estimate is over budget by more than one rendered line of word-wrap noise
  (`pitch_body + BULLET_AFTER_PT`, ~±12pt), so a borderline OVERFLOW still renders.

The two that do not:

1. **`skills/resume-writer/SKILL.md`'s verdict protocol** (the "Verdict protocol (calibrated
   bands…)" bullet list, ~line 285) has NO noise band. It says: `OVERFLOW > 734 — will be 2
   pages; shorten the longest bullets/summary before rendering`, and the next bullet tells the
   agent to simulate the trim and confirm it lands under budget. An agent that follows this
   protocol on the canonical example deletes real, traceable content from a resume that fits —
   which collides with the tailoring guardrails, since the content it removes is the content
   the profile supports.
2. **`estimate_layout.py`'s own exit code** is 1 on that same borderline case, so any caller
   reading the exit code (an agent, a script, a future gate) gets "failed" where `render.py`
   deliberately reads "proceed".

## Why this is judgement, not a mechanical repair

There is more than one defensible fix and they are not equivalent:

- teach `SKILL.md`'s protocol the same ±1-line band `render.py` and `LESSONS.md` already use
  (a BORDERLINE verdict between 734 and 734+noise), and/or
- give `estimate_layout.py` a distinct exit code for borderline vs clear overflow so the CLI
  and the in-process gate agree, and/or
- re-calibrate the constants so the shipped example lands under budget — which risks moving
  the band for every real resume to make one example look tidy.

The choice changes agent behaviour on every tailoring run, so it wants a deliberate decision
and a canary run.

## Constraints for whoever picks this up

- **Not in the 2026-08-02 `fix/commands-that-fail-on-a-healthy-repo` branch.** Another branch
  is already editing this skill and depends on staying non-behavioural; this change is
  behavioural by definition.
- Editing `SKILL.md` / `LESSONS.md` here is a behavioural harness edit, so AGENTS.md's
  risk-based eval gate applies: run `evals/canaries/resume-writer.yaml` before merge and
  record the result.
- Do not resolve it by loosening `check.py`. `check.py`'s page count is the authoritative
  gate and it is currently RIGHT; the estimator is the surface that is wrong.

## Definition of done

- [ ] A single documented rule for the borderline zone, identical in `SKILL.md`'s verdict
      protocol, `LESSONS.md`, `render.py`'s gate and `estimate_layout.py`'s exit code.
- [ ] Following the documented protocol on
      `examples/me/applications/6_drafted/example-corp-senior-software-engineer/` no longer tells
      an agent to cut content — verified by re-running the two commands above and recording
      both exit codes in `verification.md`.
- [ ] `evals/canaries/resume-writer.yaml` run and recorded per `evals/README.md`.
