# Architecture

How the toolkit works under the hood. For the quickstart, read
[`README.md`](../README.md); for the agent-facing contract (guardrails, folder
conventions, memory zones), read [`AGENTS.md`](../AGENTS.md).

## The rendering pipeline: content and formatting are separate concerns

Your full professional profile lives in markdown (the file `config.profile_md_path()`
points at). For each job application, the AI tailors the *content* and writes it as
structured YAML; a script then renders that YAML into a DOCX by copying your approved
**reference resume** and swapping in the tailored text — so every render preserves your
fonts, margins, and layout exactly. The DOCX is converted to PDF and validated.

```
candidate profile (markdown) + job description
    → AI analyzes gaps, selects projects, tailors content
    → source/tailored.yaml                      (structured content)
    → render.py fills the reference DOCX        (format-preserving)
    → resume DOCX (source/) + PDF (root)
      + one cover letter per posting + bundled Application .txt
    → check.py validation                       (automatic, mandatory)
```

Validation (`skills/resume-writer/scripts/check.py`) enforces locked identity
fields, real project titles and skills, bullet counts/lengths, a one-page PDF, and a
proper cover letter per posting. Resume YAML canonically uses an ordered `employers:`
list; each job may carry conventional direct achievement bullets, named project blocks,
or both. The singular `employer:` form remains backward compatible. A failed render is
fixed, never shipped.

`extract.py` can bootstrap that YAML from standard single-column, paragraph-based DOCX
resumes, including native Word bullets and repeated employer/promotion entries. It fails
closed with diagnostics for tables/two-column layouts, text boxes, image-only documents,
corrupt packages, and ambiguous experience headers; those layouts require manual cleanup
instead of a silently incomplete work history.

## Configuration

Candidate identity, paths, and output filename stems are never hardcoded — they come
from a git-ignored `config.yaml`, loaded by `automation/shared/config.py` (vendored into
each skill). Discovery order: `$JOBHUNT_CONFIG` → the nearest `config.yaml` walking up
from the current directory → the tracked `config.example.yaml` (the fictional
**"Jordan Rivers"** placeholder), so every tool runs out of the box with the example
data. Paths in the config resolve relative to the config file's directory.

What the config supplies:

| Key | What it points at |
|-----|-------------------|
| `candidate.*` | Name, contact line, and the `name_slug`/`title_slug` that build output filenames (`Jordan_Rivers_Software_Engineer_Resume` in the example) |
| `paths.profile_md` | Your complete professional profile — the source of truth for all tailoring |
| `paths.baseline_yaml` | Canonical YAML transcription of your approved resume — every tailored resume starts as a copy of it |
| `paths.reference_docx` | Your formatted resume DOCX — the format-preserving render template |
| `paths.company_levels_yaml` | Optional reusable company level/YOE/compensation cache (its own schema-v2 file format, separate from application `meta.yaml`) |
| `paths.applications_root` | Where the application pipeline folders live |
| `paths.discoveries_dir` | Where job-search shortlists land |
| `job_search.default_profile` | Which `skills/job-search/profiles/<label>.yaml` search profile to use |
| `outlook_email.*` | Private personal-mailbox address, Microsoft public-client application ID, and `consumers` tenant selection; OAuth refresh state lives only in the OS keyring |
| `location_policy` | Allowed metros + US-remote/us-only rules that gate application creation |

## Application folders: per-job status, folder = derived rollup

Every application is a folder `<company>-<role>-<YYYYMMDD>/` inside a numbered status
folder under the applications root:

```
applications/
├── 0_profile/        # profile support files + search skip-logs (not an application)
├── 1_discoveries/    # job-search shortlists (not an application)
├── 2_ignored/        # decided not to submit
├── 3_rejected/       # rejected at any stage
├── 4_in_progress/    # heard back / interviewing
├── 5_applied/        # submitted
└── 6_drafted/        # generated applications land here for your review
```

The numeric prefixes make a plain directory listing sort into pipeline order. Each `jobs:`
entry in `meta.yaml` carries its own `status`; the folder is the **derived overall status** —
the per-job statuses rolled up by precedence (`in_progress > applied > drafted > rejected >
ignored`), and the two must agree. `status.py --update <slug> <status>` (whole application) and
`--update-job <slug> <role-match> <status>` (one posting) write the per-job field(s) and move the
folder to match; moving a folder by hand needs a re-sync via `--update`.

Inside each application folder, deliverables sit at the root (final resume PDF, one
cover-letter PDF and one bundled copy-paste `..._Application_<role>.txt` per posting,
`meta.yaml`) and generation inputs live in `source/` (JD files, `tailored.yaml`,
DOCX files). `AGENTS.md` → "Application Folder Convention" is the canonical spec.

`meta.yaml` carries per-posting facts (a required `status`, a structured `progress`
summary, level, required YOE, salary,
workplace, sponsorship) under a `jobs:` list — schema v5, the only supported application schema.
The `application-tracker` skill owns the schema; its scripts insert and validate the
facts with a formatting-preserving, checksum-guarded editor, and are the sole
transactional writer of the single `calendar.md` resolved by `config.calendar_path()`.

## Self-contained skills (vendoring)

Each skill under `skills/<skill>/` bundles its own `scripts/` plus a
`scripts/_vendor/` copy of the shared modules it needs (`config.py`, `layout.py`,
`location.py`, `job_metadata.py`, `metadata_editor.py`). A skill never imports
repo-root Python, so a single skill folder can be dropped into another project and
keeps working.

The canonical sources live in `automation/shared/`; `automation/vendoring/sync_vendored.py`
regenerates the byte-identical `_vendor/` copies, and its `--check` mode (run by the
pre-commit hook and CI) fails on any drift. Edit the canonical source, never a copy.
(This is "Approach 2" of the historical design exploration in
`docs/design/skill-script-sharing/`.)

Skills are discovered by listing `skills/` — any AI agent that reads
`AGENTS.md` finds them there. `.claude/skills/` and `.cursor/skills/` are
compatibility symlinks for tools that look in their own skill directories, and
`.claude-plugin/marketplace.json` publishes the public skills as a Claude Code plugin
marketplace.

## Public / private split

This repo is the PUBLIC toolkit: tooling, the eight public skills, an identity-only
company registry, and the fictional Jordan Rivers dataset under `examples/`. Everything
tied to a real person mounts under the git-ignored `private/` overlay (its own git
repo) and is pointed at by the git-ignored `config.yaml`. Three defenses keep the
public tree clean:

1. **`.gitignore`** anchors every private path (`private/`, `config.yaml`,
   `/applications/`, `/interviews/`, per-skill `references_private/`, …).
2. **The leak guard** (`automation/publish/check_public.py`) scans tracked files — paths,
   text, and `.docx`/`.pdf` content — for private trees, structural PII, and
   personal-identity tokens derived at runtime from your config and
   `private/leak_tokens.txt` (nothing hardcoded). It runs blocking in CI, in the
   pre-push hook, and by hand.
3. **The exporter** (`automation/publish/export_public.py`) can produce a sanitized copy
   of any checkout; the leak-guard test suite drives it end-to-end.

Full walkthrough: [`PRIVATE_OVERLAY.md`](PRIVATE_OVERLAY.md).

## Continuous integration

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs on every push and
pull request:

1. **Vendored-copy drift check** — `sync_vendored.py --check`.
2. **Compile** — byte-compiles all toolkit and skill Python.
3. **Example renders + validate** — renders the legacy worked example under
   `examples/applications/6_drafted/` and a public multi-experience fixture with fake
   configs, including one-page PDF checks (LibreOffice is installed in CI).
4. **Resume-writer unit tests** — schema normalization, extraction diagnostics,
   multi-employer rendering/layout, and an isolated `_test_application_` workflow.
5. **Shared-module unit tests** — `automation/shared/tests` (job metadata, the
   formatting-preserving editor, layout, search/backfill).
6. **Leak-guard + exporter unit tests** — `automation/publish/tests`.
7. **Public leak guard** — blocking; zero findings is the steady state.

A separate `secret-scan` job runs gitleaks over the full history for credential
shapes the identity guard does not target.

Local equivalents of all gates are listed in
[`CONTRIBUTING.md`](../CONTRIBUTING.md) → "Running the checks"; the tracked git hooks
(installed by `python automation/bootstrap_overlay.py`) run the cheap ones on commit and
the leak guard on push.

## Repo reference

| Path | Purpose |
|------|---------|
| `config.example.yaml` (tracked) / `config.yaml` (git-ignored) | Candidate identity, paths, filename stems; the example doubles as the no-config fallback |
| `examples/` | The fictional "Jordan Rivers" dataset: profile, baseline, reference DOCX, a worked drafted application, screenshots, and the public resume/JD fixture matrix under `examples/fixtures/resume-writer/` |
| `skills/<skill>/` | The skills — `SKILL.md` instructions + self-contained `scripts/` + `_vendor/` copies |
| `skills/job-search/companies.yaml` | Canonical company registry: identity, ATS poll config, tags, blacklist — never dated postings |
| `automation/shared/` | Canonical shared modules, vendored into skills |
| `automation/vendoring/` | `sync_vendored.py` — regenerates `_vendor/` copies, checks drift |
| `automation/maintenance/` | The `gardener/` memory-hygiene routines and file-only `import_company_levels.py` |
| `automation/metrics/` | Opt-in local metrics hooks + the instruction-file size budget (`instruction_budget.py --strict`) |
| `automation/publish/` | Leak guard + exporter (the repo's privacy defenses) |
| `evals/` | Per-skill canary evals gating skill-instruction changes (see `evals/README.md`) |
| `hooks/` | Tracked git hooks: pre-commit (drift + compile + budget), pre-push (leak guard) |
| `AGENTS.md` | The agent-facing contract: guardrails, conventions, memory map |
| `docs/` | Human-facing design docs (this file, `PRIVATE_OVERLAY.md`, `METRICS.md`, historical `design/`) |
