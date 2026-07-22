# Command Cookbook (full)

Expands `AGENTS.md` → "Handy Commands". Always use the repo venv:
`.venv/bin/python` (needs Python 3.11+). PDF conversion uses LibreOffice,
which `skills/resume-writer/scripts/pdf_convert.py` finds via
`~/Applications`, `/Applications`, or `soffice` on `PATH` (override with the
`JOBHUNT_SOFFICE` env var).

```bash
# Render a tailored resume to DOCX (source/) + PDF (root) and validate it (format,
# locked fields, one page). Also renders one cover letter PER JD from each bundled
# ..._Application_<job title>.txt. Accepts the app folder or the source/tailored.yaml path.
.venv/bin/python skills/resume-writer/scripts/render.py applications/6_drafted/<slug>/

# Render only the cover letters (one per JD, from each bundled ..._Application_<job title>.txt)
.venv/bin/python skills/resume-writer/scripts/cover_letter.py applications/6_drafted/<slug>/
# Render just one role's cover letter:
.venv/bin/python skills/resume-writer/scripts/cover_letter.py applications/6_drafted/<slug>/ --label "Senior Platform Engineer"

# Validate without rendering
.venv/bin/python skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/

# Show all applications and their status (status = which folder each app lives in)
.venv/bin/python skills/application-tracker/scripts/status.py

# Populate/validate schema-v4 level, required YOE, salary + approximate Google-equiv from JD + cache.
.venv/bin/python skills/application-tracker/scripts/status.py --enrich-metadata applications/6_drafted/<slug>/
# Fleet preview: dry-run, covers ALL status folders (strict schema v4). Use --statuses <labels> to
# narrow to a set; add --write only after reviewing the dry-run preview.
.venv/bin/python skills/application-tracker/scripts/backfill_job_metadata.py
# Validate structured metadata — ALL status folders by default; --statuses <labels> to narrow.
.venv/bin/python skills/application-tracker/scripts/status.py --check-metadata

# Import user-supplied/licensed company-level facts (YAML/JSON/CSV; dry-run by default)
.venv/bin/python automation/maintenance/import_company_levels.py INPUT <company-levels.yaml>

# Regenerate applications-log.yaml (the postings job-search skips) from all folders
# and upsert company-search-log.yaml created entries
.venv/bin/python skills/application-tracker/scripts/status.py --sync-log

# Record a successful company search with no application folder (no suitable role)
.venv/bin/python skills/application-tracker/scripts/status.py --log-search "Example Corp" --outcome no_suitable
# Optional: --date YYYY-MM-DD

# Transition status (writes per-job status + moves the folder to match the rollup)
# (statuses: drafted | applied | in_progress | rejected | ignored)
.venv/bin/python skills/application-tracker/scripts/status.py --update <slug> applied
# Transition ONE posting in a multi-role app (role-match = role substring or 1-based index)
.venv/bin/python skills/application-tracker/scripts/status.py --update-job <slug> "<role-match>" in_progress --stage "onsite"

# Personal Outlook (draft-only; user sends manually; see the email-assistant skill
# for login/inbox/draft commands)
.venv/bin/python skills/email-assistant/scripts/outlook_email.py doctor

# Mail send-less safety check (folder-walks every provider; also run by pre-commit)
.venv/bin/python automation/shared/mail/check_mail_safety.py --consumer skills/email-assistant/scripts

# Provider conformance against the synthetic fixture mailbox (CI-safe)
.venv/bin/python automation/shared/mail/contract/conformance.py
# Owner opt-in READ-ONLY conformance against the real mailbox (never CI)
.venv/bin/python automation/shared/mail/contract/conformance.py --provider outlook_graph --live

# Extract content from a DOCX resume (utility)
.venv/bin/python skills/resume-writer/scripts/extract.py path/to/resume.docx

# Regenerate vendored copies after editing a canonical shared module
# (e.g. automation/shared/config.py, layout.py, or location.py), then verify no copy has drifted
.venv/bin/python automation/vendoring/sync_vendored.py
.venv/bin/python automation/vendoring/sync_vendored.py --check

# Install the git hooks once (pre-commit drift check + compileall, and pre-push)
python automation/bootstrap_overlay.py

# Install dependencies
pip install -r requirements.txt
```
