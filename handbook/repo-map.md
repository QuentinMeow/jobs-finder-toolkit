# Repo Map (full directory table)

Expands `AGENTS.md` → "Repo Map". All job-search content (the candidate's
profile materials, research findings, and every application) lives under the
applications root (`config.applications_root()`, `applications/` by default,
real data under `private/applications/`); only shared tooling (`scripts/`,
`skills/`) sits at the repo root. Files are grouped by purpose into
meaningful subfolders (see `handbook/file-organization.md`): `scripts/` fans
out into `automation/shared/`, `automation/vendoring/`, and `automation/maintenance/`
(each skill bundles its own render/tracking scripts under
`skills/<skill>/scripts/`). Application status is encoded per posting
in each `jobs:` entry's `status`, and the sub-folder the application sits in
is the derived overall status (rollup); the profile-support directory
(`<profile-dir>` = `config.applications_root()/0_profile/` — where the
skip-logs and the tailoring card ALWAYS live, regardless of where
`config.profile_md_path()` points; in the shipped example the profile file
lives under `examples/profile/`, but this logs dir is
`examples/applications/0_profile/`) and `config.discoveries_dir()` are
support folders, not applications.

| Path | Purpose |
|------|---------|
| `config.yaml` (git-ignored) / `config.example.yaml` (tracked) | Candidate identity, paths, and output-stem config; the tracked example is the neutral "Jordan Rivers" placeholder + fallback (see `handbook/configuration.md`) |
| `config.profile_md_path()` (example: `examples/profile/profile.example.md`) | Comprehensive candidate profile: all experience, skills, and resume writing preferences |
| `config.baseline_path()` | Canonical transcription of the approved resume — starting point for every tailored.yaml and the reference for locked-field validation |
| `skills/job-search/companies.yaml` | Canonical company registry — public, single source of truth for company **identity**, ATS poll config, and tags. Ships NO personal skip rules; candidate-specific blacklist rows (companies that don't sponsor, the candidate's own employer) live in a git-ignored overlay `private/job-search/blacklist.yaml` merged at load time by `registry.py` (each row: identity-only + `blacklist:` reason, no `ats`/`token`). Never carries specific or dated postings |
| `<applications_root>/0_profile/applications-log.yaml` | Auto-generated (via `status.py --sync-log`) list of postings already generated/considered — job-search skips them (new roles at the same company still surface) |
| `<applications_root>/0_profile/company-search-log.yaml` | Last successful full-company search per employer — job-search skips within 7 days (`skip_within_days`); upserted by `--sync-log` (`created`) or `--log-search` (`no_suitable`) |
| `config.company_levels_path()` | Reusable, sourced company level/YOE/base-salary/total-compensation mappings used as a fallback when a live JD omits those facts; real dated research defaults beside the private profile, while the public toolkit ships only `examples/profile/company-levels.example.yaml` |
| `<profile-dir>/resumes/` | The candidate's approved master resume file(s) |
| `config.discoveries_dir()` | Ad-hoc research findings during the job search (job-search output, target-company lists) |
| `config.applications_root()/6_drafted/<slug>/` | Generated applications land here first — for the user to review the resume + JD and decide the next move |
| `config.applications_root()/5_applied/<slug>/` | Applications the user has submitted (user moves the folder here manually) |
| `config.applications_root()/4_in_progress/<slug>/` | Heard back / interviews scheduled — active pipeline (user moves here manually) |
| `config.applications_root()/3_rejected/<slug>/` | Rejected at any stage (user moves here manually) |
| `config.applications_root()/2_ignored/<slug>/` | Decided not to submit; don't reconsider this posting (user moves here manually) |
| `config.reference_docx_path()` (default `examples/templates/reference.example.docx`; real DOCX under `private/`) | Formatted resume DOCX — the rendering reference (preserves all formatting) |
| `skills/resume-writer/scripts/render.py` | Fill the DOCX template from `source/tailored.yaml` → resume DOCX (`source/`) + PDF (root, stem from `config.resume_stem()`) + **one cover letter per JD**; auto-runs `check.py`. Detail in the resume-writer skill |
| `skills/resume-writer/scripts/cover_letter.py` | Render one cover letter per JD from each bundled `..._Application_<job title>.txt` COVER LETTER section (DOCX in `source/` + PDF at root); `--label "<Role>"` renders just one. Detail in the resume-writer skill |
| `skills/resume-writer/scripts/pdf_convert.py` | Shared DOCX → PDF conversion (LibreOffice, docx2pdf fallback) used by both renderers |
| `skills/resume-writer/scripts/extract.py` | DOCX → YAML extraction utility (re-run when the master resume changes) |
| `skills/application-tracker/scripts/status.py` | Scan applications and manage status-folder metadata; `--enrich-metadata` safely inserts missing schema-v5 level/YOE/salary facts with the formatting-preserving editor, `--check-metadata` validates them (all status folders by default), `--update`/`--update-job` transition per-job status + move the folder, `--sync-log` refreshes logs, and `--check-locations` enforces location policy |
| `skills/application-tracker/scripts/backfill_job_metadata.py` | Dry-run-by-default fleet metadata preview/backfill; requires exact `jd_file` associations for multi-role records and uses checksum-guarded atomic writes only with `--write` |
| `skills/resume-writer/scripts/check.py` | Validate tailored.yaml + PDF (locked fields, real project titles/skills, bullet lengths, one page, each JD's cover letter); re-exports the filename stems + `application_roles()`/layout helpers. Detail in the resume-writer skill |
| `automation/shared/config.py` | **Canonical** config loader — candidate identity, paths (including the company-level cache), output-filename stems, and location policy. Vendored into `job-search`, `resume-writer`, and `application-tracker` |
| `automation/shared/layout.py` | **Canonical** pure application-folder layout helpers (no identity/config): `source/` rules, `slugify_label` / `compose_stem`, `application_roles()`, and `find_jd_files`. Vendored into `resume-writer` and `application-tracker` |
| `automation/shared/location.py` | **Canonical** shared location classifier — turns a posting `location` string into a match (e.g. `metro` / `us_remote`) or no-match (`other_us` / `foreign` / `unknown`) per the configured location policy (ships with NO built-in metros; callers inject `config.location_policy()`); also extracts `Location:` lines from JD files. Vendored into `job-search`, `resume-writer`, and `application-tracker` (see `handbook/skills-and-vendoring.md`) |
| `automation/shared/job_metadata.py` | **Canonical** pure extractor/validator for the flat schema-v5 per-posting `status`, job level (normalized word + approximate Google-equivalent range), required YOE, salary, `workplace` (onsite/hybrid/remote), and heuristic `sponsorship` (likely/unlikely/unknown), plus the `derive_status` folder rollup and loading of the optional sourced company-levels reference cache. Vendored into all three job workflow skills |
| `automation/shared/metadata_editor.py` | **Canonical** formatting-preserving schema-v5 `meta.yaml` editor (YAML node anchors, checksums, atomic writes, semantic verification, idempotence). Vendored into application-tracker |
| `automation/maintenance/import_company_levels.py` | Dry-run-by-default YAML/JSON/CSV importer for user-supplied or licensed company-level facts; never fetches/scrapes Levels.fyi and keeps base/stock/bonus/total plus geographic bands distinct |
| `automation/vendoring/sync_vendored.py` | Vendoring tool: copies each canonical shared module into every consuming skill's `scripts/_vendor/` (registry in `TARGETS`); `--check` fails on drift (run by the pre-commit hook) |
| `automation/hooks/pre-commit` | Tracked git pre-commit hook: runs the vendored-copy drift check + `compileall`. Install once: `python automation/bootstrap_overlay.py` (installs pre-commit AND pre-push) |
| `skills/<skill>/scripts/_vendor/` | Generated byte-identical copies of vendored toolkit modules (e.g. `config.py`, `layout.py`, `location.py`, `job_metadata.py`, `metadata_editor.py`) — do not edit; regenerate via `automation/vendoring/sync_vendored.py` |
| `skills/ask-me-anything/` | PUBLIC orientation guide: the five-step workflow, repo structure, and which skill + dependencies each step needs (read first when a user asks how the toolkit works or where to start) |
| `skills/job-search/` | PUBLIC skill for discovering and ranking matching job postings (role, keyword, location, recency, visa filters) |
| `skills/resume-writer/` | PUBLIC skill for resume tailoring |
| `skills/application-tracker/` | PUBLIC skill for application status and pipeline management |
| `skills/behavioral-interview-prep/` | PUBLIC skill for behavioral interview story banks and STAR answers |
| `skills/company-research/` | PUBLIC skill for researching a company + role for interviews (product, size, teams, values, stage, comp, WLB, ratings, visa) and drafting a hiring-manager/engineer question bank under `interviews/company-specific/<company>/company-info/` |
| `skills/email-assistant/` | PUBLIC draft-only personal email workflow (Outlook via Microsoft Graph today): reads mailbox messages, grounds suggested replies in the private job-hunt data, and creates Outlook drafts. OAuth tokens stay in the OS keyring; the skill has no send capability and consumes the mail layer only through its vendored copy. |
| `automation/shared/mail/` | The send-less mail layer: `contract/` (MailProvider interface, audited raw-HTTP transport with per-provider route allowlists, provider conformance suite incl. the read-only `--live` mode), `providers/outlook_graph/` (the isolated Outlook implementation), and the folder-walking `check_mail_safety.py` run by pre-commit |
| `.claude/skills/`, `.cursor/skills/` | Tool-compatibility symlinks to `skills` (for agents that look in their own skill directories) |
| `.agents/MEMORY.md` | Cross-session hypotheses and learnings (gitignored) |
| `tmp/` | Gitignored scratch space for **all** disposable, ad-hoc work — one-off ATS/API probes, fetched web artifacts, sanity checks — organized into purpose-named subfolders (`tmp/ats_scripts/`, `tmp/web_artifacts/`, `tmp/scratch/`). Never committed; created on demand; nothing in the toolkit may depend on it. See `handbook/file-organization.md` |
| `message-queue/` | Async human↔agent messages, one file each, routed by who acts next (contract: `AGENTS.md` → Async Collaboration; map: `message-queue/README.md`): `needs-human/` `decisions/`, `clarifications/`, `reviews/`; `needs-agent/` `requests/`, `retries/`. Private mirror: `private/message-queue/` |
| `tasks/` | Work items, one folder per task (`YYYY-MM-DD-<slug>`); the status folder it sits in IS its status (`0_backlog`…`4_done`). Map: `tasks/README.md` |
| `memory/` | Long-term project memory: `decisions/` (append-only ADR log; open questions live in `message-queue/needs-human/decisions/` until decided), `known-issues/` (canonical detailed bug records — GitHub issues link here), `facts/`, `lessons/` |
| `templates/` | Single source of truth for every process-file schema — queue items, tasks, memory entries, handovers (`templates/README.md`) |
| `roadmap/` | `desired-state.md` vs `current-state.md`; the gap is the backlog's source (`roadmap/README.md`) |
| `history/` | One folder per working session under `conversations/`, each with a `handover.md` (`history/README.md`) |
| `automation/reconcile/reconcile.py` | The reconciler — mechanical referee for process-layer schemas, the memory index, handovers, and roadmap freshness; runs in pre-commit + CI; `--file-retries` queues findings, `--fix-index` regenerates `memory/index.md` |
| `design/` | Active design programs (multi-approach explorations, execution plans), one folder per topic; folder-local contract in `design/AGENTS.md` |
| `handbook/` | This folder — the extended reference behind `AGENTS.md` (`handbook/README.md` is the index) |
| `README.md` | Human-facing quickstart (capability-first: example output, then the workflow) |
| `handbook/architecture.md` | Human-facing design doc: render pipeline, config system, vendoring, CI gates, repo reference |
| `AGENTS.md` | The agent-facing contract (core) |
