---
name: email-assistant
visibility: public
description: Read a personal Microsoft Outlook mailbox, connect recruiter or hiring-team messages to job applications in this repository, maintain action-first application notes and interview calendar events, reconcile evidence-backed application status changes, draft grounded replies, and save them as Outlook drafts through Microsoft Graph. Use when the user asks to review, summarize, prioritize, or reply to Outlook email, update application notes or calendar events from recruiter messages, or reconcile their job pipeline. This skill is permanently draft-only and must never send email.
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

## Local Bounded Store

For a complete bounded review, sync Inbox, Sent Items, and Drafts into the private local store,
then verify freshness before reading its content-free reconciliation projection:

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py sync-store --days 30 --full
.venv/bin/python skills/email-assistant/scripts/outlook_email.py store-staleness
.venv/bin/python skills/email-assistant/scripts/outlook_email.py store-review
```

Set `--days` to the user-requested window (for example, `--days 90`) rather than silently applying
the 30-day example. Include Inbox and Sent Items for the complete communication timeline; use Drafts
only to reconcile unsent work, and never present a draft as a sent communication.

If a transient Graph failure prevents a complete store refresh, keep the review read-only and use
the bounded live fallback with the same exact start timestamp. `--compact` retains message IDs,
subjects, participants, and timestamps while omitting body previews and web links; reopen only
relevant messages with `read`:

```bash
.venv/bin/python skills/email-assistant/scripts/outlook_email.py \
  inbox --limit 2000 --since '2026-04-24T07:00:00Z' --compact
.venv/bin/python skills/email-assistant/scripts/outlook_email.py \
  sent --limit 2000 --since '2026-04-24T07:00:00Z' --compact
```

The store keeps full message bodies only under the git-ignored private email data root and stores
attachment metadata, never attachment bytes. `store-review` is read-only, fails closed on stale or
incomplete sync state, and emits neutral keys rather than subjects, addresses, or body text. Unknown
company/role links remain unresolved until exact evidence or an approved private company-domain
mapping exists. Until the store-first cutover gate is satisfied, retain the live review-window and
exact-message preflight before any draft or application change.

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
   `in_progress`. Update the application's `notes.md` through the communication-notes protocol below;
   the status itself lives in `meta.yaml`, not in `notes.md`.
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

Never copy full mailbox bodies into application files. Save concise paraphrases needed for the
communication timeline and pipeline traceability, and keep personal mailbox details out of the
public repository.

## Application Communication Notes

For every requested mailbox review, maintain one private `notes.md` communication record per
unambiguously matched application. Associate mail by exact company plus role, job ID, recruiter
domain, or established conversation evidence; a company name alone is insufficient when multiple
applications could match. Include every matched Inbox and Sent message in the bounded review
window—one entry per message, not one blended thread summary. Skip alerts, newsletters, and other
mail that is not actually part of the application process.

Preserve existing interview preparation, technical exercises, and other hand-written content. Add
or refresh these sections immediately after the note title, in this order:

```markdown
## Upcoming Events & To-Dos

- [ ] 2026-08-04 10:00 AM PT — Technical interview; interviewer: Casey Lee; calendar: confirmed
- [ ] Waiting — Morgan Chen (Recruiter) to send the onsite schedule

## People

- **Morgan Chen** — Recruiter, Example Corp — morgan@example.com
- **Casey Lee** — Interviewer, Infrastructure — role inferred from explicit email signature

## Email Timeline

### 2026-07-23 2:15 PM PT — Inbound — Technical interview confirmation

- **People:** Morgan Chen; Casey Lee
- **Summary:** Confirmed a 60-minute infrastructure interview for August 4 and named Casey as the interviewer.
- **Outcome / next step:** Calendar event confirmed; prepare system-design examples.
```

Apply these rules:

- Keep `Upcoming Events & To-Dos` at the top and actionable. List only open work, future events, and
  explicit waits, with the responsible person when known. Do not invent deadlines. Remove resolved
  items from this dashboard after their resolution is captured in the timeline; write `None
  currently.` when there are no open items.
- Record exact event date, time, duration, and timezone from the message. Preserve the sender's
  timezone and add the user's local equivalent when useful. Proposed availability, a scheduling
  link, or “we will schedule” is a to-do—not a confirmed event.
- In `People`, deduplicate people across the thread. Record the person's explicit name, recruiting
  or interview role, team/company, and email address when present. Do not guess a name or role from
  an opaque address; label uncertain facts as unknown rather than inferring them.
- Keep `Email Timeline` reverse chronological. Each Inbox or Sent message gets its own dated,
  direction-labeled entry with subject, relevant people, a one-to-three-sentence paraphrase, and
  the resulting outcome or next action. Never paste full bodies, long quotations, signatures,
  opaque provider message IDs, or irrelevant personal details.
- Deduplicate by stable message evidence before editing. A later review updates an existing entry
  instead of appending the same email again. A Draft may inform the current to-do dashboard, but
  label it as unsent and never put it in the sent communication timeline.
- Status changes still go through `status.py`; do not let prose in `notes.md` become a second status
  authority.

## Interview Calendar Reconciliation

When the user asks to update a calendar, use the connected Outlook Calendar capability; never widen
the audited email provider's Graph route or permission allowlist. For each exact future interview
time found in matched mail:

1. Read the mailbox timezone, then search the relevant calendar window for the company, role, stage,
   and exact start time. Fetch plausible matches before writing.
2. If an organizer-created invitation or equivalent event already represents the interview, leave it
   unchanged and mark the note dashboard `calendar: confirmed`.
3. If no event exists and the email confirms a start, duration/end, and timezone, create one personal
   event titled `Interview — <Company> — <Stage or Role>`. Do not add external attendees, because
   that can notify them; list recruiter/interviewer names and the evidence date in the body instead.
   Carry over an explicit meeting link or location, mark the time busy, and use a 30-minute reminder.
4. Update only an unambiguous personal event when later email explicitly reschedules it. Never guess
   a timezone or duration, respond to an invitation, create an event from proposed availability, or
   duplicate an existing event. Keep unresolved scheduling requests as top-of-note to-dos.
5. Report every created, updated, already-present, and intentionally skipped event with its evidence.

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
