---
name: email-assistant
visibility: public
description: Read a personal Microsoft Outlook mailbox, connect recruiter or hiring-team messages to job applications in this repository, reconcile evidence-backed application status changes, draft grounded replies, and save them as Outlook drafts through Microsoft Graph. Use when the user asks to review, summarize, prioritize, or reply to Outlook email, or update their job pipeline from recruiter or hiring-team messages. This skill is permanently draft-only and must never send email.
---

# Email Assistant

Read Outlook mail and create suggested replies grounded in the job-hunt repository. Keep every
message in Outlook's Drafts folder so the user remains the only sender. (Outlook via Microsoft
Graph is the only provider today; the provider layer lives in `automation/shared/mail/`.)

## Before You Start

1. Read `AGENTS.md`, especially the public/private model and the email draft-only guardrail.
2. Read `scripts/_vendor/mail/providers/outlook_graph/README.md` (the provider contract) before
   authentication, permissions, or Graph changes.
3. If `references_private/` exists, read every file in it. Candidate-specific writing preferences
   override the generic guidance here; otherwise use the profile and application evidence.
4. Use `.venv/bin/python` for every script. Keep disposable draft-body files under
   `tmp/email-assistant/`; do not save mailbox content in tracked or product folders.

## Non-Negotiable Safety Boundary

- Never send email, even if the user explicitly asks. Tell them to review and send in Outlook.
- Never request or accept a Microsoft password, client secret, or `Mail.Send` permission.
- Use only `scripts/outlook_email.py`; do not call arbitrary Graph URLs with `curl` or another tool.
- Create or update a message only when Graph returns `isDraft: true`. A missing/false value is a
  hard failure.
- Do not mark mail read, delete/move messages, or change categories. Keep pipeline reconciliation
  separate from drafting and apply the evidence gates below before changing application status.
- Do not persist message bodies, OAuth tokens, or generated drafts in the public repository.
- Never claim relocation, work authorization, availability, compensation, or another material fact
  unless the profile, matched application, private references, or the user confirms it.

The runtime, static policy checker, unit tests, and pre-commit hook all enforce this boundary.

## One-Time Setup

Run:

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py doctor
```

If configuration is missing, have the user register a **public client** application in Microsoft
Entra with personal Microsoft accounts enabled, public-client/device-code flow enabled, and only
delegated `User.Read` + `Mail.ReadWrite`. Put the mailbox address and application client ID in the
git-ignored `config.yaml`:

```yaml
outlook_email:
  account: "<personal-mailbox>"
  client_id: "00000000-0000-0000-0000-000000000000"
  tenant: "consumers"
```

Then authenticate:

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py login
```

The script prints Microsoft's device-login URL and code. The user signs in directly with
Microsoft; never ask them to paste credentials into chat. OAuth refresh state is stored only in
the OS keyring and is tied to the configured mailbox.

## Pipeline Status Reconciliation

During a requested job-related mailbox review, automatically reconcile clear application outcomes
with the repository. Treat this as a separate local workflow from drafting:

1. Run `review-window --limit 50`, then widen the read-only scan with `inbox --limit 500` when the
   user asks for a mailbox-wide status review. Expand up to `--limit 2000` only when a named older
   thread or outcome is still missing.
2. Consider only explicit hiring signals, and classify each by **scope**. *Per-role evidence* — an
   interview/screen request, a confirmed next round, or a rejection naming one specific posting in a
   multi-role app — transitions just that posting. *Whole-application evidence* — an application
   receipt covering the app, or a rejection that closes every tracked role — transitions the whole
   application. A receipt moves `drafted` to `applied`; an interview/screen or confirmed next round
   moves to `in_progress`; an explicit rejection or closed role moves to `rejected`.
3. Read the exact message and run `match-application` using company, exact role or job ID, subject,
   and sender. Require one unambiguous match — down to the exact posting when the evidence is
   per-role. A company name alone, a low score, a job alert, or a stale outcome for another role is
   not enough.
4. For a multi-role application, land a per-role outcome as **that posting's** `status` (via
   `--update-job` in the next step); the folder then follows the rollup automatically — one rejected
   role no longer forces the whole folder, and any confirmed active interview rolls the folder up to
   `in_progress`. Also record a concise dated outcome for the role in the application's `notes.md`
   (the narrative log); the status itself now lives in `meta.yaml`, not in `notes.md`.
5. Make a confirmed transition only through the application-tracker command, matched to the evidence
   scope:

   ```bash
   # per-role evidence -> one posting (record the named round via --update-progress afterwards)
   .venv/bin/python skills/application-tracker/scripts/status.py \
     --update-job <slug> "<role-match>" <applied|in_progress|rejected>
   # whole-application evidence (receipt, or rejection closing every role) -> all postings + folder
   .venv/bin/python skills/application-tracker/scripts/status.py \
     --update <slug> <applied|in_progress|rejected>
   ```

6. After all moves, run `status.py --sync-log`. Report every local change with application slug,
   the affected role (for per-role updates), previous status, new status, and the message evidence.
   Also report ambiguous or already-current matches that were intentionally left unchanged.

Never copy full mailbox bodies into application files. Save only the minimum outcome note needed
for pipeline traceability, and keep personal mailbox details out of the public repository.

## Drafting Workflow

### 1. Reconcile Inbox, Sent Items, and Drafts

Always run the read-only review window before drafting. This is a hard pre-draft gate, not an
optional check:

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py \
  review-window --limit 50
```

For each relevant conversation:

- `already_replied`: do not draft another reply.
- `already_replied_with_redundant_draft`: do not draft; show an eye-catching
  **⚠️ ACTION REQUIRED** warning and tell the user to review Sent Items and manually delete the
  redundant draft in Outlook if appropriate. Never delete it for them.
- `draft_exists`: review/edit that draft; do not create another.
- `reply_may_be_needed`: read the message and continue only after confirming it needs a reply.

When there are required user actions, lead the response with **⚠️ ACTION REQUIRED** and record
the same checklist in the requested private review/product file and PR description. Keep personal
subjects and mailbox details out of the public repository and public PR.

### 2. Read the relevant mail

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py inbox --limit 10
.venv/bin/python skills/email-assistant/scripts/outlook_email.py read \
  --message-id '<graph-message-id>'
```

Read only the messages needed for the request. Narrow by recency before expanding scope.

### 3. Match the application

Use sender, company, role, and subject text:

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py \
  match-application --query '<company role subject>' --sender '<sender-address>'
```

Confirm the best match rather than trusting a low score. Then read the matched application's
`meta.yaml`, exact `source/JD-*.md`, bundled `*_Application_*.txt`, optional `notes.md`, and only
the profile/story-bank material needed for the reply. Never infer facts from a similar company.

### 4. Compose the suggested reply

- Answer every direct question from the email.
- Reuse only documented experience, dates, compensation, work authorization, and availability.
- Keep recruiter replies concise and specific; avoid generic enthusiasm.
- Do not promise interview times, salary numbers, referrals, or documents that the repository or
  user has not confirmed.
- Preserve the original subject and recipients for replies.
- If a material fact is missing, ask the user before inserting it; still draft the safe portions.

### 5. Save the Outlook draft

Write the proposed body to `tmp/email-assistant/reply.txt`, show the exact text to the
user when review was requested, then run:

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py \
  create-reply-draft --message-id '<graph-message-id>' \
  --body-file tmp/email-assistant/reply.txt
```

For a new thread, use `create-draft --to ... --subject ... --body-file ...`. Treat the operation
as successful only when output contains `"isDraft": true`. Remove the disposable body file after
success. Report the draft subject/recipients and remind the user that sending is manual.

`create-reply-draft` independently repeats the Sent/Drafts preflight and fails closed if a later
Sent reply or existing conversation draft is found. Do not bypass this check with `create-draft`.

## Other Commands

```bash
# List existing drafts without changing them.
.venv/bin/python skills/email-assistant/scripts/outlook_email.py drafts --limit 10

# List Sent Items without changing them.
.venv/bin/python skills/email-assistant/scripts/outlook_email.py sent --limit 10

# Remove only the local OAuth cache from the OS keyring; re-login restores access.
.venv/bin/python skills/email-assistant/scripts/outlook_email.py logout

# Run the folder-walking mail-safety guard and the unit suite.
.venv/bin/python automation/shared/mail/check_mail_safety.py \
  --consumer skills/email-assistant/scripts
.venv/bin/python -m unittest discover \
  -s skills/email-assistant/scripts/tests -v
```

## Failure Handling

- Authentication missing/expired: run `login`; do not weaken keyring or OAuth requirements.
- Configured mailbox differs from `/me`: stop, clear the cache with `logout`, and reauthenticate.
- Graph denies permissions: inspect the app registration; never add `Mail.Send` as a workaround.
- Draft response lacks `isDraft: true`: stop and report the failure; do not retry through another
  endpoint or browser send flow.
- Application match is ambiguous: present the top candidates and ask the user which is correct.
- Later Sent reply found: skip drafting. If a draft also exists, warn that manual cleanup is needed.
- Existing conversation draft found: review it; never create a duplicate or delete it automatically.
- User asks to send: refuse that step and point them to the saved Outlook draft.
