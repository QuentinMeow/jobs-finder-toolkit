# Workspace layout — sign off on the design and the two things I need from you

- **Filed**: 2026-07-28
- **Look at**: [`docs/designs/workspace-restructure/README.md`](../../../docs/designs/workspace-restructure/README.md) · [`review-gate.md`](../../../docs/designs/workspace-restructure/review-gate.md) · [`execution-plan.md`](../../../docs/designs/workspace-restructure/execution-plan.md)
- **Why you might care**: This sets the shape of both repos. Phase 0 is separately urgent — it fixes a reproduced case where the publish guard prints "Safe to publish" over a file containing your real name.
- **If you do nothing**: Nothing moves. The phase-0 defects stay as they are.
- **Resolution**: Answered 2026-07-28. Topology, Q1/Q2/Q4/Q5/Q6 all decided and folded into
  [the design](../../../docs/designs/workspace-restructure/README.md), the
  [execution plan](../../../docs/designs/workspace-restructure/execution-plan.md), the
  [ADR](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md), and 11
  backlog tasks. Q3 deferred to `tasks/4_done/2026-07-28-company-key-assignment-approach`.
  This item stays open only until the owner confirms nothing was mis-folded; it is safe to
  delete after that.

## The design, in one screen

The private repo becomes the working root. Public content is reached through one
directory inside it whose **name is the instruction**:

```text
private/public/          # PROPOSED — nothing exists at this path today
```

It carries its own `AGENTS.md` ("everything below is published; no real names, employers,
dates, or salaries") that loads automatically on first read there.

Below the root, three lifetimes get three homes: `me/` (permanent, role-agnostic — profile,
resumes, story bank, practice), `companies/<key>/` (permanent per company — research,
`loop.md` for how they interview, people, coding problems, levels, decision), and
`applications/` (disposable). Plus `vendors/` — an interview-running firm is a format, not an
employer — and
`market/`, `store/`, `local/`. The name collisions disappear: your `memory/` is at the root,
the toolkit's is at `public/memory/`.

Detection is the second layer: any commit touching the public tree fails a test that prints
the changed files and says *read these for personal data*. It stays red until someone appends
a row to a tracked ledger — commit, file count, a digest of the actual diff, and a finding.
The digest is recomputed, so a row can't be guessed; it forces the diff into the reviewer's
context, which is where the judgment happens. Full spec in
[review-gate.md](../../../docs/designs/workspace-restructure/review-gate.md); I verified the
primitives work from the nested working root and that the digest is stable.

## Two things I need from you

**1. Test whether the agent's Grep/Glob tools can follow symlinks — before phase 4.**
This is the one thing that could make the working root unworkable rather than merely costly.
Measured: from the working root, `rg -l X .` finds nothing, and `rg -l X public/` **also
finds nothing** — only `rg --follow` or naming a link directly (`rg -l X public/skills`)
works. Those tools wrap ripgrep. If they expose no `--follow`, public code is unsearchable
from the working root and the door is a wall, not a speed bump. I can't test it — they aren't
loaded in this session.

Can't you test yourself?

> **2026-07-28 (agent):** I searched the deferred-tool registry twice; `Grep` and `Glob`
> aren't in this session's tool set (I have Bash, Read, Edit, Write, Agent, WebFetch,
> browser tools). I *did* test the underlying engine through Bash — ripgrep is blind to
> symlinked directories unless you pass `--follow`, and naming the parent (`rg X public/`)
> does not help. What I couldn't test is whether the Grep tool exposes a `--follow`
> equivalent; its documented parameters (`pattern`, `path`, `glob`, `type`, `output_mode`,
> `-i`/`-n`/`-A`/`-B`/`-C`, `head_limit`, `multiline`) contain no such option, so the honest
> answer is "almost certainly not, but unverified."
>
> **Your answer below makes this moot** — with the working root staying public there are no
> symlinks between an agent and public code, so search works with default flags. Question
> closed.

**2. Confirm you accept the standing costs.** They don't go away:
`.venv` has to move to the working root (240 documented commands get sed'd); `git status`
from the working root won't show public edits, so an agent can truthfully say "committed"
while a public edit sits uncommitted; and `git log`/`git bisect` across a change spanning both
zones needs two commands. All are in the README's cost table with mitigations.

A: I would still allow agents to view public stuff, so .venv won't go away. so working roots might still be public, just all instructions direct agents to look inside private ones if there's any. Again, I don't want to hide public repo from agents. Just make it structurally hard for it to make mistakes / or easily catch mistakes when they made them

## One measurement that changed the design

I prototyped the obvious PII detector — flag any public file naming a company in your private
tree — and it's unusable as a blocker: **51 of 177 private company tokens already appear in
public files**, led by `canonical` (114 files), `writer` (103), `render` (85), `lambda` (59),
`customer`, `iterable` — ordinary English words — plus Google, Microsoft, Amazon and
Anthropic, which legitimately appear as ATS providers and model vendors.

So it's narrowed to: run on the **diff** only, subtract everything already in the public tree
before the change, match **display names** from `companies/_index.yaml` rather than slug
fragments, skip `examples/` and the ATS registry — and it feeds the review gate as a *hint*,
never blocking on its own. Your instinct that the human/agent review step is the real defense
was right; the automated detector can only narrow where to look.

## Three things the taxonomy needs that aren't obvious

1. **The company key doesn't exist yet.** 242 application folders carry **213 distinct
   free-text company strings**, and the public registry resolves only 119 — 44% unresolvable,
   including several household-name employers the registry has no row for. Bare-name-versus-
   legal-suffix and bare-name-versus-parenthesised-entity splits are already live. Needs one owner-owned
   `companies/_index.yaml` (there are four competing alias registries today).

2. **Deleting an application is unsafe until the skip-log stops being derived.**
   `--sync-log` regenerates `applications-log.yaml` from a scan of the folders, so `rm -rf` a
   rejection, re-sync, and job-search offers it to you again as fresh. It becomes an
   append-only URL-keyed JSONL — deliberately not per-company markdown, because the skip check
   is URL-first and key-independent, so sharding by key would make every alias split a
   re-drafted application.

3. **Durable vs disposable splits at write time.** A sentence in your notes typically reads
   *"<recruiter> confirmed the 60-minute video coding interview for <date> … with <video
   tool> and <coding platform>"* — format permanent, date disposable, one sentence. The email assistant rewrites these files
   every run, so it has to emit a `durable:` flag per entry rather than anyone sorting it out
   later.

## Phase 0 — worth starting regardless

Reproduced: a tracked file containing your real full name, config discovery finding nothing →
`active tokens: 0` … `OK: no public-repo leaks detected. Safe to publish.` exit 0. `pre-push`
notices it's unarmed, warns, and pushes anyway. Also live: the guard never runs at commit
time; **`search-recall-audit` has never shipped in any export and is not installable** (five
lists disagree about which skills are public); the exporter walks the filesystem instead of
the index; the exported repo's CI is already red; and the private repo — about to host most
of your commits — has no git hooks at all.

Full list and fixes in
[execution-plan.md](../../../docs/designs/workspace-restructure/execution-plan.md#merged-phase-0--the-gates-fail-closed).

---

## Open questions (filed 2026-07-28, after your answers were folded in)

Your topology answer is recorded in
[`memory/decisions/workspace-layout-public-root-plus-review-gate.md`](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md)
and the design is rewritten around it. **None of these block round 1** (phase 0 gate repairs
+ phase 1 orphan cleanup) — each has a stated default so nothing stalls.

**Q1 — Review-gate scope and row rate.** *Blocks phase 3.*
Every tracked public file except the ledger (recommended), or only paths in the exporter
allowlist? The allowlist excludes `memory/`, `tasks/`, `message-queue/`, `history/` — which is
exactly where an agent writes prose about real work; all four live examples of employer names
in the public tree are in that excluded set. Cost of "everything": at 5–20 toolkit commits a
day, every one needs a ledger row. Relief if that bites is batching (one row covering a commit
range), not narrowing scope.
**Default: everything, one row per commit range.**
**Your answer:** ______

**Q2 — May an agent sign its own review?** *Blocks phase 3.*
`reviewed_by: agent` for everything (recommended), or require `reviewed_by: human` when the
advisory detector fires or a brand-new file appears under a docs-ish path?
**Default: agent signs; human required only when the detector fires.**
**Your answer:** ______

**Q3 — Who assigns the ~94 unresolvable company keys?** *Blocks phase 7.*
213 distinct company strings, 119 resolvable via the registry. The remaining 94 (Google,
Microsoft, subsidiaries, JVs, `-inc`/`-ltd` variants) need a human call. Options: I propose a
complete `companies/_index.yaml` in one PR for you to review in a single pass, or I auto-slug
and you correct as you encounter them.
**Default: one proposal PR.**
**Your answer:** ______

**Q4 — `docs/` consolidation reverses a recorded decision.** *Blocks phase 2.*
`docs/handbook/file-organization.md` records that a generic `docs/` was deliberately dissolved into
`docs/handbook/` + `docs/designs/`. The rule it applied (generic roots must fan out into purpose
sub-folders) is satisfied by `docs/{handbook,designs,roadmap}`, but the reversal needs its own
superseding ADR rather than a silent change. Confirm, and I write it.
**Default: consolidate, with the ADR.**
**Your answer:** ______

**Q5 — Rendered PDFs stay inside the disposable application folder.** *Blocks phase 5.*
Consequence: `rm -rf` on a rejected application deletes the exact resume and cover letter you
submitted. The alternative is sealing sent artifacts into `me/sent/` at the applied
transition — more correct, worse to live with (you'd browse a date-sorted filing cabinet
instead of the application folder).
**Default: they stay in the application folder.**
**Your answer:** ______

**Q6 — Handovers move to `private/local/history/` (never committed).** *Blocks phase 5.*
This is your earlier "history local only", now placed under `private/` so even a forced add
lands in the private repo. Consequence: the reconciler's `handover-present` check — which
`AGENTS.md` calls a backstop — fires only on the machine doing the work and is vacuous in CI,
and a handover written on one machine is invisible on the other.
**Default: local-only as you asked.** The alternative is to track them in the overlay
instead, at the proposed path below — that keeps the gate real everywhere and survives
machine loss.

```text
private/memory/history/  # PROPOSED alternative — nothing exists at this path today
```

**Your answer:** ______

---

## 2026-07-31 (agent) — re-checked, and NOT swept

A bookkeeping pass reached this item under the 30-day sweep rule and **declined to delete it**.
Recording why, so the next pass does not re-litigate it:

- **Every phase this review gated has merged.** Phases 0–7's public sides are all on `main`;
  phase 8 is the only one left and it is now unblocked. Q3 is closed — the task it deferred to,
  `2026-07-28-company-key-assignment-approach`, is in `tasks/4_done/`, and the company index it
  produced holds 222 keys with all 243 applications resolving against it.
- **Your typed answer at line 69 IS folded**, and this is the thing that was worth checking. It is
  in `memory/decisions/workspace-layout-public-root-plus-review-gate.md`, in the Decision section:
  the public repo stays the working root, *"Nothing is hidden from agents; instructions route them
  into `private/` for real data"*, and *"Preventing writes to public files is explicitly not a
  goal"*. Defence is naming plus after-the-fact detection — which is your "structurally hard to
  make mistakes, or easy to catch them" restated as a mechanism.
- **So why keep the file.** The Resolution says this item stays open until you confirm nothing was
  mis-folded, and that confirmation has not happened. Line 69 is the only owner-typed prose in the
  public queue and it exists verbatim nowhere else. Deleting it to satisfy a sweep rule would
  destroy owner text to tidy a folder, which is the wrong trade at any age.

**What is now left for you: one line.** If the fold above looks right, say so and this file can be
deleted. Nothing else in it is open.

---

## 2026-07-31 (agent) — two proposed paths moved into fenced blocks

Formatting only; no wording above was changed or removed. `verify_links.py` now treats
`message-queue/needs-human/reviews/` as a fail-closed tier (a review item points AT real
artifacts, so a dead pointer in one is rot). This item is the exception in that folder: it
*summarises a proposal*, and two of its backticked paths — the public directory in the
design summary and Q6's tracked-handovers alternative — name places that deliberately do
not exist. On a checkout with the overlay mounted, both were reported as broken references
and the documented manual gate exited 1; CI and pre-commit never saw it because both run
`--no-overlay`. Fencing them says "quoted proposal, not a pointer" in the way the checker
already understands, without demoting the tier that catches genuine rot.
