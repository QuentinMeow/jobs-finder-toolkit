# Workspace phase 7c: descope to the one live defect, or build the durable-marker machinery anyway?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [the phase-7c task](../../../tasks/0_backlog/2026-07-31-workspace-phase-7c-durable-timeline/task.md) · [the design's `companies/<key>/` tree](../../../docs/designs/workspace-restructure/README.md)
- **Blocks**: nothing today. It **would** block if anyone starts phase 7c: two of its four questions must be answered before a rename touches 126 of your files.
- **Default path**: **do not build the durable/disposable machinery, and do not rename anything.** Fix the one live defect (two skills specifying incompatible templates for the same file), and leave the rest until a real degradation is observed. The phase-7c task has been updated to say this.
- **Cost if wrong**: ratify
- **Safe to merge because**: nothing is renamed, so the files a rename would touch stay put and no
  reference breaks.

## Background

Phase 7c was written to stop the durable half of an application's narrative from being "rewritten
away every time the email assistant runs", by marking each timeline entry durable or disposable at
write time and adding a `promote` command that moves the durable ones into `companies/<key>/`.
It also carries a rename of the narrative file.

**Every measurement below was re-run on 2026-07-31 against the mounted overlay. No company,
employer, person, application slug or dated posting appears here — shapes and counts only.**

### The premise is measurably false

**The instruction does not say "rewrite".** `skills/email-assistant/SKILL.md` says, verbatim,
*"Preserve existing interview preparation, technical exercises, and other hand-written content"*,
and its rules block says a later review *"updates an existing entry instead of appending the same
email again"*. Exactly one section is instructed to shrink — the to-do dashboard — and that is the
disposable half being disposed of on purpose.

**And the history agrees.** Every commit in the overlay that has ever touched one of these files,
totalled:

```
+5,434 / −709 across 16 commits — and every single commit is net-additive.
```

There is **no observed instance** of the degradation this phase exists to prevent.

### The proposed flag is on the wrong syntactic object

18 of 126 files carry a hand-written section outside the three-section template — that count
reproduces exactly. But: **all 18 place every extra heading *after* `## Email Timeline`, as a
sibling section, never as a timeline entry.** So a `durable:` flag on a `### <date>` entry *inside*
the timeline cannot reach the content worth keeping.

And the value is concentrated far more than the count suggests. Hand-written tail per file,
descending:

```
544  192  24  10  4  4  4  4  4  3  3  3  3  3  3  3  3  3
```

**Two files hold 736 of 817 hand-written lines — 90%.** Fourteen of the eighteen are a 3–4-line
outcome stub restating a status already in `meta.yaml`.

### `promote`'s destinations exist in no phase and no folder

The design README gives the durable side a schema —
`companies/<key>/{company.yaml, loop.md, people.yaml, decision.md, …}`. On disk, the 25 company
folders contain only `research/` (18), `coding/` (9), `derived/` (2), `product-sense/` (1) and one
loose file. **`loop.md`, `people.yaml`, `company.yaml` and `decision.md` exist in zero folders,
and grepping the entire execution plan for those four names returns nothing.** So `promote` has a
source with no marker, a destination with no schema, and a key space of 222 keys of which 25 have
a folder at all.

`AGENTS.md` also forbids what the task calls it: *"application folders … are removed by the user
only — never by an agent, under any condition, including cleanup, migration"*. A `promote` that
moves content out of a file you wrote is an agent removing owner data. The safe verb is
copy-then-report.

### Doing the rename half first fails *silently*, and that is the real hazard

`status.py`'s calendar link builder falls back to `meta.yaml` when the narrative file is absent,
the note reader returns `None` on `OSError`, and the refresh sets the details field
**unconditionally** on every run. So if the files are renamed while the readers still name the old
file:

- nothing raises and no gate fails at write time;
- the next `status.py --refresh-calendar --write` **silently rewrites all 109 calendar links to
  point at `meta.yaml`** and drops every "latest update" line from the generated company view;
- the email assistant silently stops being offered the file, so the next mailbox review works from
  less context and can re-create a note it believes is missing.

The link checker *would* catch the dangling links — but only if run **before** someone refreshes
the calendar, because the refresh replaces broken links with wrong-but-resolvable ones and turns
the gate green again. **That is a silent data-quality regression reachable by a one-line ordering
mistake, and it is the single worst outcome available in this phase.**

### The one thing that IS a live defect, today, independent of the phase

**Two skills tell the model to write the same file in two incompatible shapes.**
`skills/email-assistant/SKILL.md` specifies `## Upcoming Events & To-Dos` / `## People` /
`## Email Timeline`. `skills/application-tracker/SKILL.md`'s "Record Interview Notes" specifies a
different template — `## Company Research`, then a `## <Round> (<date>)` section per round with
recruiter / topics / outcome bullets — for a file at the same path. Whichever skill runs last wins.
This is also why any parser built for this phase would be unreliable: keyed on `## Email Timeline`,
it returns an empty list on a file written to the other template rather than failing loudly.

## Options

### Option A — build phase 7c as specified
The durable marker, a new parser, a `promote` command, and the rename of 126 owner files plus 9
fixtures. Cost: a new instruction rule, a new module, a new file-moving command, a canary run, and
242 textual references across 66 files. Buys: protection for two files and ~700 lines, written by
hand, never touched by an agent, in a repo whose instruction file already tells agents not to touch
them. Adds a *new* way to lose owner data that does not exist today.

### Option B — descope to the one live defect *(recommended)*
Three items, none of which needs a marker, a parser, a rename or a canary run:

1. **Reconcile the two conflicting note templates.** One instruction edit. It is a defect today,
   independent of this phase, and it is the reason a parser would be unreliable.
2. **Add one sentence to the email-assistant SKILL** beside the existing preservation rule: *a
   section you did not write is owner content — never edit, reorder or summarise it.* That is the
   whole durable/disposable teaching, with no machinery.
3. **Move the two large hand-written writeups by hand, once, with you watching** — ~700 lines, two
   files, ten minutes, 90% of the phase's total value, zero new code and zero new failure modes.
   *(This one is your call, not an agent's — see the question below.)*

If a real degradation is ever observed, the marker design is written down and the evidence to
justify it will exist.

### Option C — do the rename only, leave the marker
The worst of the three. It banks no benefit (the marker is not there, so a run in the window
produces the same file under a new name) while taking on the entire silent-failure risk above. If
the rename is ever done, the safe order is readers-accept-both-names first, then the rename, then
drop the fallback.

## Recommendation

**Option B.** The phase exists to prevent a degradation that has never happened, using a mechanism
aimed at the wrong syntactic object, writing into destinations that do not exist, via a command
that would need to do something `AGENTS.md` forbids. Its one genuine finding — the conflicting
templates — is worth fixing on its own and costs one instruction edit.

**Two questions inside this, if you pick anything other than B:**

1. **Is renaming the narrative file the right thing at all?** You open this file by hand and have
   typed its current name for months. **Default: do not rename.** An unanswered naming question is
   not a resolution, and the phase's own definition of done says the question is resolved *before*
   any rename.
2. **Do the two large hand-written writeups move to a company folder, and under what filename?**
   None of the four filenames the design names exists anywhere. **No default — this is your own
   writing, and choosing its new home for you is the decision you are most likely to want back.**
   If forced: leave them where they are and add a one-line pointer from the company folder.

**Your answer:** ______
