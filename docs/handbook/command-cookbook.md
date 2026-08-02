# Command Cookbook (full)

Expands `AGENTS.md` → "Handy Commands". Always use the repo venv:
`.venv/bin/python` (needs Python 3.11+). PDF conversion uses LibreOffice,
which `skills/resume-writer/scripts/pdf_convert.py` finds via
`~/Applications`, `/Applications`, or `soffice` on `PATH` (override with the
`JOBHUNT_SOFFICE` env var).

**`applications/` in every command below is shorthand for `config.applications_root()`**
(`private/applications/` for a real hunt, `examples/applications/` under the shipped
example config) — substitute the resolved path, never a literal folder at the repo root.

```bash
# Render a tailored resume to DOCX (source/) + PDF (root) and validate it (format,
# locked fields, one page). Also renders one cover letter PER JD from each bundled
# ..._Application_<job title>.txt. Accepts the app folder or the source/tailored.yaml path.
.venv/bin/python skills/resume-writer/scripts/render.py applications/6_drafted/<slug>/

# Render only the cover letters (one per JD, from each bundled ..._Application_<job title>.txt)
.venv/bin/python skills/resume-writer/scripts/cover_letter.py applications/6_drafted/<slug>/
# Render just one role's cover letter:
.venv/bin/python skills/resume-writer/scripts/cover_letter.py applications/6_drafted/<slug>/ --label "Senior Platform Engineer"

# Validate without rendering (a missing/unreadable PDF FAILs — the one-page gate is mandatory)
.venv/bin/python skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/
# Same, for a deliberate DOCX-only draft: the PDF gates are reported NOT RUN, not failed
.venv/bin/python skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/ --no-pdf

# Show all applications and their status (status = which folder each app lives in)
.venv/bin/python skills/application-tracker/scripts/status.py

# Populate/validate schema-v6 level, required YOE, salary + approximate Google-equiv from JD + cache.
.venv/bin/python skills/application-tracker/scripts/status.py --enrich-metadata applications/6_drafted/<slug>/
# Fleet preview: dry-run, covers ALL status folders (strict schema v6). Use --statuses <labels> to
# narrow to a set; add --write only after reviewing the dry-run preview.
.venv/bin/python skills/application-tracker/scripts/backfill_job_metadata.py
# Validate structured metadata — ALL status folders by default; --statuses <labels> to narrow.
.venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
# Migrate v4 meta.yaml files to schema v5 (fleet dry-run diff; --write applies atomically)
.venv/bin/python skills/application-tracker/scripts/migrate_to_v5.py
# Migrate v5 scalar calendar links to schema v6 ordered lists (fleet dry-run; all files preflight before --write)
.venv/bin/python skills/application-tracker/scripts/migrate_to_v6.py

# Import user-supplied/licensed company-level facts (YAML/JSON/CSV; dry-run by default)
.venv/bin/python automation/company-levels/import_company_levels.py INPUT <company-levels.yaml>

# Append every changed posting to the append-only skip-log (the postings job-search
# skips) and upsert company-search-log.yaml created entries. Never rewrites the log,
# so deleting an application does not un-skip its posting. --update/--update-job
# already append as they go; this is the reconciliation backstop.
# Exits 1 when an application's meta.yaml would not parse: every other application
# is still written, but no row is DERIVED from a file the tool could not read (the
# log is append-only, so a wrong row needs a --forget-log tombstone). Fix the file
# and re-run. --backfill-log below behaves the same way.
.venv/bin/python skills/application-tracker/scripts/status.py --sync-log

# One-time seed of the append-only skip-log from the retired applications-log.yaml
# UNION the application folders. Refuses if the log exists; --force appends a fresh
# generation (a later line wins the fold; nothing is ever deleted).
.venv/bin/python skills/application-tracker/scripts/status.py --backfill-log

# Un-skip ONE posting by appending a tombstone — the only way to repair a wrong row,
# since nothing rewrites the log. One value = the posting URL, two = COMPANY ROLE.
# Refuses when that key is not currently folded. This is also the undo for an
# abandoned scaffold: handoff records every folder it creates, whatever exit code
# the run returned, and prints this command with its argument filled in on a
# non-zero exit.
.venv/bin/python skills/application-tracker/scripts/status.py --forget-log '<posting-url>'

# Record a successful company search with no application folder (no suitable role)
.venv/bin/python skills/application-tracker/scripts/status.py --log-search "Example Corp" --outcome no_suitable
# Optional: --date YYYY-MM-DD

# Transition status (writes per-job status + moves the folder to match the rollup)
# (statuses: drafted | applied | in_progress | rejected | ignored)
.venv/bin/python skills/application-tracker/scripts/status.py --update <slug> applied
# Transition ONE posting in a multi-role app (role-match = role substring or 1-based index)
.venv/bin/python skills/application-tracker/scripts/status.py --update-job <slug> "<role-match>" in_progress
# Set ONE posting's structured progress (meta + calendar together; never moves folders)
.venv/bin/python skills/application-tracker/scripts/status.py --update-progress <slug> "<role-match>" --phase technical_interview --state booking_required
# Verify calendar.md <-> progress consistency; preview/apply owner calendar edits
.venv/bin/python skills/application-tracker/scripts/status.py --check-calendar
.venv/bin/python skills/application-tracker/scripts/status.py --sync-calendar          # add --write to apply

# Personal Outlook (draft-only; user sends manually; see the email-assistant skill
# for login/inbox/draft commands)
.venv/bin/python skills/email-assistant/scripts/outlook_email.py doctor
# Capture all four folders; repeat --query for company, role, or recruiter-domain participant terms
.venv/bin/python skills/email-assistant/scripts/outlook_email.py sync-store --all --full
.venv/bin/python skills/email-assistant/scripts/outlook_email.py store-search --query '<company>' --query '<role>'
# Single-scan, content-free coverage: each query is independent; include active application families
.venv/bin/python skills/email-assistant/scripts/outlook_email.py store-coverage --in-progress-applications --query '<recruiter-domain>' --query '<thread-alias>'

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

# Install the git hooks once (pre-commit: staged-index leak guard + staged-private/
# reject + public review gate + drift check + compileall; pre-push: the armed leak
# guard). When the
# overlay is mounted this also installs ITS hooks into private/.git/hooks/ —
# automation/hooks/overlay-pre-commit (store-payload + staged-set-size guard) and
# overlay-pre-push (destination must be the configured private remote).
python automation/bootstrap_overlay.py

# Reconciler by hand. Plain --check no-ops on a process folder that is absent (the
# published export ships none of message-queue/, tasks/, memory/, docs/roadmap/,
# history/). --require-roots is the maintainer-checkout assertion that they all
# exist; the pre-commit hook adds it automatically when private/ is mounted.
.venv/bin/python automation/reconcile/reconcile.py --check
.venv/bin/python automation/reconcile/reconcile.py --check --require-roots

# Leak guard by hand. It refuses to run unarmed (exit 2) — a checkout with no real
# config.yaml identity adds --allow-unarmed to run the token-independent checks.
.venv/bin/python automation/publish/check_public.py
.venv/bin/python automation/publish/check_public.py --staged   # what a commit would add

# Public review gate by hand. Fails (exit 1) when the published tree changed since
# the last row in automation/publish/review_ledger.yaml, and prints the row to add.
# --staged is what the pre-commit hook runs: it judges the STAGED INDEX, so the row
# it prints carries no `commit:` (that SHA does not exist yet) and the change and its
# review go in ONE commit — append the row, `git add` the ledger, commit. Without
# --staged it judges HEAD and prints a `commit:`-carrying row, which is the shape for
# history that already landed. Exit 2 means the ledger itself is wrong (bad digest,
# malformed row, ack not an ancestor of HEAD).
.venv/bin/python automation/publish/review_gate.py --staged      # what pre-commit runs
.venv/bin/python automation/publish/review_gate.py               # judge HEAD instead
.venv/bin/python automation/publish/review_gate.py --verify-all  # recompute EVERY row (CI)

# Install dependencies
pip install -r requirements.txt
```
