# Jobs Finder — job-hunting toolkit

The **public** `jobs-finder-toolkit` repository, licensed **Apache-2.0**.
A minimal toolkit for ATS-optimized resume generation, job discovery,
and application tracking, driven by AI agents. The skills live in `.agents/skills/` and work
from Claude Code, Cursor, or Codex. It ships timeless tooling plus a fictional "Jordan Rivers"
example candidate under `examples/`; your real data stays in a separate private overlay (see
"Bring your own data"). Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## How It Works

**Content and formatting are separate concerns.** Your full professional profile lives in markdown (your candidate profile (`config.profile_md_path()`)). For each job application, the AI tailors the content and generates structured YAML. A script renders the YAML into a DOCX resume by copying your approved reference resume and swapping in the tailored content (preserving all formatting), then converts to PDF and validates it.

```
your candidate profile (config.profile_md_path()) + job description
    → AI analyzes gaps, selects projects, tailors content
    → source/tailored.yaml (structured)
    → render.py fills the reference DOCX (config.reference_docx_path(), format-preserving)
    → resume DOCX (source/) + PDF (root) + cover letter + automatic validation (.agents/skills/resume-writer/scripts/check.py)
```

Each application folder keeps only the finished PDFs, a bundled copy-paste `..._Application.txt`,
and `meta.yaml` at its root; the generation inputs (JD files, `tailored.yaml`, DOCX) live in a
`source/` subfolder.

## Configuration

Candidate identity, paths, and output filename stems are never hardcoded — they come from
`config.yaml` (git-ignored). Copy `config.example.yaml` to `config.yaml` and edit it with your
own values:

```bash
cp config.example.yaml config.yaml
```

`config.example.yaml` is a neutral **"Jordan Rivers"** placeholder that also serves as the
fallback when no `config.yaml` is found. It supplies the profile path (`config.profile_md_path()`),
the baseline (`config.baseline_path()`), the render reference DOCX
(`config.reference_docx_path()`), the reusable company leveling/compensation cache
(`config.company_levels_path()`), and the output filename stems
(`<RESUME_STEM>` = `Jordan_Rivers_Software_Engineer_Resume` in the example). Paths in the config
are resolved relative to the config file's directory.

## Quickstart

### 1. Clone and install dependencies

```bash
git clone https://github.com/<owner>/jobs-finder-toolkit.git   # or your fork
cd jobs-finder-toolkit
python3 -m venv .venv        # needs Python 3.11+ — check `python3 --version` first
.venv/bin/pip install -r requirements.txt
```

> **Python 3.11+ required.** On macOS, bare `python3` can still resolve to an
> ancient interpreter (3.7-era) where the install fails — if so, create the venv
> with a modern one instead, e.g. `python3.13 -m venv .venv` or
> `uv venv --python 3.13`.

No `config.yaml` is needed to try the toolkit: with none present, every tool falls back to the
fictional `config.example.yaml` and the `examples/` **Jordan Rivers** fixture, so you can run
any skill against the example candidate right away.

For PDF conversion, install one of:
- **LibreOffice** (recommended): `brew install --cask libreoffice`
- **Microsoft Word** (if already installed): `.venv/bin/pip install docx2pdf`

Optional (recommended for contributors): wire the tracked git hooks (vendored-copy drift check
+ byte-compile) with the idempotent, stdlib-only bootstrap script:

```bash
python scripts/bootstrap_overlay.py
```

### 2. Review your profile

Your professional profile is at your candidate profile (`config.profile_md_path()`). It contains all your experience (tagged `[draft]` or `[backup]`), skills, and resume writing preferences. Update it as your experience grows.

### 3. Tailor a resume for a job

In Cursor, tell the AI:

> Tailor my resume for this job: [paste the job description]

The `resume-writer` skill handles the rest: reads your profile, analyzes keyword gaps, selects the best projects, tailors content, and renders DOCX + PDF. By default it also drafts a matching cover letter PDF and a single bundled `..._Application.txt` — a copy-paste-friendly file with three plain-text sections (cover letter, "why this company / role", and "past experience") that you paste straight into portal boxes — say "resume only" to skip them. Cover-letter, why-fit, and past-experience content are researched against the company's product and the specific job description. When one company posts several jobs, it produces one resume covering them all unless the roles are very different, in which case it splits them into separate applications with position-labeled filenames.

### 4. Check application status

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py
```

Prints a summary table of all applications with status, source, and next actions.

Schema-v3 per-posting job metadata (workplace, visa sponsorship, job level, required
YOE, and base salary — an application's `meta.yaml` has **no** `total_compensation_range`)
lives under a `jobs:` list, one entry per posting, and can be inserted safely after
saving the JD:

```bash
# One application: formatting-preserving, checksum-guarded write
.venv/bin/python .agents/skills/application-tracker/scripts/status.py \
  --enrich-metadata applications/6_drafted/<slug>/

# Drafted-folder preview: dry-run unless --write is added after review
.venv/bin/python .agents/skills/application-tracker/scripts/backfill_job_metadata.py
```

Validation and backfill default to the `applications/6_drafted/` folder only, where
drafts must be strict schema-v3 (`job_metadata_schema_version: 3`); pass `--all-statuses`
to include the archived status folders, whose older applications may remain at schema v2
without blocking resume renders. (Unrelated: the reusable company leveling/compensation
cache — `company-levels.yaml` — is a separate file that legitimately stays at schema v2,
`total_compensation_range` included.)

Company benchmarks import from user-supplied YAML/JSON/CSV only:
`.venv/bin/python scripts/maintenance/import_company_levels.py INPUT DESTINATION`.
It is dry-run by default. Public Levels.fyi scraping is never used; automated Levels.fyi
inputs require a user-supplied licensed export or licensed API access.
An application's **status is the folder it lives in** (there is no `status` field in
`meta.yaml`) — newly generated applications start in `applications/6_drafted/`, and you move
each folder into `applications/5_applied/`, `applications/4_in_progress/`,
`applications/3_rejected/`, or `applications/2_ignored/` as things progress.

### 5. Update status

Move the application folder into the target status folder — either by hand, or with
(`<status>` is one of `drafted | applied | in_progress | rejected | ignored`):

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --update google-ml-engineer-20260416 applied
```

## Install as skills / Claude plugin

Every skill under `.agents/skills/<skill>/` is **self-contained**: it bundles its own
`scripts/` plus a `scripts/_vendor/` copy of the shared toolkit modules (`config.py`,
`layout.py`, `location.py`, `job_metadata.py`). A skill never imports repo-root Python, so you can drop a single
skill folder into another project and it keeps working — just copy the whole
`.agents/skills/<skill>/` directory (its `scripts/` and `_vendor/` come along) and provide a
`config.yaml` (or set `JOBHUNT_CONFIG`; it falls back to `config.example.yaml`).

The public skills are also published as a **Claude Code plugin marketplace** via
[`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json). Each entry points at its
`.agents/skills/<skill>/` folder:

- `ask-me-anything` — orientation guide: the five-step workflow, repo structure, and the skill + dependencies each step needs (start here if you're new)
- `job-search` — discover and rank fresh job postings that match a candidate profile
- `resume-writer` — tailor resumes for ATS optimization and render DOCX + PDF + cover letters
- `application-tracker` — track applications, statuses, and pipeline health
- `behavioral-interview-prep` — build project-based behavioral story banks and STAR answers
- `company-research` — deep company + role research and an interview question bank

The private `coding-interview` skill is intentionally **not** in the marketplace — it ships only
in the private overlay (see below).

## Continuous integration

CI lives in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) and runs on every push and
pull request. It:

1. **Drift check** — verifies each skill's vendored `_vendor/` copies are byte-identical to their
   canonical `scripts/shared/` source (`sync_vendored.py --check`).
2. **Compile** — byte-compiles all toolkit and skill Python (`compileall`).
3. **Example render + validate** — renders and validates the worked example under
   `examples/applications/6_drafted/` using the fake `config.example.yaml`.
4. **Leak guard** — runs `scripts/publish/check_public.py`, a **blocking** gate. This is the
   public repo, so the guard must be **completely clean** (exit 0, zero findings); any finding is
   a regression. It prevents leaking personal data or private skills.

## Public + private (two-repo) setup

This repository is the **PUBLIC toolkit** — it ships only timeless, general material: the
tooling (`scripts/`, the public skills and their scripts), the company registry
`.agents/skills/job-search/companies.yaml` (**identity only** — never specific or dated
postings), a fake example candidate under `examples/`, `config.example.yaml`, and general
instructions. It contains no real identity or products.

Everything tied to a real person or an active job hunt lives in a separate **PRIVATE overlay
repo** — its **own git repo**, synced to a private GitHub remote, cloned into a git-ignored
**`private/`** path inside this checkout (`personal/` is a legacy alias). Your `config.yaml`
(git-ignored) points the toolkit's `paths.*` into the overlay — its real profile, baseline,
reference DOCX, and applications:

- The private `coding-interview` skill (SKILL.md + its products) lives only in the overlay and
  never ships in the public repo.
- All real products — `applications/**`, the real `interviews/**`, the real
  company-level cache, and your real profile / baseline / reference DOCX — belong in the
  private overlay. Exported public checkouts git-ignore these paths, and the public exporter
  excludes them; only fake `examples/**` counterparts are published.
- The overlay also ships the git-ignored `.cursor/rules/private-skills.mdc` that registers the
  `coding-interview` skill, so it's discoverable only when the overlay is mounted.

### Bring your own data

To point the toolkit at your real profile and applications:

1. Copy the example config and edit its `paths.*` to point at your own files:
   `cp config.example.yaml config.yaml`. `config.yaml` is git-ignored, so your identity is never
   committed. Paths resolve relative to the config file's directory.
2. (Optional) Keep your real data in a **separate private repo** mounted at the git-ignored
   `private/` path (`git clone <you>/<your-private-overlay> private`, or symlink it there), then
   point `paths.*` at `private/…`.
3. Wire the overlay symlinks + git hooks idempotently:
   `python scripts/bootstrap_overlay.py`.

Full walkthrough — overlay layout, config keys, and the leak guard — is in
[docs/PRIVATE_OVERLAY.md](docs/PRIVATE_OVERLAY.md).

## Folder Structure

| Path | Purpose |
|------|---------|
| `config.yaml` (git-ignored) / `config.example.yaml` (tracked) | Candidate identity, paths, and output-filename stems; the tracked example is the neutral "Jordan Rivers" placeholder + fallback |
| your candidate profile (`config.profile_md_path()`) | Your complete professional profile (source of truth); the public example is `examples/profile/profile.example.md` |
| `config.baseline_path()` | Canonical transcription of your approved resume |
| `config.company_levels_path()` | Schema-v2 sourced company level/YOE/base/stock/bonus/total-compensation cache; compensation ages per fact and keeps geographic bands separate; the public example is fictional |
| `.agents/skills/job-search/companies.yaml` | Canonical company registry — identity, ATS poll config, tags, and the blacklist (employers to never consider); never carries specific or dated postings |
| `<profile-dir>/applications-log.yaml` | Auto-generated log of postings already considered (job-search skips them) |
| `<profile-dir>/resumes/` | Your approved master resume file(s) |
| `config.discoveries_dir()` | Ad-hoc research findings during the job search |
| `applications/6_drafted/<slug>/` | Generated applications land here first, for your review (finished files at root, inputs in `source/`) |
| `applications/5_applied/<slug>/` | Applications you've submitted |
| `applications/4_in_progress/<slug>/` | Heard back / interviewing |
| `applications/3_rejected/<slug>/` | Rejected at any stage |
| `applications/2_ignored/<slug>/` | Decided not to submit |
| `config.reference_docx_path()` (git-ignored; example `examples/templates/reference.example.docx`) | Your approved resume DOCX — the format-preserving render reference |
| `scripts/shared/` | Canonical cross-cutting helpers (`config.py`, `layout.py`, `location.py`, `job_metadata.py`, `metadata_editor.py`) vendored into skills |
| `scripts/vendoring/` | Keeps skills self-contained: `sync_vendored.py` copies canonical shared modules into each skill's `_vendor/` and checks for drift |
| `scripts/maintenance/` | Maintenance tooling (`migrate_layout.py`, file-only `import_company_levels.py`) |
| `.agents/skills/<skill>/scripts/` | Each skill bundles its own scripts (e.g. resume-writer's `render.py`, `cover_letter.py`, `check.py`; application-tracker's `status.py`, `backfill_location.py`, `backfill_job_metadata.py`) |
| `hooks/pre-commit` | Git pre-commit hook (drift check + compile); install with `ln -sf ../../hooks/pre-commit .git/hooks/pre-commit` |
| `.agents/skills/ask-me-anything/` | PUBLIC orientation guide: the five-step workflow, repo structure, and per-step dependencies (start here) |
| `.agents/skills/job-search/` | PUBLIC skill for discovering and ranking matching job postings |
| `.agents/skills/resume-writer/` | PUBLIC skill for resume tailoring |
| `.agents/skills/application-tracker/` | PUBLIC skill for status and pipeline management |
| `.agents/skills/behavioral-interview-prep/` | PUBLIC skill for behavioral interview story banks and STAR answers |
| `.agents/skills/company-research/` | PUBLIC skill for researching a company + role for interviews |

The private `coding-interview` skill is not part of this public repo — it is an overlay-only
skill shipped by the private overlay and is never published here.

## Privacy

- This repository is the **PUBLIC toolkit** — it ships only the tooling, the company registry
  (identity only, no specific jobs), fake `examples/**`, and general instructions
- Personal data belongs under the `private/` overlay (`personal/` is a legacy alias) or other
  private product paths. Exported public checkouts git-ignore these paths, and the exporter
  removes real `applications/**`, `interviews/**`, company-level research, and profile /
  baseline / reference DOCX content
- `config.yaml` is git-ignored (your real identity, paths, and filename stems); only
  `config.example.yaml` is tracked
- `.cursor/MEMORY.md` is gitignored (personal cross-session notes)
- `.DS_Store` and other OS/editor junk remain gitignored
