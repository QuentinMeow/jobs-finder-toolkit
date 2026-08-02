# Does `doc-style.md` bind only `docs/designs/`, or every human-read document?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [docs/handbook/doc-style.md](../../../docs/handbook/doc-style.md)
- **Blocks**: nothing.
- **Default path**: agents treat §§1-4 and §7 (the prose and figure rules) as binding
  under `docs/designs/` only, and §§5-6 (decision blocks, `**Your answer:**` lines,
  resolved tables, `## Human questions / additional tasks`) as binding wherever a
  two-way field actually appears. That is what practice already does; it is just not
  what any single file says.
- **Cost if wrong**: ratify
- **Safe to merge because**: a scope convention changes no file on disk; re-scoping later is a doc
  edit.

## Background

Four surfaces disagree about which documents this style contract governs, and the file
disagrees with itself.

**Narrow.** `docs/handbook/doc-style.md:1-3`:

> # Design-doc writing style
>
> Rules for every document under `docs/designs/`.

`docs/designs/AGENTS.md:3` reads it the same way — *"the binding writing contract for
design docs"*.

**Broad.** `docs/handbook/README.md:24`:

> | `docs/handbook/doc-style.md` | Style contract for **human-read documents** (decision blocks, async fields) |

And `AGENTS.md:166-169`, the Doc dialogue paragraph, applies it to *"human-read
documents"* generally:

> **Doc dialogue:** human-read documents carry two-way fields — decision blocks with
> `**Your answer:**` lines, "Decisions (resolved)" tables … and a trailing
> `## Human questions / additional tasks` section (contract:
> `docs/handbook/doc-style.md`, the decision-block and async-fields sections).

**And the file widens back out on its own.** Its §6 is titled *"Async collaboration fields
(human-read documents)"* (`:89`) and states at `:105-106`:

> **Every human-read document ends with a `## Human questions / additional tasks`
> section** — free space the owner can write into at any time.

**What practice does.** `grep -rn "^## Human questions"` finds the section in exactly
**eight** files, all under `docs/designs/` — the three `application-progress-calendar`
docs, two `raw-data-layer` docs, three `workspace-restructure` docs. No `tasks/*/task.md`,
no roadmap file, no queue item, no handbook page has one. So today's tree is the narrow
reading, and §6's sentence is false about ~90% of the repository's human-read markdown.

**Why it is worth your minute rather than an agent's.** An agent editing
`docs/roadmap/current-state.md` or a `tasks/*/task.md` today follows `AGENTS.md` to a
style contract whose first line says it does not cover the file being edited. Both
readings are defensible from the text, so the agent either applies rules that were never
meant for that file or ignores a contract `AGENTS.md` told it to obey. The failure is
quiet either way, which is why it has survived.

**One observation that I think decides it.** `AGENTS.md:168` does not cite the file — it
cites *"the decision-block and async-fields sections"*, i.e. §5 and §6 specifically. The
contract `AGENTS.md` actually leans on is already section-scoped; what has not caught up
is the file's own header, which claims the whole document is about design docs. So the
split below is not a new structure — it is the one already in use.

## Options

### Option A — narrow the claims to match the file

Change `docs/handbook/README.md:24` to say "design docs", change §6's "every human-read
document" to "every design doc", and reword the `AGENTS.md:166-169` citation to point at
design docs.

*Pros:* smallest edit; the tree already conforms, so nothing new is owed. *Cons:* it
throws away a rule that is genuinely good outside `docs/designs/` — the trailing
free-space section is how the owner adds a question to a document without opening a queue
item, and the doc-dialogue paragraph in `AGENTS.md` is written for *all* human-read
documents on purpose. Narrowing here quietly narrows that too.

### Option B — widen `doc-style.md:3` to every human-read document

Its line 3 becomes "every human-read document; §§1-4 and §7 bind `docs/designs/` in
particular".

*Pros:* one line changed; `AGENTS.md` and the handbook index become true as written.
*Cons:* taken literally, §6 then obliges every `tasks/*/task.md` (53 today), both roadmap
files and every queue item to grow a `## Human questions / additional tasks` section —
process weight duplicating what `message-queue/` already provides, on files whose whole
design is that they are small. Unless §6 is also softened, B trades a scope bug for a
compliance bug across roughly 70 files.

### Option C — split the file's scope explicitly, section by section

One paragraph under the title: §§1-4 and §7 (sections stand alone, clickable references,
prose findings, both figure forms, general prose) bind `docs/designs/`; §§5-6 (decision
blocks and async collaboration fields) bind any document that carries a two-way field,
wherever it lives — and a document is not obliged to carry one. `docs/handbook/README.md:24`
keeps its current wording, which becomes accurate; `AGENTS.md:166-169` needs no edit at
all, because it already cites those two sections by name.

*Pros:* makes the document say what the system already does; nothing new is owed by any
existing file; the one edit is confined to `doc-style.md` itself. *Cons:* a scope
paragraph is more to read than a scope line, and "binds any document that carries a
two-way field" is softer than an absolute — an editor who wants to skip the rules can
decline to add a decision block in the first place. In practice that is fine, because the
block is added when there is a question to ask.

## Recommendation

**Option C.** It is the only one of the three that requires no file in the tree to change
except `doc-style.md`, and it is what `AGENTS.md` already assumes — it cites two named
sections, not the document. The §6 sentence is then repaired by scope rather than by
weakening: "every human-read document that carries async fields", which is true today and
stays true.

If C is more structure than you want in a style file, **Option A** is the safe fallback:
it is honest, it is one word in three places, and the doc-dialogue rules keep working from
`AGENTS.md` alone, which is where agents read them anyway. I would not pick B without also
softening §6 in the same commit, or it silently bills roughly 70 files for a section they
do not need.

**Your answer:** ______
