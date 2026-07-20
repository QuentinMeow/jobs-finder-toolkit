---
name: outlook-email-assistant
visibility: public
description: Read a personal Microsoft Outlook mailbox, connect recruiter or hiring-team messages to job applications in this repository, draft evidence-grounded replies, and save them as Outlook drafts through Microsoft Graph. Use when the user asks to review, summarize, prioritize, or reply to Outlook email, especially for recruiters, interviews, applications, scheduling, follow-ups, or offer communication. This skill is permanently draft-only and must never send email.
---

# Outlook Email Assistant

Read Outlook mail and create suggested replies grounded in the job-hunt repository. Keep every
message in Outlook's Drafts folder so the user remains the only sender.

## Before You Start

1. Read `AGENTS.md`, especially the public/private model and the email draft-only guardrail.
2. Read `references/graph-contract.md` before authentication, permissions, or Graph changes.
3. If `references_private/` exists, read every file in it. Candidate-specific writing preferences
   override the generic guidance here; otherwise use the profile and application evidence.
4. Use `.venv/bin/python` for every script. Keep disposable draft-body files under
   `tmp/outlook-email-assistant/`; do not save mailbox content in tracked or product folders.

## Non-Negotiable Safety Boundary

- Never send email, even if the user explicitly asks. Tell them to review and send in Outlook.
- Never request or accept a Microsoft password, client secret, or `Mail.Send` permission.
- Use only `scripts/outlook_email.py`; do not call arbitrary Graph URLs with `curl` or another tool.
- Create or update a message only when Graph returns `isDraft: true`. A missing/false value is a
  hard failure.
- Do not mark mail read, delete/move messages, change categories, or modify application status as
  a side effect of drafting.
- Do not persist message bodies, OAuth tokens, or generated drafts in the public repository.
- Never claim relocation, work authorization, availability, compensation, or another material fact
  unless the profile, matched application, private references, or the user confirms it.

The runtime, static policy checker, unit tests, and pre-commit hook all enforce this boundary.

## One-Time Setup

Run:

```bash
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py doctor
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
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py login
```

The script prints Microsoft's device-login URL and code. The user signs in directly with
Microsoft; never ask them to paste credentials into chat. OAuth refresh state is stored only in
the OS keyring and is tied to the configured mailbox.

## Drafting Workflow

### 1. Reconcile Inbox, Sent Items, and Drafts

Always run the read-only review window before drafting. This is a hard pre-draft gate, not an
optional check:

```bash
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py \
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
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py inbox --limit 10
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py read \
  --message-id '<graph-message-id>'
```

Read only the messages needed for the request. Narrow by recency before expanding scope.

### 3. Match the application

Use sender, company, role, and subject text:

```bash
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py \
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

Write the proposed body to `tmp/outlook-email-assistant/reply.txt`, show the exact text to the
user when review was requested, then run:

```bash
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py \
  create-reply-draft --message-id '<graph-message-id>' \
  --body-file tmp/outlook-email-assistant/reply.txt
```

For a new thread, use `create-draft --to ... --subject ... --body-file ...`. Treat the operation
as successful only when output contains `"isDraft": true`. Remove the disposable body file after
success. Report the draft subject/recipients and remind the user that sending is manual.

`create-reply-draft` independently repeats the Sent/Drafts preflight and fails closed if a later
Sent reply or existing conversation draft is found. Do not bypass this check with `create-draft`.

## Other Commands

```bash
# List existing drafts without changing them.
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py drafts --limit 10

# List Sent Items without changing them.
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py sent --limit 10

# Remove only the local OAuth cache from the OS keyring; re-login restores access.
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/outlook_email.py logout

# Run the structural guard and unit suite.
.venv/bin/python .agents/skills/outlook-email-assistant/scripts/check_draft_only.py
.venv/bin/python -m unittest discover \
  -s .agents/skills/outlook-email-assistant/scripts/tests -v
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
