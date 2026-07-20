---
description:
alwaysApply: true
---

# Agent Contract

## Summary

This repo is a job-hunting toolkit: it tailors resumes for ATS optimization, writes
per-posting cover letters, and tracks applications through a status pipeline. All
candidate-specific values (identity, paths, output-filename stems) come from a git-ignored
`config.yaml` (see "Configuration"), never hardcoded; the shipped fallback is the fake
"Jordan Rivers" example. For each application the AI writes a structured `tailored.yaml`
that a template renders into a validated DOCX + PDF resume, plus **one cover letter per JD**
(a one-to-one mapping with each posting) rendered from that role's bundled, copy-paste
`..._Application_<job title>.txt` (cover letter + "why this company/role" + "past experience"
sections, deeply researched per posting). Each application folder keeps only the final PDFs,
the bundled `.txt`(s), and `meta.yaml` at its root; all generation inputs (JD files,
`tailored.yaml`, DOCX) live in a `source/` subfolder — see "Application Folder Convention".
When one company posts several jobs the default is one resume covering them all (still one
cover letter per posting); only divergent roles split into separate applications. The
canonical company registry `.agents/skills/job-search/companies.yaml` is the single source of
truth for company identity, ATS poll config, and the blacklist. Project skills live
canonically in `.agents/skills/` so every AI agent shares them. The toolkit
ships **public** (timeless tooling + a fake example candidate); a **private overlay** supplies
the real identity and products (see "Public vs Private").

## Configuration

Candidate identity, paths, and output filename stems are never hardcoded — they come
from a config file loaded by `scripts/shared/config.py` (vendored into each consuming
skill's `scripts/_vendor/config.py`):

- `config.yaml` (git-ignored) holds the real values. `config.example.yaml` (tracked) is a
  neutral **"Jordan Rivers"** placeholder that doubles as the fallback when no `config.yaml`
  is found. Discovery order: `$JOBHUNT_CONFIG` → nearest `config.yaml` walking up from cwd
  then from the loader's directory → `config.example.yaml`. Paths in the config are resolved
  relative to the config file's directory.
- **Paths** come from config, not literals — always accessed via the `config.py` functions:
  the candidate profile is `config.profile_md_path()` (example:
  `examples/profile/profile.example.md`), the baseline is `config.baseline_path()`, the
  rendering reference DOCX is `config.reference_docx_path()`, the reusable sourced company
  leveling/compensation cache is `config.company_levels_path()` (default: beside the profile;
  compensation bands are age-gated while level/YOE mappings retain provenance), the
  applications root is `config.applications_root()` (`applications/` by default), and the
  discoveries dir is `config.discoveries_dir()`. Real data mounts under `private/` and the
  public example under `examples/`; the function always returns the configured absolute path.
- **Output filename stems** come from `config.resume_stem()` / `config.cover_stem()` /
  `config.application_stem()` — each built from `name_slug` + `title_slug` (plus an optional
  target-position label via `layout.compose_stem`). Never hardcode a concrete person's filename
  stem anywhere; refer to `<RESUME_STEM>` / "the configured stem". With the example config the
  resume stem is `Jordan_Rivers_Software_Engineer_Resume`.

## Public vs Private (skills + products)

The toolkit is layered as two repos so timeless tooling can be published while everything
tied to a real person or a real job hunt stays private:

- **Public toolkit repo (this repo)** — public-ready: ships only timeless, general
  information — the tooling (`scripts/`, public skills + their scripts), the company registry
  `.agents/skills/job-search/companies.yaml` (**identity only** — never specific or dated
  postings), a FAKE example candidate under `examples/` (`examples/profile/…`,
  `examples/templates/…`, `examples/applications/…`), and general instructions/techniques.
  `config.example.yaml` is the tracked placeholder.
- **Private overlay repo** — its **own git repo** synced to a private GitHub remote, mounted
  at a git-ignored **`private/`** directory inside the public checkout. `config.yaml`
  (git-ignored) points the toolkit's `paths.*` into it — real
  identity, profile, baseline, reference DOCX, applications, interviews, and the private
  `coding-interview` skill all live under `private/`. See `docs/PRIVATE_OVERLAY.md`.

**Skill visibility** is declared by a `visibility: public|private` key in each `SKILL.md`
frontmatter:

- **PUBLIC skills** (SKILL.md + scripts are published; their generated PRODUCTS stay private):
  `ask-me-anything`, `job-search`, `resume-writer`, `application-tracker`,
  `behavioral-interview-prep`, `company-research`, `gardener`.
- **PRIVATE skill**: `coding-interview` — the ENTIRE skill (SKILL.md + product) lives only in
  the private overlay and never ships in the public repo.

**PRODUCTS are always private** and mount under `private/`: anything tied to real jobs, the
candidate's background, or dated/time-sensitive info — the real applications
(`config.applications_root()`, e.g. `private/applications/**`, including the discoveries dir
and the real company-level cache), the real interviews (`private/interviews/**` — every real
interview product, from company-info to behavioral/coding prep, belongs here), and the real
profile / baseline / reference DOCX. The overlay is git-ignored in the public checkout and the
exporter excludes it; only fake `examples/**` counterparts are published.

**Personal skill content stays out of `SKILL.md`.** The tracked `SKILL.md` / `LESSONS.md`
of a PUBLIC skill must be personal-free: they defer candidate DATA to `config.yaml` /
the profile and use the generic "Jordan Rivers" examples. Any residual candidate-specific
skill guidance (real lead-project ordering, real metrics, personal anecdotes) goes in a
git-ignored, per-skill **`references_private/`** folder — the exporter prunes it, the leak
guard fails on any tracked file under it, and `.gitignore` ignores it. Each `SKILL.md`
"Before You Start" carries a **Personalization** stanza telling the agent to read
`references_private/` (overrides the generic examples) when present, and to fall back to
the generic examples otherwise.

**The publish leak guard derives its tokens** (`scripts/publish/check_public.py` →
`personal_tokens()`) from the git-ignored `config.yaml` identity, an optional git-ignored
`private/leak_tokens.txt`, and the `JOBHUNT_PERSONAL_TOKENS` env var — it hardcodes NO
real identity and scans both text and document-binary (`.docx`/`.pdf`) content. The
exporter (`export_public.py`) always runs it against the copied tree as the final gate.

**Routing**: skills are discovered by listing `.agents/skills/` — this file's skills table
names only the PUBLIC ones that ship in the repo. The private `coding-interview` skill
appears in `.agents/skills/` via a git-ignored symlink that `scripts/bootstrap_overlay.py`
creates, so it stays discoverable whenever the overlay is mounted.

## Folder Structure

All job-search content (the candidate's profile materials, research findings, and every
application) lives under the applications root (`config.applications_root()`, `applications/`
by default, real data under `private/applications/`); only shared tooling (`scripts/`,
`.agents/skills/`) sits at the repo root. Files are grouped by purpose into
meaningful subfolders (see "File & Folder Organization"): `scripts/` fans out into
`scripts/shared/`, `scripts/vendoring/`, and `scripts/maintenance/` (each skill bundles its
own render/tracking scripts under `.agents/skills/<skill>/scripts/`). Application status is encoded by which sub-folder the application sits in
(the folder is the source of truth for status); the profile directory (`<profile-dir>` — the
directory containing `config.profile_md_path()`, where the skip-logs live; by convention
`<applications_root>/0_profile/` in a real overlay, `examples/profile/` in the shipped
example) and `config.discoveries_dir()` are support folders, not applications.

| Path | Purpose |
|------|---------|
| `config.yaml` (git-ignored) / `config.example.yaml` (tracked) | Candidate identity, paths, and output-stem config; the tracked example is the neutral "Jordan Rivers" placeholder + fallback (see "Configuration") |
| `config.profile_md_path()` (example: `examples/profile/profile.example.md`) | Comprehensive candidate profile: all experience, skills, and resume writing preferences |
| `config.baseline_path()` | Canonical transcription of the approved resume — starting point for every tailored.yaml and the reference for locked-field validation |
| `.agents/skills/job-search/companies.yaml` | Canonical company registry — public, single source of truth for company **identity**, ATS poll config, and tags. Ships NO personal skip rules; candidate-specific blacklist rows (companies that don't sponsor, the candidate's own employer) live in a git-ignored overlay `private/job-search/blacklist.yaml` merged at load time by `registry.py` (each row: identity-only + `blacklist:` reason, no `ats`/`token`). Never carries specific or dated postings |
| `<profile-dir>/applications-log.yaml` | Auto-generated (via `status.py --sync-log`) list of postings already generated/considered — job-search skips them (new roles at the same company still surface) |
| `<profile-dir>/company-search-log.yaml` | Last successful full-company search per employer — job-search skips within 7 days (`skip_within_days`); upserted by `--sync-log` (`created`) or `--log-search` (`no_suitable`) |
| `config.company_levels_path()` | Reusable, sourced company level/YOE/base-salary/total-compensation mappings used as a fallback when a live JD omits those facts; real dated research defaults beside the private profile, while the public toolkit ships only `examples/profile/company-levels.example.yaml` |
| `<profile-dir>/resumes/` | The candidate's approved master resume file(s) |
| `config.discoveries_dir()` | Ad-hoc research findings during the job search (job-search output, target-company lists) |
| `config.applications_root()/6_drafted/<slug>/` | Generated applications land here first — for the user to review the resume + JD and decide the next move |
| `config.applications_root()/5_applied/<slug>/` | Applications the user has submitted (user moves the folder here manually) |
| `config.applications_root()/4_in_progress/<slug>/` | Heard back / interviews scheduled — active pipeline (user moves here manually) |
| `config.applications_root()/3_rejected/<slug>/` | Rejected at any stage (user moves here manually) |
| `config.applications_root()/2_ignored/<slug>/` | Decided not to submit; don't reconsider this posting (user moves here manually) |
| `config.reference_docx_path()` (default `examples/templates/reference.example.docx`; real DOCX under `private/`) | Formatted resume DOCX — the rendering reference (preserves all formatting) |
| `.agents/skills/resume-writer/scripts/render.py` | Fill the DOCX template from `source/tailored.yaml` → resume DOCX (`source/`) + PDF (root, stem from `config.resume_stem()`) + **one cover letter per JD**; auto-runs `check.py`. Detail in the resume-writer skill |
| `.agents/skills/resume-writer/scripts/cover_letter.py` | Render one cover letter per JD from each bundled `..._Application_<job title>.txt` COVER LETTER section (DOCX in `source/` + PDF at root); `--label "<Role>"` renders just one. Detail in the resume-writer skill |
| `.agents/skills/resume-writer/scripts/pdf_convert.py` | Shared DOCX → PDF conversion (LibreOffice, docx2pdf fallback) used by both renderers |
| `.agents/skills/resume-writer/scripts/extract.py` | DOCX → YAML extraction utility (re-run when the master resume changes) |
| `.agents/skills/application-tracker/scripts/status.py` | Scan applications and manage status-folder metadata; `--enrich-metadata` safely inserts missing schema-v3 level/YOE/salary facts with the formatting-preserving editor, `--check-metadata` validates them (drafted by default), `--sync-log` refreshes logs, and `--check-locations` enforces location policy |
| `.agents/skills/application-tracker/scripts/backfill_job_metadata.py` | Dry-run-by-default fleet metadata preview/backfill; requires exact `jd_file` associations for multi-role records and uses checksum-guarded atomic writes only with `--write` |
| `.agents/skills/resume-writer/scripts/check.py` | Validate tailored.yaml + PDF (locked fields, real project titles/skills, bullet lengths, one page, each JD's cover letter); re-exports the filename stems + `application_roles()`/layout helpers. Detail in the resume-writer skill |
| `scripts/shared/config.py` | **Canonical** config loader — candidate identity, paths (including the company-level cache), output-filename stems, and location policy. Vendored into `job-search`, `resume-writer`, and `application-tracker` |
| `scripts/shared/layout.py` | **Canonical** pure application-folder layout helpers (no identity/config): `source/` rules, `slugify_label` / `compose_stem`, `application_roles()`, and `find_jd_files`. Vendored into `resume-writer` and `application-tracker` |
| `scripts/shared/location.py` | **Canonical** shared location classifier — turns a posting `location` string into a match (e.g. `metro` / `us_remote`) or no-match (`other_us` / `foreign` / `unknown`) per the configured location policy (ships with NO built-in metros; callers inject `config.location_policy()`); also extracts `Location:` lines from JD files. Vendored into `job-search`, `resume-writer`, and `application-tracker` (see "Sharing Code Across Skills") |
| `scripts/shared/job_metadata.py` | **Canonical** pure extractor/validator for the flat schema-v3 per-posting job level (normalized word + approximate Google-equivalent range), required YOE, salary, `workplace` (onsite/hybrid/remote), and heuristic `sponsorship` (likely/unlikely/unknown), plus loading of the optional sourced company-levels reference cache. Vendored into all three job workflow skills |
| `scripts/shared/metadata_editor.py` | **Canonical** formatting-preserving schema-v3 `meta.yaml` editor (YAML node anchors, checksums, atomic writes, semantic verification, idempotence). Vendored into application-tracker |
| `scripts/maintenance/import_company_levels.py` | Dry-run-by-default YAML/JSON/CSV importer for user-supplied or licensed company-level facts; never fetches/scrapes Levels.fyi and keeps base/stock/bonus/total plus geographic bands distinct |
| `scripts/vendoring/sync_vendored.py` | Vendoring tool: copies each canonical shared module into every consuming skill's `scripts/_vendor/` (registry in `TARGETS`); `--check` fails on drift (run by the pre-commit hook) |
| `hooks/pre-commit` | Tracked git pre-commit hook: runs the vendored-copy drift check + `compileall`. Install once: `python scripts/bootstrap_overlay.py` (installs pre-commit AND pre-push) |
| `.agents/skills/<skill>/scripts/_vendor/` | Generated byte-identical copies of vendored toolkit modules (e.g. `config.py`, `layout.py`, `location.py`, `job_metadata.py`, `metadata_editor.py`) — do not edit; regenerate via `scripts/vendoring/sync_vendored.py` |
| `.agents/skills/ask-me-anything/` | PUBLIC orientation guide: the five-step workflow, repo structure, and which skill + dependencies each step needs (read first when a user asks how the toolkit works or where to start) |
| `.agents/skills/job-search/` | PUBLIC skill for discovering and ranking matching job postings (role, keyword, location, recency, visa filters) |
| `.agents/skills/resume-writer/` | PUBLIC skill for resume tailoring |
| `.agents/skills/application-tracker/` | PUBLIC skill for application status and pipeline management |
| `.agents/skills/behavioral-interview-prep/` | PUBLIC skill for behavioral interview story banks and STAR answers |
| `.agents/skills/company-research/` | PUBLIC skill for researching a company + role for interviews (product, size, teams, values, stage, comp, WLB, ratings, visa) and drafting a hiring-manager/engineer question bank under `interviews/company-specific/<company>/company-info/` |
| `.claude/skills/`, `.cursor/skills/` | Tool-compatibility symlinks to `.agents/skills` (for agents that look in their own skill directories) |
| `.agents/MEMORY.md` | Cross-session hypotheses and learnings (gitignored) |
| `tmp/` | Gitignored scratch space for **all** disposable, ad-hoc work — one-off ATS/API probes, fetched web artifacts, sanity checks — organized into purpose-named subfolders (`tmp/ats_scripts/`, `tmp/web_artifacts/`, `tmp/scratch/`). Never committed; created on demand; nothing in the toolkit may depend on it. See "Scratch & Temporary Files" |
| `README.md` | Human-facing quickstart (capability-first: example output, then the workflow) |
| `docs/ARCHITECTURE.md` | Human-facing design doc: render pipeline, config system, vendoring, CI gates, repo reference |
| `AGENTS.md` | This file (agent-facing contract) |

## Handy Commands

Always use the repo venv: `.venv/bin/python` (needs Python 3.11+). PDF conversion uses
LibreOffice, which `.agents/skills/resume-writer/scripts/pdf_convert.py` finds via
`~/Applications`, `/Applications`, or `soffice` on `PATH` (override with the `JOBHUNT_SOFFICE`
env var).

```bash
# Render a tailored resume to DOCX (source/) + PDF (root) and validate it (format,
# locked fields, one page). Also renders one cover letter PER JD from each bundled
# ..._Application_<job title>.txt. Accepts the app folder or the source/tailored.yaml path.
.venv/bin/python .agents/skills/resume-writer/scripts/render.py applications/6_drafted/<slug>/

# Render only the cover letters (one per JD, from each bundled ..._Application_<job title>.txt)
.venv/bin/python .agents/skills/resume-writer/scripts/cover_letter.py applications/6_drafted/<slug>/
# Render just one role's cover letter:
.venv/bin/python .agents/skills/resume-writer/scripts/cover_letter.py applications/6_drafted/<slug>/ --label "Senior Platform Engineer"

# Validate without rendering
.venv/bin/python .agents/skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/

# Show all applications and their status (status = which folder each app lives in)
.venv/bin/python .agents/skills/application-tracker/scripts/status.py

# Populate/validate schema-v3 level, required YOE, salary + approximate Google-equiv from JD + cache.
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --enrich-metadata applications/6_drafted/<slug>/
# Fleet preview: dry-run, defaults to applications/6_drafted/ (strict schema v3). Add --all-statuses for the
# full fleet or --statuses <labels> for a set; add --write only after reviewing the dry-run preview.
.venv/bin/python .agents/skills/application-tracker/scripts/backfill_job_metadata.py
# Validate structured metadata — DRAFTED-ONLY by default; --all-statuses for the fleet.
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --check-metadata

# Import user-supplied/licensed company-level facts (YAML/JSON/CSV; dry-run by default)
.venv/bin/python scripts/maintenance/import_company_levels.py INPUT <company-levels.yaml>

# Regenerate applications-log.yaml (the postings job-search skips) from all folders
# and upsert company-search-log.yaml created entries
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --sync-log

# Record a successful company search with no application folder (no suitable role)
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --log-search "Example Corp" --outcome no_suitable
# Optional: --date YYYY-MM-DD

# Move an application into a different status folder
# (statuses: drafted | applied | in_progress | rejected | ignored)
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --update <slug> applied

# Extract content from a DOCX resume (utility)
.venv/bin/python .agents/skills/resume-writer/scripts/extract.py path/to/resume.docx

# Regenerate vendored copies after editing a canonical shared module
# (e.g. scripts/shared/config.py, layout.py, or location.py), then verify no copy has drifted
.venv/bin/python scripts/vendoring/sync_vendored.py
.venv/bin/python scripts/vendoring/sync_vendored.py --check

# Install the git hooks once (pre-commit drift check + compileall, and pre-push)
python scripts/bootstrap_overlay.py

# Install dependencies
pip install -r requirements.txt
```

## Guidance to AI Agent Tasks

### Read Order

1. Read this file first for repo-level orientation.
2. Read the relevant PUBLIC skill before starting work:
   - `.agents/skills/ask-me-anything/SKILL.md` when the user is new or asks how the toolkit works, where to start, the overall workflow/structure, or which dependencies a step needs
   - `.agents/skills/job-search/SKILL.md` for finding/filtering matching job postings
   - `.agents/skills/resume-writer/SKILL.md` for resume tailoring
   - `.agents/skills/application-tracker/SKILL.md` for status management
   - `.agents/skills/behavioral-interview-prep/SKILL.md` for behavioral interview prep
   - `.agents/skills/company-research/SKILL.md` for researching a company/role for interviews and building a question bank
   - (The private `coding-interview` skill, when the overlay is mounted, appears at `.agents/skills/coding-interview/` via the bootstrap symlink.)
3. Read `.agents/MEMORY.md` (if it exists) for cross-session context.
4. Read the candidate profile (`config.profile_md_path()`) before tailoring — this is the source of truth.

### Memory Map

Every place an agent reads context from or appends learnings to, by lifecycle **zone** (maintainer-only
design doc `private/docs/harness-engineering-and-repo-evolution/03-folder-structure-and-memory.md` §3 —
overlay-mounted, absent in contributor checkouts) with its
retention + writer. Promotion (MEMORY→LESSONS→SKILL) exists; **forgetting** (TTL/prune/demotion) is
enforced by the `gardener` (`.agents/skills/gardener/`, dry-run by default).

| Location | Zone | Retention | Who writes |
|----------|------|-----------|-----------|
| `AGENTS.md` | (b) harness | permanent, versioned | human + agent (PR) |
| `SKILL.md` / `reference.md` | (b) instructions | permanent, versioned; size-budgeted | human + agent (PR) |
| `LESSONS.md` | (c) durable memory | `last_confirmed` >180d → gardener flags demotion; universalized entries promote into SKILL.md (separate human commit) | agent proposes, human ratifies |
| `.agents/MEMORY.md` | (d) scratch (gitignored) | ephemeral; entries >14d promote to LESSONS or drop | agent |
| `<applications_root>/0_profile/applications-log.yaml` | (d) derived index | regenerable — never hand-edit; `status.py --sync-log` rebuilds it | `status.py` |
| `<applications_root>/0_profile/company-search-log.yaml` | (d) TTL state | read-side skip `skip_within_days: 7`; rows >90d pruned | `status.py` / gardener |
| `config.company_levels_path()` | (d) TTL cache | comp facts 365d (`last_verified`); level maps re-verified, not expired | agent / `import_company_levels.py` |
| `config.discoveries_dir()` `current/` + `archive/` | (d) working memory | 30d hard TTL; raw scans >14d → `archive/` (move, never delete) | job-search; gardener |
| `private/` overlay (real products; `examples/` is the public mirror) | (e)/(f) products | user-owned, kept; never auto-deleted | human (private) |

### Skill Compatibility

- `.agents/skills` is the canonical Agent Skills directory. Edit skill content there.
- `.claude/skills/<skill>` and `.cursor/skills/<skill>` are symlinks for tool compatibility. Do not edit through duplicated copies.
- Keep each skill folder named the same as the `name` field in `SKILL.md`; use lowercase letters, numbers, and hyphens.

### Sharing Code Across Skills (Vendoring)

Skills are **self-contained** (Approach 2). A skill's `scripts/` may import its own
sibling modules, but it **must never import repo-root toolkit Python** and must never
`sys.path`-inject a path outside its own skill folder. When a skill needs a pure
toolkit module, that module is **vendored** (copied) into the skill:

- **One canonical source per shared module** lives in `scripts/shared/` (today:
  `config.py`, `layout.py`, `location.py`, `job_metadata.py`, and
  `metadata_editor.py`). Edit the logic there — never in a copy.
- **Byte-identical copies** are generated into each consuming skill's
  `scripts/_vendor/` (e.g. `.agents/skills/resume-writer/scripts/_vendor/config.py`,
  `.agents/skills/job-search/scripts/_vendor/location.py`).
  Everything in `_vendor/` except `__init__.py`/`README.md` is generated — do not edit.
- The registry of `source -> [copies]` lives in `scripts/vendoring/sync_vendored.py`.
  After editing a canonical source, regenerate the copies:
  `.venv/bin/python scripts/vendoring/sync_vendored.py`.
- A drift check (`sync_vendored.py --check`) fails if any copy diverges from its
  source. It runs in the tracked `hooks/pre-commit` hook (install once with
  `python scripts/bootstrap_overlay.py`), so copies can never
  silently drift.
- Skill scripts import the vendored module locally, e.g.
  `from _vendor.location import classify_location`.

Where does a new shared module go? If **only one skill** needs it and it's
skill-specific, keep it in that skill's `scripts/`. If a skill needs a **pure toolkit
module**, add it to `scripts/vendoring/sync_vendored.py`'s `TARGETS`, run the sync, and
import the `_vendor/` copy. The self-contained skills (`resume-writer`,
`application-tracker`, `job-search`) vendor the shared modules they need; the repo-root
maintenance tooling (`scripts/maintenance/`, `scripts/vendoring/`) may import
`scripts/shared/` directly since it always runs inside this repo.

### File & Folder Organization

**Group files by purpose in a meaningful subfolder — never dump files into a broad,
generically named directory.** A bare `scripts/` (or `utils/`, `lib/`, `inputs/`,
`docs/`, `data/`, `misc/`) is too vague on its own: the folder name must announce what
its contents are *for*. Prefer a purpose-scoped subfolder such as
`scripts/shared/`, `scripts/vendoring/`, or `.agents/skills/<skill>/scripts/` over a
flat `scripts/`.

**Before creating ANY new file, reason about the whole folder tree** and place the file
where its purpose is obvious:

- **Think tree-first.** Ask "what is this file for, and which purpose-named folder
  already expresses that?" Put it there. If no such folder exists and the file belongs to
  a group, create the purpose-named subfolder first, then add the file.
- **Purpose over mechanism.** Name folders after the job they do (`shared`,
  `vendoring`, `company-info`, `oa-references`), not after a file type or a
  generic bucket (`scripts`, `docs`, `files`, `data`).
- **Generic top-level folders must fan out into purpose subfolders.** `scripts/` splits
  into `shared/`, `vendoring/`, and `maintenance/`; `docs/` fans out into `docs/design/`; each
  skill keeps its code under `.agents/skills/<skill>/scripts/`. Follow the same pattern
  for anything new that would otherwise land in a generic root.
- **Don't orphan single files at a generic root.** A lone reference PDF, asset, image, or
  note belongs in a named subfolder (e.g. an OA reference PDF goes in
  `.../coding/oa-references/`), not loose beside unrelated files.
- **Match the existing convention.** Folder names are lowercase with hyphens; reuse an
  established purpose folder instead of inventing a near-duplicate.
- **Surface conflicts, don't silently break the pattern.** If a file genuinely fits no
  existing purpose folder, propose the new subfolder name; if existing layout conflicts
  with this rule, flag it and propose a refactor rather than adding to the mess.

Skill-scoped code is an accepted exception: a skill may keep its implementation in its own
`.agents/skills/<skill>/scripts/` because the parent skill folder already names the purpose.

**Coding-interview files** (`interviews/company-specific/<company>/coding/`): a single-file
solution stays flat as `<problem>.py`; give a problem its **own** subfolder
`coding/<problem>/<problem>.py` only when it carries extra assets (question screenshots,
PDFs, input files). Do not hard-wrap code lines in these files — keep each line on one line
unless it exceeds 150 characters (see the `coding-interview` skill).

### Scratch & Temporary Files

Ad-hoc, throwaway work — one-off API/ATS probes, scraper snippets, fetched raw HTML/JSON,
sanity-check scripts, any disposable intermediate — MUST live under the single top-level
**`tmp/`** folder in **purpose-named subfolders**, never in the repo root or a tracked/product
folder (`applications/`, `scripts/`, `templates/`, `.agents/skills/`, `interviews/`). A hard rule
for every agent and skill; the old flat `tmp_*.py`-in-root habit is retired.

- **Location & lifecycle:** everything disposable lives under `tmp/<purpose>/`. The whole `tmp/`
  tree is gitignored — nothing in it is committed, and nothing in
  the committed toolkit may import from or depend on `tmp/`. Temp files are disposable: delete them
  once done; if a probe proves worth keeping, promote it into the proper skill's `scripts/`.
- **Purpose-named buckets** (the name must announce the contents' job): `tmp/ats_scripts/` (job-board/
  ATS API probes), `tmp/web_artifacts/` (fetched raw HTML/JSON/career-page snapshots), `tmp/scratch/`
  (quick sanity checks). Descriptive lowercase file names inside each; never a bare `tmp_*.py` in the
  root. Machine scratch (`--json-out`) may target the OS `/tmp`, but keep anything worth revisiting
  in a named `tmp/` bucket.

### Subagent Budget

When a single user request fans out into multiple applications or searches, launch **at most
8 subagents total** across the entire request, including later waves. Reuse or resume those
agents, or finish remaining work in the parent agent; never launch a ninth. This is a
repo-wide cap — the skills reference it rather than restating it.

### Guardrails

- **Never fabricate** experience, metrics, titles, or technologies not listed in the profile. Reframe and emphasize existing experience; do not invent new experience.
- **Traceability**: every bullet in `tailored.yaml` must map to real content the user actually did — documented in the candidate profile (`config.profile_md_path()`) or the supporting library (`interviews/behavioral-story-bank/`, answer bank, prior applications, notes). Rewording and pulling in real detail from those sources is encouraged; fabrication is forbidden.
- **Validation is mandatory**: `render.py` auto-runs `check.py` (the resume-writer skill's validator: locked identity/employer fields, real project titles and skills, bullet counts/lengths, one-page PDF). A FAILed render must be fixed, never shipped or bypassed with `--skip-checks`.
- **Anchored, not frozen**: start every `tailored.yaml` as a copy of the baseline (`config.baseline_path()`). Rephrasing experience bullets and adding real, traceable detail from the library to improve JD fit is allowed; it is still not a from-scratch rewrite, and locked fields, titles, and skill-list gating always hold.
- **Deep, tailored research**: the cover letter, why-fit, and past-experience sections of each `..._Application_<job title>.txt` must show genuine understanding of the company's product AND that specific JD. Research the company's product/mission before writing; reference concrete, real specifics (never generic flattery or invented product claims). **One cover letter per JD, tailored per posting — no shared/boilerplate letter across postings.**
- **Keyword density**: incorporate job description keywords naturally. Do not stuff. Readability matters — a human recruiter reads after ATS passes.
- **Skill lists**: the profile's Skills section defines Approved (generally include in most
  resumes, if not all), Weak (shown to users as **Weak or Selective**; include only when the
  JD specifically mentions it), and Never (never include in any resume, even when the JD
  mentions it). JD skills in none of the lists must be surfaced to the user for categorization
  at the end of a tailoring run, never added silently.
- **Honesty over optimization**: if the user's experience is a poor match for a role, say so clearly.
- **Profile is user-owned**: ask before modifying the candidate profile (`config.profile_md_path()`).
- **Eval-gated harness edits**: any change to a skill's `SKILL.md`/`LESSONS.md`/`reference.md` must pass that skill's canaries (`evals/<skill>/canaries.yaml`) before merge, with no large efficiency regression vs baseline; record runs per `evals/README.md` (model-pinned; re-baseline on model upgrades). Harness self-edits are delta-only — never full-file rewrites, and consolidation never deletes a domain edge case.

### Application Folder Convention

Each application is a folder named `<company>-<role>-<YYYYMMDD>/`. **Status is the
parent status folder**, and applications are always created under
`applications/6_drafted/<company>-<role>-<YYYYMMDD>/`. The status folders and what they mean:

| Folder | Status | Who moves it |
|--------|--------|--------------|
| `applications/6_drafted/` | tailored, awaiting the user's review/decision | created here by the resume-writer skill |
| `applications/5_applied/` | submitted | the **user** moves the folder here manually |
| `applications/4_in_progress/` | heard back / interviews scheduled | the **user** moves the folder here manually |
| `applications/3_rejected/` | rejected at any stage | the **user** moves the folder here manually |
| `applications/2_ignored/` | decided not to submit; don't reconsider | the **user** moves the folder here manually |

**Numeric-prefix convention.** Every folder under `applications/` carries a `0_`–`6_`
prefix (`0_profile`, `1_discoveries`, `2_ignored`, `3_rejected`, `4_in_progress`,
`5_applied`, `6_drafted`) so a plain directory listing sorts into pipeline order. The
prefix is part of the on-disk folder name only — the CLI status **labels** stay
unprefixed (`drafted`, `applied`, `in_progress`, `rejected`, `ignored`): the summary table
and `status.py --update <slug> <status>` still take the bare label, and `status.py` maps
each label to its numbered folder (`applied` → `applications/5_applied`, etc.). Do not
rename these folders back to unprefixed names.

Agents should create applications under `applications/6_drafted/` and never move them
between status folders unless the user explicitly asks (they manage moves manually, or
via `.agents/skills/application-tracker/scripts/status.py --update <slug> <status>`).

Each application folder splits into a small set of **root** files (the finished
deliverables you submit / paste, plus tracking metadata) and a **`source/`**
subfolder (everything used to generate them):

One resume covers the whole folder, but **cover letters are one-to-one with JDs** — one
`<COVER_STEM>_<job title>.pdf` + one bundled `<APPLICATION_STEM>_<job title>.txt` per
`meta.yaml` role. A single-role folder has exactly one of each (still job-title-labeled); a
multi-role folder (a `jobs:` list) has one per posting. The stems below come from
`config.resume_stem()` / `config.cover_stem()` / `config.application_stem()` — with the
example config the resume stem is `Jordan_Rivers_Software_Engineer_Resume`:

```
applications/6_drafted/<slug>/                     # e.g. a 2-role folder
├── meta.yaml                                    # tracking metadata (status = the folder)
├── <RESUME_STEM>.pdf                            # ONE final resume (for humans/email)
├── <COVER_STEM>_<Role_A>.pdf                    # one cover letter per JD
├── <COVER_STEM>_<Role_B>.pdf
├── <APPLICATION_STEM>_<Role_A>.txt              # one bundled packet per JD
├── <APPLICATION_STEM>_<Role_B>.txt
├── notes.md                                     # optional interview/company notes
└── source/
    ├── JD-<job title A>.md                       # one per posting, ALWAYS JD-prefixed
    ├── JD-<job title B>.md
    ├── tailored.yaml                             # AI-tailored resume content (one resume)
    ├── <RESUME_STEM>.docx                        # submit this DOCX to ATS portals
    ├── <COVER_STEM>_<Role_A>.docx
    └── <COVER_STEM>_<Role_B>.docx
```

The `<Role>` suffix is the role's slug (underscores, via `layout.slugify_label`, e.g.
`Senior_Platform_Engineer`), derived one-to-one from each `meta.yaml` role. `render.py` /
`cover_letter.py` emit these names automatically — never hand-name or hand-place them.

Root files:
- `meta.yaml` — human-readable tracking metadata. Top-level `job_metadata_schema_version: 3`
 plus company-scope fields and a uniform **`jobs:` list — one entry per posting, always a list
 even for a single role** (each entry carries `role`, its exact `jd_file`, `location`,
 `workplace`, `sponsorship`, and the flat `job_level`/`required_yoe`/`salary_range` facts; no
 `total_compensation_range`). **The `application-tracker` skill (`.agents/skills/application-tracker/SKILL.md`,
 "`meta.yaml` Schema") is the single canonical owner of the full schema and rules** — read it
 before writing or validating a `meta.yaml`; don't restate the field list elsewhere. Run
 `status.py --enrich-metadata <folder>` after saving the JD. The folder, not a field, is the
 status, and the role list is the canonical set of cover letters. Only create an application
 whose `location` matches the configured location policy (`config.location_policy()` — the
 candidate's preferred metros plus US-remote / `us_only` rule) — verify with
 `.agents/skills/application-tracker/scripts/status.py --check-locations`; a role that is
 on-site/hybrid outside the allowed metros or non-US must not be drafted.
- `..._Resume.pdf` — the single final resume PDF (generated, committed)
- `..._Cover_Letter_<job title>.pdf` — one final cover-letter PDF per JD (generated, committed)
- `..._Application_<job title>.txt` — one plain-text packet per JD, each bundling three
  copy-paste sections introduced by a title + `===` underline: **COVER LETTER**, **WHY THIS
  COMPANY & ROLE**, and **PAST EXPERIENCE**. Plain English, no Markdown/bold — paste straight
  into that posting's portal boxes. Each `.txt` is the source of truth for its cover letter:
  `render.py` renders `..._Cover_Letter_<job title>.pdf` from its COVER LETTER section (name +
  contact, then the salutation — no job-title/subject line). Every letter is researched and
  tailored to its own JD — never reuse one letter across postings.
- `notes.md` — optional interview notes and company research

`source/` files (generation inputs/intermediates):
- `JD-<job title>.md` — full job-description text, one file per posting, **always**
  `JD-`-prefixed and slug-named after the job title (single or multiple postings).
  `check.py` reads and concatenates every `JD-*.md` in `source/` (via `layout.find_jd_files`).
- `tailored.yaml` — AI-tailored content matching the render schema (one resume per folder);
  may set an optional top-level `target_position` to add a role suffix to the RESUME
  filename (divergent-split only)
- `..._Resume.docx` — the editable resume DOCX (submit this to ATS portals)
- `..._Cover_Letter_<job title>.docx` — one editable cover-letter DOCX per JD

When one company's roles are too different for a single honest resume, they are split into
separate application folders and each `tailored.yaml` sets `target_position`, so the RESUME
filename carries a role suffix (e.g. `..._Resume_Frontend_Engineer.pdf`); the cover letter
and bundled `.txt` are always job-title-labeled per JD regardless of the split.

Slug format: lowercase, hyphens, no special characters. Example: `google-ml-engineer-20260416`.

### Doc Ownership

- `README.md` is human-facing. Do not add agent instructions to it.
- `AGENTS.md` is agent-facing. Do not add human usage guides to it.
- The candidate profile (`config.profile_md_path()`) is user-owned. Ask before modifying.
