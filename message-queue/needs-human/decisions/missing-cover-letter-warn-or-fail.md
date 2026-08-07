# Should a role with no cover-letter bundle FAIL `check.py` instead of only warning?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-02
- **Source**: [resume-writer docs-vs-gate task](../../../tasks/4_done/2026-08-01-resume-writer-docs-misstate-what-check-py-enforces/task.md)
- **Blocks**: nothing. The docs now describe the WARN accurately, so no agent is misled while
  this is pending.
- **Default path**: leave it a WARN; the docs now say so. `check.py` keeps calling `c.warn()` for
  a role whose bundled `..._Application_<role>.txt` is missing, and `SKILL.md` / `reference.md` /
  `check.py --rules` all state plainly that a render producing zero cover letters still exits 0.
- **Cost if wrong**: ratify
- **Safe to merge because**: nothing changed in the gate — `check.py:613-616` is byte-identical to
  what shipped before this task. Only the prose around it moved. Reverting the decision later is a
  three-line code change (`c.warn` → `c.fail` plus a flag), and no owner data, application folder,
  or log row is touched either way.

## Background

`AGENTS.md` makes "one cover letter per JD" a hard guardrail. `skills/resume-writer/scripts/check.py`
does not enforce it. `check_cover_letter` validates the letter of every role whose bundle exists —
salutation, sign-off, ≥2 paragraphs of 60-180 words, a 200-450-word body, no placeholders — but a
role with **no bundle at all** only warns:

```python
body = cover_letter_text(app_dir, label)
if body is None:
    c.warn(f"no bundled {application_stem(label)}.txt (COVER LETTER section) found"
           f"{where} — every JD needs its own cover letter")
    return
```

Measured on a copy of the shipped example folder with its bundle deleted:

```
  WARN: no bundled Jordan_Rivers_Software_Engineer_Application_Senior_Software_Engineer_Platform.txt
        (COVER LETTER section) found for 'Senior Software Engineer, Platform' — every JD needs its own cover letter
  ✓ all checks passed (1 warning(s))
EXIT=0
```

So a folder holding zero cover letters prints a success line. An agent that reports validation from
the exit code calls that folder done.

The warn is deliberate, not an oversight: `check_cover_letter`'s docstring says "A missing letter is
only a warning so resume-only drafts still validate", and the skill supports a resume-only run
(`render.py --no-cover-letter`, and "Skip cover letters only when the user explicitly asks"). A
blanket FAIL would turn every deliberate resume-only draft red.

This task corrected the documentation to match the code. Changing the code is a behaviour change to
a hard gate, which is why it is a decision rather than an edit.

**What is unknown:** how many of your existing application folders would go red. The private overlay
is not mounted in the checkout that filed this, and agents do not read your real application folders
to answer a process question. The one public folder
(`examples/me/applications/6_drafted/example-corp-senior-software-engineer/`) has its bundle and would
stay green under every option below.

## Options

### Option A — leave it a WARN (the default path)

Nothing changes in code. The docs, updated by this task, carry the caveat: `SKILL.md` tells the agent
to count rendered letters against the `meta.yaml` roles rather than trust the exit code,
`reference.md` names it a known limitation, and `check.py --rules` lists it under "warn-only".

- Pros: zero risk to existing folders; resume-only drafts keep working; already shipped.
- Cons: the enforcement of a hard `AGENTS.md` guardrail stays in prose, where an agent that skips
  the warning lines can still miss it. Prose is weaker than a gate.
- Cost: none.

### Option B — promote to a FAIL, unconditionally

`c.warn(...)` → `c.fail(...)`. Every role in `meta.yaml` must have its bundle before `check.py`
passes.

- Pros: the guardrail becomes a gate; no letterless folder can ever report as validated.
- Cons: breaks the deliberate resume-only draft — a real, documented workflow with no escape hatch.
  Any existing folder missing a bundle goes red on its next validate, including ones you already
  submitted and no longer care about.
- Cost: one repair pass over whatever folders are currently letterless.

### Option C — FAIL by default, with a declared opt-out flag

Add `--no-cover-letter` to `check.py` (and pass it through from `render.py --no-cover-letter`),
mirroring exactly how `--no-pdf` already works: without the flag, a missing bundle FAILs; with it,
the run reports the omission and warns. `check.py` already carries this pattern for the PDF gates —
"a PDF that is absent or unreadable is NOT a skip … unless `--no-pdf` declared a DOCX-only draft".

- Pros: the guardrail is enforced by default and the resume-only workflow survives; consistent with
  the gate design already in the file, so nothing new to learn.
- Cons: the largest change of the three — a new flag on two scripts, the pass-through, and tests.
  Existing letterless folders still go red until they are either given letters or validated with
  the flag.
- Cost: one implementation task plus the same repair pass as Option B.

## Recommendation

**Option C**, as a follow-up task — but only after you say how many of your folders are currently
letterless, because that number is the whole cost of the change and this checkout cannot see it.
Option C is the shape the file already uses for the PDF gates, so it enforces the `AGENTS.md`
guardrail without deleting the resume-only path that Option B would break. Option A is a safe place
to sit meanwhile: the failure mode is now written down in all three places an agent reads, so the
loss is no longer silent, just unenforced.

**Your answer:** ______
