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
in `docs/AGENTS-ANNEX.md`; read the relevant § when a section points you there.

## Public vs Private (skills + products)

Two layered repos so timeless tooling can be published while anything tied to a real person
or job hunt stays private. **Leak rule: never put real names, employers, or dated/time-sensitive
data in the public tree** — it ships only the fake "Jordan Rivers" example.

- **Public toolkit repo (this repo)** — timeless tooling (`scripts/`, public skills + their
  scripts), the registry `.agents/skills/job-search/companies.yaml` (**identity only** — never
  specific or dated postings), a FAKE example candidate under `examples/`, general instructions.
  `config.example.yaml` is the tracked placeholder.
- **Private overlay repo** — its own git repo, mounted at the git-ignored `private/` dir;
  `config.yaml` points `paths.*` into it (real identity, profile, baseline, reference DOCX,
  applications, interviews, private `coding-interview` skill). See `docs/PRIVATE_OVERLAY.md`.

**Skill visibility** is a `visibility: public|private` key in each `SKILL.md`. **PUBLIC skills**
(SKILL.md + scripts published; PRODUCTS stay private): `ask-me-anything`, `job-search`,
`resume-writer`, `application-tracker`, `behavioral-interview-prep`, `company-research`,
`outlook-email-assistant`, `gardener`. **PRIVATE skill**: `coding-interview` — the entire skill
lives only in the overlay.

**PRODUCTS are always private** and mount under `private/` (real applications, discoveries,
company-level cache, interviews, profile/baseline/reference DOCX); only the fake `examples/**`
counterparts ship. **Personal content stays out of `SKILL.md`/`LESSONS.md`** — candidate DATA defers
to `config.yaml`/the profile; residual personal skill guidance goes in a git-ignored per-skill
`references_private/` (exporter prunes it; leak guard fails on any tracked file under it). **The leak
guard** (`scripts/publish/check_public.py`) hardcodes NO identity — it derives personal tokens from
`config.yaml`/overlay/`JOBHUNT_PERSONAL_TOKENS` and scans text + `.docx`/`.pdf`; `export_public.py`
runs it as the final publish gate. Routing: skills are discovered by listing `.agents/skills/`;
private `coding-interview` appears via a git-ignored symlink `scripts/bootstrap_overlay.py` creates.
Full detail: `docs/AGENTS-ANNEX.md` §2.

## Configuration

Identity, paths, and output-filename stems are never hardcoded — they load via
`scripts/shared/config.py` (vendored into each skill's `scripts/_vendor/config.py`). `config.yaml`
(git-ignored) holds real values; `config.example.yaml` (tracked) is the neutral **"Jordan Rivers"**
placeholder + fallback (discovery: `$JOBHUNT_CONFIG` → nearest `config.yaml` up from cwd then the
loader dir → `config.example.yaml`). **Paths** always come from `config.*_path()` functions (profile,
baseline, reference DOCX, company-levels, applications root, discoveries), never literals — real data
under `private/`, the public example under `examples/`. **Output stems** come from
`config.resume_stem()`/`cover_stem()`/`application_stem()`; never hardcode a person's filename stem —
use `<RESUME_STEM>`. **Generation mode**: `config.generation_mode()` returns `token_saving`
(default) or `full` — a token-usage dial for search + drafting; hard gates run identically in both.
Full function/path detail: `docs/AGENTS-ANNEX.md` §1.

## Repo Map (top level)

Full directory table (every script + per-skill row): `docs/AGENTS-ANNEX.md` §3.

| Path | Purpose |
|------|---------|
| `config.yaml` (git-ignored) / `config.example.yaml` (tracked) | Candidate identity, paths, output-stem config; example is the "Jordan Rivers" placeholder + fallback |
| `config.profile_md_path()` / `config.baseline_path()` | Candidate profile (source of truth for tailoring) / canonical transcription of the approved resume (start point for every `tailored.yaml`) |
| `.agents/skills/job-search/companies.yaml` | Canonical **public** registry (company identity, ATS config, tags); candidate blacklist rows live in git-ignored `private/job-search/blacklist.yaml` |
| `config.applications_root()` / `config.discoveries_dir()` | All applications in numbered status folders `0_profile`…`6_drafted` (the folder is the status) / ad-hoc job-search research |
| `.agents/skills/` | Canonical skills dir (PUBLIC skills — see Public vs Private; private `coding-interview` via symlink) |
| `scripts/shared/`, `scripts/vendoring/`, `scripts/maintenance/`, `scripts/metrics/`, `scripts/publish/` | Canonical toolkit modules; vendoring; maintenance/gardener; budget metrics; publish/leak-guard |
| `tmp/` | Gitignored scratch (purpose-named subfolders); never committed |
| `README.md`, `docs/ARCHITECTURE.md` (human) / `AGENTS.md`, `docs/AGENTS-ANNEX.md` | Human quickstart + design doc / this agent contract (core) + its extended reference |

## Read Order (boot sequence)

1. Read this file first for repo orientation. Open `docs/AGENTS-ANNEX.md` on demand when you
   need the full command cookbook, the complete directory table, or a detailed policy.
2. Read the relevant PUBLIC skill before working. Skills are **quickstart-first**: the SKILL.md
   routine path handles the common case; open a skill's `reference.md` (and the annex) only when it
   points you there. Route by need: `ask-me-anything` (new user / how it works / where to start),
   `job-search` (find/filter postings), `resume-writer` (tailoring), `application-tracker` (status),
   `behavioral-interview-prep`, `company-research` (company/role research + question bank),
   `outlook-email-assistant` (read personal Outlook mail, create repository-grounded reply drafts).
   Private `coding-interview` is at `.agents/skills/coding-interview/` when the overlay is mounted.
3. Read `.agents/MEMORY.md` (if present) for cross-session context.
4. Read the candidate profile (`config.profile_md_path()`) before tailoring — source of truth.

## Guardrails (hard behavioral invariants)

- **Never fabricate** experience, metrics, titles, or technologies not in the profile. Reframe
  and emphasize existing experience; never invent new experience.
- **Traceability & anchored, not frozen**: start every `tailored.yaml` as a copy of the baseline;
  every bullet maps to real, documented content (profile or the supporting library — annex §12).
  Rephrase and add real, traceable detail, but locked fields, titles, and skill-list gating always hold.
- **Validation is mandatory / hard gates**: `render.py` auto-runs `check.py` (locked
  identity/employer fields, real titles/skills, bullet counts, one-page PDF). A FAILed render must
  be fixed — never shipped or bypassed with `--skip-checks`.
- **Deep, tailored research**: each cover letter / why-fit / past-experience section shows genuine
  understanding of the company AND that JD (concrete real specifics, never invented claims). **One
  cover letter per JD — no shared/boilerplate letter.**
- **Skill lists**: honor the profile's Approved / Weak / Never lists; JD skills in none of them
  must be surfaced to the user for categorization, never added silently (full rule: annex §12).
- **Blacklist/log preflight**: before searching or drafting, honor the company blacklist
  (`private/job-search/blacklist.yaml`) and the skip-logs (`applications-log.yaml`,
  `company-search-log.yaml`) — never draft a blacklisted company or re-surface a logged posting.
- **Location policy**: only draft a role whose `location` matches `config.location_policy()`
  (preferred metros + US-remote); verify with `status.py --check-locations`.
- **Email is draft-only**: the Outlook assistant may read mail and create/update messages only while
  Microsoft Graph confirms `isDraft: true`. Never request `Mail.Send`, expose a send
  command/tool/endpoint, or send email on the user's behalf. The user sends manually in Outlook.
- **Honesty over optimization**: if the user's experience is a poor match, say so clearly.
- **Profile is user-owned**: ask before modifying the candidate profile (`config.profile_md_path()`).
- **Doc ownership**: `README.md` is human-facing (no agent instructions); `AGENTS.md` is agent-facing
  (no human usage guides).
- **Eval-gated harness edits**: any change to a skill's `SKILL.md`/`LESSONS.md`/`reference.md` must
  pass that skill's canaries (`evals/<skill>/canaries.yaml`) before merge with no large efficiency
  regression; record runs per `evals/README.md` (model-pinned). Harness self-edits are delta-only —
  never full-file rewrites, and **consolidation never deletes a domain edge case.**

## Handy Commands

Always use the repo venv `.venv/bin/python` (Python 3.11+). PDF conversion needs LibreOffice
(override with `JOBHUNT_SOFFICE`). Full cookbook (validate-only, metadata backfill/validate,
company-level import, log sync/record, DOCX extract, vendoring, hook install, deps): annex §4.

```bash
# Render a tailored resume (DOCX + PDF) + one cover letter per JD, then auto-validate.
.venv/bin/python .agents/skills/resume-writer/scripts/render.py applications/6_drafted/<slug>/
# Show all applications and their status (status = which folder each app lives in)
.venv/bin/python .agents/skills/application-tracker/scripts/status.py
# Populate/validate schema-v3 metadata (level, YOE, salary) from JD + cache
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --enrich-metadata applications/6_drafted/<slug>/
# Move an application to a different status folder (drafted|applied|in_progress|rejected|ignored)
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --update <slug> applied
```

## Conventions (quick reference)

Each expands in the annex; the bolded name is the canonical section.

- **Memory Map** — agent-memory zones (read/append points), retention, writers; promotion plus
  **forgetting** (TTL/prune/demotion) enforced by the `gardener` (dry-run). Full table: annex §5.
- **Sharing Code Across Skills** — skills are self-contained; a skill's `scripts/` **never** imports
  repo-root Python. Pure toolkit modules live once in `scripts/shared/`, vendored (byte-identical)
  into each skill's `scripts/_vendor/` via `scripts/vendoring/sync_vendored.py`; never edit a copy. Annex §7.
- **File & Folder Organization** — group files by purpose in a meaningful subfolder (never a generic
  `scripts/`/`docs/`/`data/`); reason tree-first before creating any file. Detail (incl. the
  coding-interview 150-char no-hard-wrap rule): annex §8.
- **Scratch & Temporary Files** — throwaway work (probes, scraped HTML/JSON, sanity checks) lives ONLY
  under the top-level gitignored **`tmp/`** in purpose-named subfolders (`tmp/ats_scripts/`,
  `tmp/web_artifacts/`, `tmp/scratch/`) — never the repo root or a tracked/product folder. Annex §9.
- **Subagent Budget** — a request that fans out launches **at most 8 subagents total** across all
  waves; reuse/resume or finish in the parent — never a ninth. Repo-wide cap. Annex §10.

## Application Folder Convention

Each application is a folder `<company>-<role>-<YYYYMMDD>/` under `applications/6_drafted/`; **status
is the parent status folder** (`0_profile`…`6_drafted`; the **user** moves folders, or use `status.py
--update <slug> <status>` — agents never move them unless asked). One resume covers the folder, but
**cover letters are one-to-one with JDs** — one `<COVER_STEM>_<job title>.pdf` + one bundled
`<APPLICATION_STEM>_<job title>.txt` per `meta.yaml` role; `render.py`/`cover_letter.py` emit all
names automatically. Slug: lowercase, hyphens (`google-ml-engineer-20260416`). The
`application-tracker` skill owns the full `meta.yaml` schema — read it before writing one. Canonical
file tree:

```
applications/6_drafted/<slug>/                     # multi-role: repeat cover/txt/JD per posting
├── meta.yaml                                    # tracking metadata (status = the folder)
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
`source/`) descriptions, and the divergent-role split: `docs/AGENTS-ANNEX.md` §11.
