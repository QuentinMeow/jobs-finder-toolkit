# Workspace phase 7c — durable vs disposable in the application timeline

- **Priority**: P2 (someday) — after [7b](../../3_in-review/2026-07-31-workspace-phase-7b-company-key-on-meta/task.md)
- **Area**: email
- **Source**: [workspace phase 7](../../4_done/2026-07-28-workspace-phase-7-company-key/task.md) · [design](../../../docs/designs/workspace-restructure/README.md)
- **Claimed-by**:

## Goal

Stop the durable half of an application's narrative from being rewritten away every time the email
assistant runs: mark each entry durable or disposable at write time, and give the owner a command
that promotes the durable ones into `companies/<key>/`.

## Context

The design's third requirement: a single real sentence in a recruiter email routinely carries both
lifetimes — the interview *format* is permanent, the *date* dies with the application, and they
arrive in one sentence. The assistant rewrites these files every run, so the split has to be made
at write time or it degrades continuously.

### What phase 7 found, which changes how this should be built

**No Python writes `notes.md`.** Every one of the four public references reads it. The file is
produced entirely by the model following prose in `skills/email-assistant/SKILL.md`. So this is
**greenfield**, not an edit to an existing writer:

- the `durable:` flag is a new bullet in the SKILL's entry template plus a rule in its rules block;
- enforcing it needs a **new** parser. The reusable pattern is `status.py`'s existing parse of
  `## Email Timeline` / `### <heading>` (first = newest) / `- **Summary:**` /
  `- **Outcome / next step:**` — a `- **Durable:** true` line matches that shape verbatim.

**The split already exists structurally, unlabelled.** All 126 files carry exactly three sections:
`## Upcoming Events & To-Dos` (disposable — rewritten each run, "None currently." when empty),
`## People` and `## Email Timeline` (durable — dated, append-only). So the flag is formalising an
existing convention, not inventing one.

**The real prize is 18 files**, not 126. Those carry hand-written non-template sections — take-home
writeups, screen notes, debugging transcripts — sitting inside an application folder when they
belong to the employer. Two are large enough that losing them would matter. The other 108 are
template-only and have nothing worth promoting. **Scope the value by those 18, not by the 126.**

**Counts, re-measured 2026-07-30**: 126 `notes.md` under the applications root (the plan's 135
counted 9 fixtures under `private/evals/`). None in `2_ignored` or `6_drafted`; all of
`3_rejected` and `4_in_progress`; 72 of 88 in `5_applied`. Notes exist exactly where email
evidence exists. Minimum file is 17 lines, so any ">N lines" triage test is useless.

### Why this was split out of phase 7

Its first consumer is a command that **moves files**, and it would have run on the least-verified
data in the repo — the 44%-hand-judged key assignment — in the same change that created it. The
two are now sequenced instead.

### Guardrails

- **Agents never delete owner data.** `promote` moves content out of a file the owner wrote. Treat
  it as owner-invoked and reversible: write the destination first, and never remove the source in
  the same step without the owner's explicit go-ahead.
- The rename `notes.md` → `timeline.md` has to move with its readers, `status.py:590,695` and
  `application_context.py:56`. Whether `timeline.md` is even the right name is an open question in
  the phase-7 design — resolve it before renaming 126 files.
- Editing `skills/email-assistant/SKILL.md` is a **behavioural** change to an instruction file, so
  the risk-based eval gate requires that skill's canaries to run and be recorded.
- **Email stays draft-only.** Nothing here may add a send path.

## Definition of done

- [ ] The SKILL's entry template emits a durable/disposable marker, with a rule saying how to judge
- [ ] A parser reads it, with a test per shape, including an entry that carries both lifetimes
- [ ] `promote` moves a flagged entry into `companies/<key>/` and is safe to re-run
- [ ] The 18 files with hand-written sections are the ones the change is measured against
- [ ] The `timeline.md` naming question is resolved before any rename
- [ ] email-assistant canaries run and recorded per `evals/README.md`
