# Workspace phase 7c — durable vs disposable in the application timeline

- **Priority**: P2 (someday) — after [7b](../../3_in-review/2026-07-31-workspace-phase-7b-company-key-on-meta/task.md)
- **Area**: email
- **Source**: [workspace phase 7](../../4_done/2026-07-28-workspace-phase-7-company-key/task.md) · [design](../../../docs/designs/workspace-restructure/README.md)
- **Claimed-by**:

## Goal

Stop the durable half of an application's narrative from being rewritten away every time the email
assistant runs: mark each entry durable or disposable at write time, and give the owner a command
that promotes the durable ones into `companies/<key>/`.

> ## STOP — descope proposed 2026-07-31; do not start this as written
>
> A read-only reconnaissance pass re-measured every claim below and found the phase's premise
> **false**. The recommendation is now in front of the owner as
> [`message-queue/needs-human/decisions/phase-7c-descope-to-the-one-live-defect.md`](../../../message-queue/needs-human/decisions/phase-7c-descope-to-the-one-live-defect.md).
> **Default path while that is unanswered: build nothing here and rename nothing.**
>
> The four findings, each re-verified 2026-07-31 against the mounted overlay:
>
> 1. **The degradation this phase prevents has never happened.** Every commit that has ever
>    touched one of these files is net-additive — **+5,434 / −709 across 16 commits, no exceptions**
>    — and the SKILL text says *"Preserve existing interview preparation, technical exercises, and
>    other hand-written content"* and *"updates an existing entry instead of appending"*. The
>    "assistant rewrites these files wholesale" premise is contradicted by the instruction and by
>    100% of the history.
> 2. **The proposed flag is on the wrong syntactic object.** All 18 files with hand-written
>    sections put every extra heading *after* `## Email Timeline`, as a **sibling section** — never
>    as a timeline entry. A per-entry `durable:` marker cannot reach them. The value is also far
>    more concentrated than "18 files" implies: two files hold **736 of 817 hand-written lines
>    (90%)**, and 14 of the 18 are 3–4-line outcome stubs restating a status already in `meta.yaml`.
> 3. **`promote`'s destinations exist nowhere.** `loop.md`, `people.yaml`, `company.yaml` and
>    `decision.md` appear in the design README's tree diagram, in **no phase of the execution plan**
>    and in **zero of the 25 company folders on disk**. Also, `AGENTS.md` forbids what this task
>    calls it: a command that *moves* content out of a file the owner wrote is an agent removing
>    owner data. The safe verb is copy-then-report.
> 4. **Doing the rename half first fails *silently*.** The calendar link builder falls back to
>    `meta.yaml` when the narrative file is absent and the note reader returns `None` on `OSError`,
>    so a rename ahead of its readers raises nothing — and the next
>    `status.py --refresh-calendar --write` **rewrites all 109 owner-visible calendar links to
>    point at `meta.yaml`** and drops the latest-update lines. The link checker catches it only if
>    run *before* that refresh, because the refresh replaces broken links with wrong-but-resolvable
>    ones and turns the gate green again.
>
> **What survives, and it is worth doing on its own:** `skills/email-assistant/SKILL.md` and
> `skills/application-tracker/SKILL.md` specify **two incompatible templates for the same file** —
> `## Upcoming Events & To-Dos` / `## People` / `## Email Timeline` versus `## Company Research` /
> `## <Round> (<date>)`. Whichever skill runs last wins. That is a live defect today, independent
> of this phase, and it is also why any parser built here would be unreliable: keyed on
> `## Email Timeline`, it returns an empty list on a file written to the other template instead of
> failing loudly.

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
- The rename `notes.md` → `timeline.md` has to move with its readers, ~~`status.py:590,695`~~ and
  `application_context.py:56`. Whether `timeline.md` is even the right name is an open question in
  the phase-7 design — resolve it before renaming 126 files.
  **Corrected 2026-07-31: those two line numbers are wrong and were wrong when written.** There
  are **three** reader sites in `status.py`, not two, and none of them is at 590 or 695 (590 is
  now inside `check_locations`, 695 inside meta validation). Find them with
  `grep -n 'notes.md' skills/application-tracker/scripts/status.py` — that command does not rot;
  the numbers did. Five further byte-identical copies of a doc comment naming the file live in
  `automation/shared/layout.py` and its four vendored copies and must move together.
- Editing `skills/email-assistant/SKILL.md` is a **behavioural** change to an instruction file, so
  the risk-based eval gate requires that skill's canaries to run and be recorded.
- **Email stays draft-only.** Nothing here may add a send path.

## Definition of done

**Descoped 2026-07-31, pending the owner's answer.** The list below is what this phase *would*
finish if the machinery is built; it is kept because the design work behind it is real and
should not be re-derived if the answer is "build it". **Until that answer arrives, the only item
an agent may act on is the first one in the second list.**

### If the descope is accepted (the default path)

- [ ] `skills/email-assistant/SKILL.md` and `skills/application-tracker/SKILL.md` stop specifying
      two incompatible templates for the same file — one of them wins, or they are explicitly
      split into two files. Behavioural instruction edit ⇒ both skills' canaries run and are
      recorded per [`evals/README.md`](../../../evals/README.md)
- [ ] One sentence added beside the email-assistant SKILL's existing preservation rule: a section
      the model did not write is owner content — never edit, reorder or summarise it
- [ ] **Owner-only, never an agent:** decide whether the two large hand-written writeups move to a
      company folder and under what filename. No default; none of the four filenames the design
      names exists anywhere on disk

### If the owner asks for the machinery anyway

- [ ] The SKILL's entry template emits a durable/disposable marker, with a rule saying how to judge
      — and the marker names a **target**, not a boolean, because the design already names five
      destinations and a boolean says "move this" without saying where
- [ ] A parser reads it, with a test per shape, including an entry that carries both lifetimes and
      **a file written to the application-tracker template, which must raise rather than return
      an empty list**
- [ ] `promote` **copies** a flagged entry into `companies/<key>/` and is safe to re-run
      (fingerprint-idempotent, dry-run by default). It never edits the source, and it never
      removes it — `AGENTS.md`: application folders are removed by the user only
- [ ] The 18 files with hand-written sections are the ones the change is measured against — noting
      that two of them hold 90% of the content and the other 16 hold 3–4 lines each
- [ ] The `timeline.md` naming question is resolved by the **owner** before any rename, and the
      rename is ordered readers-accept-both-names → rename → drop the fallback, because the
      reverse order fails silently
- [ ] email-assistant canaries run and recorded per `evals/README.md`
