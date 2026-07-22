---
description:
alwaysApply: true
---

# Agent Contract

This repo is a job-hunting toolkit — it tailors ATS resumes, writes **one cover letter per JD**,
and tracks applications through a status pipeline. It writes a `tailored.yaml` that a template
renders into a validated DOCX + PDF resume plus each JD's bundled `..._Application_<job title>.txt`
(one resume can cover several roles at one company; only divergent roles split). It ships **public**
(timeless tooling + the fake **"Jordan Rivers"** example) with a **private overlay** for real
identity/products. This is the core contract every agent reads BEFORE acting; extended detail —
full command cookbook, complete directory table, long rationale, edge-case policies, setup — lives
in `handbook/` (index: `handbook/README.md`); read the named doc when a section points you there.

**Collaboration mode:** `async` — decide everything reversible; file expensive-to-reverse choices
in `message-queue/needs-human/decisions/` with a default path and continue; stop only on
`Blocking: yes`. See `handbook/collaboration-modes.md`; a task file may override the mode for
that task only.

## Public vs Private (skills + products)

Two layered repos so timeless tooling can be published while anything tied to a real person
or job hunt stays private. **Leak rule: never put real names, employers, or dated/time-sensitive
data in the public tree** — it ships only the fake "Jordan Rivers" example.

- **Public toolkit repo (this repo)** — timeless tooling (`automation/`, public skills + their
  scripts), the registry `skills/job-search/companies.yaml` (**identity only** — never
  specific or dated postings), a FAKE example candidate under `examples/`, general instructions.
  `config.example.yaml` is the tracked placeholder.
- **Private overlay repo** — its own git repo, mounted at the git-ignored `private/` dir;
  `config.yaml` points `paths.*` into it (real identity, profile, baseline, reference DOCX,
  applications, interviews, private `coding-interview` skill). See `handbook/private-overlay.md`.

**Skill visibility** is a `visibility: public|private` key in each `SKILL.md`. **PUBLIC skills**
(SKILL.md + scripts published; PRODUCTS stay private): `ask-me-anything`, `job-search`,
`resume-writer`, `application-tracker`, `behavioral-interview-prep`, `company-research`,
`email-assistant`, `gardener`. **PRIVATE skill**: `coding-interview` — the entire skill
lives only in the overlay.

**PRODUCTS are always private** and mount under `private/` (real applications, discoveries,
company-level cache, interviews, profile/baseline/reference DOCX); only the fake `examples/**`
counterparts ship. **Personal content stays out of `SKILL.md`/`LESSONS.md`** — candidate DATA defers
to `config.yaml`/the profile; residual personal skill guidance goes in a git-ignored per-skill
`references_private/` (exporter prunes it; leak guard fails on any tracked file under it). **The leak
guard** (`automation/publish/check_public.py`) hardcodes NO identity — it derives personal tokens from
`config.yaml`/overlay/`JOBHUNT_PERSONAL_TOKENS` and scans text + `.docx`/`.pdf`; `export_public.py`
runs it as the final publish gate. Routing: skills are discovered by listing `skills/`;
private `coding-interview` appears via a git-ignored symlink `automation/bootstrap_overlay.py` creates.
Full detail: `handbook/public-private-split.md`.

## Configuration

Identity, paths, and output-filename stems are never hardcoded — they load via
`automation/shared/config.py` (vendored into each skill's `scripts/_vendor/config.py`). `config.yaml`
(git-ignored) holds real values; `config.example.yaml` (tracked) is the neutral **"Jordan Rivers"**
placeholder + fallback (discovery: `$JOBHUNT_CONFIG` → nearest `config.yaml` up from cwd then the
loader dir → `config.example.yaml`). **Paths** always come from `config.*_path()` functions (profile,
baseline, reference DOCX, company-levels, applications root, discoveries), never literals — real data
under `private/`, the public example under `examples/`. **Output stems** come from
`config.resume_stem()`/`cover_stem()`/`application_stem()`; never hardcode a person's filename stem —
use `<RESUME_STEM>`. **Generation mode**: `config.generation_mode()` returns `token_saving`
(default) or `full` — a token-usage dial for search + drafting; hard gates run identically in both.
Full function/path detail: `handbook/configuration.md`.

## Repo Map (top level)

Full directory table (every script + per-skill row): `handbook/repo-map.md`.

| Path | Purpose |
|------|---------|
| `config.yaml` (git-ignored) / `config.example.yaml` (tracked) | Candidate identity, paths, output-stem config; example is the "Jordan Rivers" placeholder + fallback |
| `config.profile_md_path()` / `config.baseline_path()` | Candidate profile (source of truth for tailoring) / canonical transcription of the approved resume (start point for every `tailored.yaml`) |
| `skills/job-search/companies.yaml` | Canonical **public** registry (company identity, ATS config, tags); candidate blacklist rows live in git-ignored `private/job-search/blacklist.yaml` |
| `config.applications_root()` / `config.discoveries_dir()` | All applications in numbered status folders `0_profile`…`6_drafted` (the folder is the derived overall status) / ad-hoc job-search research |
| `skills/` | Canonical skills dir (PUBLIC skills — see Public vs Private; private `coding-interview` via symlink) |
| `automation/` (shared, vendoring, maintenance, metrics, publish, store, reconcile, hooks) | Everything that runs: canonical toolkit modules, vendoring, gardener, metrics, leak guard, store tools, the reconciler, tracked git hooks |
| `templates/` | **Single source of truth for every process-file schema** — copy one to create any queue/task/memory item (`templates/README.md`) |
| `roadmap/` | `desired-state.md` vs `current-state.md` — the gap between them is the backlog's source |
| `history/` | One folder per working session, each with a `handover.md` |
| `tmp/` | Gitignored scratch (purpose-named subfolders); never committed |
| `message-queue/` (`needs-human/`: `decisions/`, `clarifications/`, `reviews/`; `needs-agent/`: `requests/`, `retries/`) | Async human↔agent messages, one file each, routed by **who acts next** (see Async Collaboration) |
| `tasks/` (status folders `0_backlog`…`4_done`) | Work items; the folder a task sits in IS its status (`tasks/README.md`) |
| `memory/` (`decisions/` ADRs, `known-issues/`, `facts/`, `lessons/`) | Long-term project memory; ADRs are immutable — a reversal is a new file |
| `README.md`, `handbook/architecture.md` (human) / `AGENTS.md`, `handbook/README.md` | Human quickstart + design doc / this agent contract (core) + its extended reference |

## Read Order (boot sequence)

1. Read this file first for repo orientation. Open the `handbook/` doc a section points to on
   demand — command cookbook, full directory table, detailed policies (index: `handbook/README.md`).
2. Read the relevant PUBLIC skill before working. Skills are **quickstart-first**: the SKILL.md
   routine path handles the common case; open a skill's `reference.md` (and the handbook) only when
   it points you there. Route by need: `ask-me-anything` (new user / how it works / where to start),
   `job-search` (find/filter postings), `resume-writer` (tailoring), `application-tracker` (status),
   `behavioral-interview-prep`, `company-research` (company/role research + question bank),
   `email-assistant` (read personal Outlook mail, create repository-grounded reply drafts).
   Private `coding-interview` is at `skills/coding-interview/` when the overlay is mounted.
3. Read `.agents/MEMORY.md` (if present) for cross-session context, and skim `memory/index.md`
   (generated) — open only the entries relevant to your task.
4. If your work changes overall architecture, read `roadmap/current-state.md` and
   `roadmap/desired-state.md` — a new task should trace to a desired-state line.
5. Before tailoring, read the tailoring card (`<applications_root>/0_profile/tailoring-card.md`) — the distilled default context; open the full profile (`config.profile_md_path()`, source of truth) only on the resume-writer skill's escalation triggers (card missing/stale/`--check` fail, or a JD domain the card doesn't cover).

## Async Collaboration (message-queue/ + tasks/ + doc dialogue)

The owner and agents work asynchronously: each side writes files, the other picks them up next
session. Messages live in **`message-queue/`**, split by **who acts next** (map + per-queue
formats: `message-queue/README.md`; private-scope mirror: `private/message-queue/`):
`needs-human/decisions/` (owner-only questions, each with options + recommendation + a **default
path** agents follow while pending), `needs-human/clarifications/` (questions that matter soon;
agent proceeds on a stated assumption), `needs-human/reviews/` (optional human-eyes items),
`needs-agent/requests/` (human→AI free-form drop box), `needs-agent/retries/` (mechanical repair
items). Work items live in **`tasks/`** — one folder per task, its status folder IS its status
(`tasks/README.md`). Decided questions and bug records live in **`memory/`**.

**Boot ritual** — run by the **top-level session only** (subagents never run it); skip entirely if
`message-queue/` is absent (public exports omit it). Filenames first; open only what's relevant:
1. `ls message-queue/needs-agent/requests/` (+ the `private/` mirror if mounted). For each item:
   act, or convert it (task / decision / dated reply appended to the item), then delete the
   request file in the same commit. **Valve:** if the user's request is explicitly narrow or items
   exceed 3, process what fits and list the remainder by name in your reply — reporting satisfies
   "never skip silently".
2. `ls message-queue/needs-agent/retries/` — pick up repair items touching this session's area;
   never delete one without fixing it or explicitly rejecting it in the file.
3. Scan `message-queue/needs-human/decisions/` for new owner answers (they arrive in the queue
   file, in a doc's decision block, or in chat; skip `parked` items unless their revisit condition
   matches this session's work). **Claim before folding:** commit a one-line `Status: folding`
   edit to the queue file first. Then fold the answer into the affected docs, update BOTH surfaces
   of a mirrored question in the same commit, record it in `memory/decisions/`, delete the queue
   file. **An answer heard in chat is written into the queue file in the same turn, before any
   other work** — chat is the only channel with no file trace of its own.
4. Pick up `tasks/0_backlog/` items when relevant to the session's work or when asked (claim
   first: `Claimed-by` in `task.md`, move to `1_in-progress/`).
5. Sweep `message-queue/needs-human/reviews/`: delete items with a filled Resolution, or older
   than 30 days.

**Always:** end your reply with one line per pending `needs-human/` item you filed or noticed —
chat is the owner's only push channel. Before opening a PR whose work relied on a pending
decision's default path, re-check that decision file. Never name or summarize
`private/message-queue/` or `private/tasks/` items in public PR descriptions or commit messages.

**End of session** (any session that did real work): write
`history/conversations/<YYYY-MM-DD>-<slug>/handover.md` from `templates/handover.md` (one screen,
for a human who was away), update the task's `worklog.md`, and file any pending questions into
`message-queue/` — the reconciler's `handover-present` check backstops this.

**Doc dialogue:** human-read documents carry two-way fields — decision blocks with
`**Your answer:**` lines, "Decisions (resolved)" tables (the owner may amend those too — check
them on any visit), and a trailing `## Human questions / additional tasks` section (contract:
`handbook/doc-style.md`, the decision-block and async-fields sections). On any visit to a doc: answer owner questions in place (dated,
appended — never delete or overwrite owner text, and **re-read any two-way file immediately
before writing it; if it changed since your last read, merge — never clobber**), file owner-added
tasks into `tasks/0_backlog/`, and treat a filled answer line as a decision event (fold in →
record → prune to a resolved-table row). If a doc block and its queue mirror conflict, **the doc
block wins**. An owner "answer" that is itself a question gets answered inside the block with
concrete examples, stays open, and is mirrored into `message-queue/needs-human/decisions/` so it
cannot be lost.

## Folder-Scoped Context (tree instructions)

Some folders carry local context in their own `AGENTS.md`, with a sibling `CLAUDE.md → AGENTS.md`
symlink so Claude Code lazy-loads it on first file-read there (Cursor applies nested AGENTS.md
natively; this root contract itself loads via the root `CLAUDE.md` import shim). Leaf files are
**additive-only** — pointers, or lines relocated out of always-loaded files; they never restate or
override this contract, and a conflict is a bug in the leaf. Unbounded detail lives in that
folder's `agents-references/`, reached only via task-conditioned pointer lines ("before <task>,
read <file>"). Hard invariants live only in this file + hooks, never in leaves. After a context
compaction, re-read the `AGENTS.md` of any routed folder you're still working in. Leaf creation is
reactive — second folder-local correction or explicit owner ask; propose via
`message-queue/needs-human/decisions/` when unsure (design: `design/tree-instructions/README.md`).

Router:
- Working under `design/`? Read `design/AGENTS.md` first (skip if your tool already injected it).
- Creating any queue item, task file, memory entry, or handover? Copy its schema from
  `templates/` (`templates/README.md`) — never write a format from memory.

## Guardrails (hard behavioral invariants)

- **Never fabricate** experience, metrics, titles, or technologies not in the profile. Reframe
  and emphasize existing experience; never invent new experience.
- **Traceability & anchored, not frozen**: start every `tailored.yaml` as a copy of the baseline;
  every bullet maps to real, documented content (profile or the supporting library — `handbook/tailoring-guardrails.md`).
  Rephrase and add real, traceable detail, but locked fields, titles, and skill-list gating always hold.
- **Validation is mandatory / hard gates**: `render.py` auto-runs `check.py` (locked
  identity/employer fields, real titles/skills, bullet counts, one-page PDF). A FAILed render must
  be fixed — never shipped or bypassed with `--skip-checks`.
- **Deep, tailored research**: each cover letter / why-fit / past-experience section shows genuine
  understanding of the company AND that JD (concrete real specifics, never invented claims). **One
  cover letter per JD — no shared/boilerplate letter.**
- **Skill lists**: honor the profile's Approved / Weak / Never lists; JD skills in none of them
  must be surfaced to the user for categorization, never added silently (full rule: `handbook/tailoring-guardrails.md`).
- **Blacklist/log preflight**: before searching or drafting, honor the company blacklist
  (`private/job-search/blacklist.yaml`) and the skip-logs (`applications-log.yaml`,
  `company-search-log.yaml`) — never draft a blacklisted company or re-surface a logged posting.
- **Location policy**: only draft a role whose `location` matches `config.location_policy()`
  (preferred metros + US-remote); verify with `status.py --check-locations`.
- **Email is draft-only**: the email assistant may read mail and create/update messages only while
  Microsoft Graph confirms `isDraft: true`. Never request `Mail.Send`, expose a send
  command/tool/endpoint, or send email on the user's behalf. The user sends manually in Outlook.
- **Honesty over optimization**: if the user's experience is a poor match, say so clearly.
- **Profile is user-owned**: ask before modifying the candidate profile (`config.profile_md_path()`).
- **Doc ownership**: `README.md` is human-facing (no agent instructions); `AGENTS.md` is agent-facing
  (no human usage guides).
- **The reconciler is a gate**: `automation/reconcile/reconcile.py --check` (process-layer
  schemas, memory index, handovers, roadmap freshness) runs in pre-commit + CI and must pass —
  fix the finding or let `--file-retries` queue it; never weaken a check to make a commit pass,
  never bypass with `--no-verify`.
- **Risk-based eval gate on harness edits**: for any change to a skill's
  `SKILL.md`/`LESSONS.md`/`reference.md`, the editing agent decides whether to run that skill's
  canaries (`evals/<skill>/canaries.yaml`) by judging the edit's **intention and size** —
  behavioral or large edits must pass canaries before merge (no large efficiency regression,
  model-pinned, runs recorded per `evals/README.md`); mechanical or small edits may skip **with a
  recorded one-line rationale**. See `evals/README.md` for the run/skip criteria. Harness
  self-edits are delta-only — never full-file rewrites, and **consolidation never deletes a domain
  edge case.**

## Handy Commands

Always use the repo venv `.venv/bin/python` (Python 3.11+). PDF conversion needs LibreOffice
(override with `JOBHUNT_SOFFICE`). Full cookbook (validate-only, metadata backfill/validate,
company-level import, log sync/record, DOCX extract, vendoring, hook install, deps): `handbook/command-cookbook.md`.

```bash
# Render a tailored resume (DOCX + PDF) + one cover letter per JD, then auto-validate.
.venv/bin/python skills/resume-writer/scripts/render.py applications/6_drafted/<slug>/
# Show all applications and their status (status = which folder each app lives in)
.venv/bin/python skills/application-tracker/scripts/status.py
# Populate/validate schema-v4 metadata (per-job status, level, YOE, salary) from JD + cache
.venv/bin/python skills/application-tracker/scripts/status.py --enrich-metadata applications/6_drafted/<slug>/
# Move an application to a different status folder (drafted|applied|in_progress|rejected|ignored)
.venv/bin/python skills/application-tracker/scripts/status.py --update <slug> applied
```

## Conventions (quick reference)

Each expands in a named `handbook/` doc; the bolded name is the canonical section.

- **Memory Map** — agent-memory zones (read/append points), retention, writers; promotion plus
  **forgetting** (TTL/prune/demotion) enforced by the `gardener` (dry-run). Full table: `handbook/memory-map.md`.
- **Sharing Code Across Skills** — skills are self-contained; a skill's `scripts/` **never** imports
  repo-root Python. Pure toolkit modules live once in `automation/shared/`, vendored (byte-identical)
  into each skill's `scripts/_vendor/` via `automation/vendoring/sync_vendored.py`; never edit a copy. Detail: `handbook/skills-and-vendoring.md`.
- **File & Folder Organization** — group files by purpose in a meaningful subfolder (never a
  generic *scripts*/*docs*/*data* bucket); reason tree-first before creating any file. Detail (incl. the
  coding-interview 150-char no-hard-wrap rule): `handbook/file-organization.md`.
- **Scratch & Temporary Files** — throwaway work (probes, scraped HTML/JSON, sanity checks) lives ONLY
  under the top-level gitignored **`tmp/`** in purpose-named subfolders (`tmp/ats_scripts/`,
  `tmp/web_artifacts/`, `tmp/scratch/`) — never the repo root or a tracked/product folder. Detail: `handbook/file-organization.md`.
- **Subagent Budget** — a request that fans out launches **at most 8 subagents total** across all
  waves; reuse/resume or finish in the parent — never a ninth. Repo-wide cap (`handbook/subagent-budget.md`).
- **Process Folders** — `message-queue/` + `tasks/` (see **Async Collaboration** above) plus the
  memory zones `memory/decisions/` and `memory/known-issues/` (+ same-name `private/` mirrors for
  leak-guarded content): one self-contained item per file, schemas in `templates/` (copy, never
  restate). Hit an owner-owned fork? File it in `message-queue/needs-human/decisions/` (with
  options + a default path) and continue — don't block, don't guess.
- **Shell & Paths** — the shell is **zsh**; always use **absolute paths** in bash calls (a subagent's
  working directory resets between calls, so relative paths break), and **quote** any `=`-leading
  argument or glob (`'--flag=val'`, `'*.md'`) so zsh does not mis-split or expand it.
- **Read Hygiene** — never re-Read a file already in context (duplicate reads are pure token waste);
  for a file over ~800 lines, prefer a `grep` or an offset/limit slice over reading the whole file.

## Application Folder Convention

Each application is a folder `<company>-<role>-<YYYYMMDD>/` under `applications/6_drafted/`; **each
`jobs:` entry carries a per-job `status`, and the parent status folder is the derived overall status
(rollup) — the two must agree** (`0_profile`…`6_drafted`; the **user** moves folders, or use
`status.py --update`/`--update-job` — agents never move them unless asked). One resume covers the folder, but
**cover letters are one-to-one with JDs** — one `<COVER_STEM>_<job title>.pdf` + one bundled
`<APPLICATION_STEM>_<job title>.txt` per `meta.yaml` role; `render.py`/`cover_letter.py` emit all
names automatically. Slug: lowercase, hyphens (`google-ml-engineer-20260416`). The
`application-tracker` skill owns the full `meta.yaml` schema — read it before writing one. Canonical
file tree:

```
applications/6_drafted/<slug>/                     # multi-role: repeat cover/txt/JD per posting
├── meta.yaml                                    # tracking metadata (per-job status; folder = derived rollup)
├── <RESUME_STEM>.pdf                            # ONE final resume (for humans/email)
├── <COVER_STEM>_<Role>.pdf                      # one cover-letter PDF per JD
├── <APPLICATION_STEM>_<Role>.txt               # one bundled copy-paste packet per JD
├── notes.md                                     # optional interview/company notes
└── source/                                      # generation inputs/intermediates
    ├── JD-<job title>.md                        # one per posting, ALWAYS JD-prefixed
    ├── tailored.yaml                            # AI-tailored resume content (one resume)
    ├── <RESUME_STEM>.docx                       # submit this DOCX to ATS portals
    └── <COVER_STEM>_<Role>.docx                 # one per JD
```

Full status-folder table, numeric-prefix rules, per-file (`meta.yaml`, `.txt` section format,
`source/`) descriptions, and the divergent-role split: `handbook/application-folders.md`.
