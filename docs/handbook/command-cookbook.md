# Command Cookbook (full)

Expands `AGENTS.md` → "Handy Commands". Always use the repo venv:
`.venv/bin/python` (needs Python 3.11+). PDF conversion uses LibreOffice,
which `skills/resume-writer/scripts/pdf_convert.py` finds via
`~/Applications`, `/Applications`, or `soffice` / `libreoffice` on `PATH`.
`JOBHUNT_SOFFICE` selects a binary before those defaults; it does not change
the permissions inherited by that process.

```bash
# One local Git dashboard for the public toolkit and its optional private overlay.
# Compact mode still lists every registered worktree and every local/cached-remote
# branch; -v adds changed files, commit subjects, upstreams, remote URLs and
# worktree administrative flags. It reads cached refs and never fetches.
./automation/workspace/status.py
./automation/workspace/status.py -v

# Every branch also carries a DERIVED state (active/idle/stale/merged/orphaned/
# wedged) and its intent — `git branch --edit-description` if it has one, else
# the branch's first commit subject. Nothing is stored, so nothing goes stale.
git config branch."$(git branch --show-current)".description "what this branch is for
next: the single next action"
./automation/workspace/status.py --json          # the whole model, for tools
./automation/workspace/status.py --stale 14      # only what nobody has touched
./automation/workspace/status.py --pr            # ask GitHub via gh (network)

# Plan the retirement of finished branches and worktrees. Dry-run by default and
# there is no --force: --execute performs ONLY the non-destructive half (backup
# refs under refs/agent-trash/, pruning worktree metadata whose directory is
# already gone). The destructive half is written to
# local/workspace/cleanup-<run-id>.sh for you to read and run.
./automation/workspace/cleanup.py                       # stale plan (no fetch)
./automation/workspace/cleanup.py --fetch               # the executable check
./automation/workspace/cleanup.py --fetch --execute     # + backup refs, prune

# Agent worktrees under .claude/worktrees are KEPT by default (the Claude Code
# harness sweeps them itself). To have them judged like any other worktree —
# clean tree, contained in the fetched base, unlocked, and its own reflog swept
# for commits no ref holds — ask for them explicitly. This is the supported way
# to clear that pile; `git worktree remove` is prohibited
# (docs/handbook/post-merge-cutover.md), and this flag changes nothing about
# what the tool RUNS: the retirement is still an emitted `mv` you run yourself.
./automation/workspace/cleanup.py --fetch --include-harness-worktrees

# Which branches and worktrees nobody came back to (report-only, always exit 0)
.venv/bin/python automation/gardener/gardener.py workspace-hygiene
```

On macOS, even `--headless` LibreOffice initializes AppKit and needs access to
LaunchServices. The Codex app sandbox may deny that access. The renderer and
PDF-producing gate preflight this condition without launching LibreOffice and
report a hard failure because PDF conversion and the one-page checks did not
run. Run PDF-producing commands outside the Codex app sandbox, or through a
separately validated route with LaunchServices access. Pointing
`JOBHUNT_SOFFICE` at a different binary is not a sandbox escape.

**`applications/` in every command below is shorthand for `config.applications_root()`**
(`private/me/applications/` for a real hunt, `examples/me/applications/` under the shipped
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
# Re-running replaces a dangling legacy hook symlink, or one pointing at the wrong
# tracked name, with the managed toolkit dispatcher or durable overlay copy. A
# runnable foreign hook is left alone with a warning. --check makes no changes and
# exits 1 when a tracked guard is not installed, so a checkout whose leak guard is
# silently not running fails a check instead of looking installed.
.venv/bin/python automation/bootstrap_overlay.py
.venv/bin/python automation/bootstrap_overlay.py --check

# The same bootstrap installs the repository-local dashboard shorthand. Git
# aliases live in .git/config and do not travel with a clone, so run bootstrap
# once on each device before using this form.
git ws

# Every blocking gate in one command — the whole pre-commit chain AND every CI `run:`
# step. Each gate is a subprocess with no shell and NO PIPE: its stdout+stderr are
# redirected to local/gates/<name>.log, so the exit code reported is the gate's own
# (`<gate> | tail -5; echo $?` prints tail's 0 for a gate that exited 1). A gate that
# cannot run here because no LibreOffice is installed or no private/ overlay is mounted
# reports SKIP, never PASS, and is named in the final line. A known macOS LaunchServices
# sandbox denial is FAIL (not SKIP), stops before any LibreOffice process starts, and
# makes the summary RED. Exit 0 only when at least one gate actually ran, every runnable
# selected gate exited 0, and no precondition failed. A run where NOTHING executed — empty
# selection, or every selected gate skipped — prints NO EVIDENCE and exits 3, never
# ALL GREEN and never 0. The green line always carries `n of N gates ran`.
# Note: example-render rewrites the tracked example DOCX/PDFs (CI does that in a
# throwaway checkout) — `git checkout -- examples/` after, unless those bytes are yours.
.venv/bin/python automation/gates/run_gates.py                  # everything
.venv/bin/python automation/gates/run_gates.py --list           # the table; runs nothing
.venv/bin/python automation/gates/run_gates.py --group hook     # just the pre-commit chain
.venv/bin/python automation/gates/run_gates.py --only reconciler,verify-links --tail 30

# If an unavoidable interactive zsh pipeline needs stage-level status, use the 1-indexed
# `$pipestatus` array (`${pipestatus[1]}` is the first command). Bash's `${PIPESTATUS[0]}`
# expands to an empty value in zsh. `$?` after a `for` loop or an `&&` chain likewise reports
# only the final command, so it cannot prove that every earlier gate passed.

# ── after a post-merge cutover: is the owner's data still intact? ─────────────
# The `cutover` validation profile. Reuses the gate runner above (no shell, no
# pipe, per-gate log, a SKIP is never a PASS), with its own five-gate table:
# app-metadata · calendar · configured-paths · copy-checksum · overlay-bootstrap.
# Every gate is read-only, so --jobs collapses the profile to its slowest gate.
# This is NOT automation/reconcile/reconcile.py: that judges process-layer
# schemas and gates commits; this judges owner DATA and gates nothing.
# Exit 0 = all green (skips named) · 1 = a gate failed · 3 = REFUSED before any
# subprocess, because no config loaded, it resolved to the fictional
# config.example.yaml persona, or no private overlay is mounted.
.venv/bin/python automation/cutover/validate_cutover.py --profile cutover --jobs 4
.venv/bin/python automation/cutover/validate_cutover.py --list          # the table; runs nothing
# Add --check-locations and --company-keys --strict to the same run:
.venv/bin/python automation/cutover/validate_cutover.py --profile cutover-full --jobs 4
# Point it at a run's log dir; the copy manifest is read from that dir's parent:
.venv/bin/python automation/cutover/validate_cutover.py --log-dir local/cutover/<run-id>/gates

# One gate on its own: does every config.*_path()/_dir()/_root() accessor still
# resolve to an existing destination of the right kind? The accessor list is
# DISCOVERED from automation/shared/config.py at runtime, so a new accessor is
# checked the day it lands (and an unclassified one is red, not skipped).
# Optional destinations that simply do not exist yet report SKIP; exit 3 means it
# refused to certify the fictional example persona.
.venv/bin/python automation/cutover/check_configured_paths.py

# Move git-ignored files to their merged destination WITHOUT ever overwriting or
# deleting: a destination that already holds different bytes refuses the whole
# run before a byte is written, and the source is always left in place.
.venv/bin/python automation/cutover/verify_copy.py --copy \
    --from <src file or dir> --to <dst> --manifest local/cutover/<run-id>/copied.txt
# Re-hash both ends of everything that manifest recorded. Exit 3 (never 0) when
# there is no manifest: a check that verified nothing must not read as green.
.venv/bin/python automation/cutover/verify_copy.py --verify --manifest local/cutover/<run-id>/copied.txt
# Compare two trees directly, no manifest involved:
.venv/bin/python automation/cutover/verify_copy.py --verify --from <src> --to <dst>

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
.venv/bin/pip install -r requirements.txt
```
