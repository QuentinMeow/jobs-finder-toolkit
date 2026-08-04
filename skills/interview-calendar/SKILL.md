---
name: interview-calendar
visibility: public
description: Reconcile interview and recruiting emails with application progress, private application notes, the toolkit's local interview calendar, and duplicate-free Outlook Calendar events. Use when the user asks to add, update, reschedule, audit, or deduplicate interview calendar entries; turn confirmed recruiter email into calendar events; keep interview details synchronized across email, applications, and Outlook; or review upcoming interview logistics.
---

# Interview Calendar

Coordinate the existing email, application, and Outlook Calendar capabilities. Keep evidence and
personal products private; keep each fact in its existing canonical owner instead of building a
second mail client, tracker, or calendar store.

## Before You Start

1. Read `../email-assistant/SKILL.md`, its Outlook provider contract, and every file in that
   skill's `config.skill_references_dir()` folder when present. The email assistant is the only mailbox reader;
   its permanent draft-only and send-less boundary still applies.
2. Read `../application-tracker/SKILL.md` and `../application-tracker/LESSONS.md`. The tracker is
   the only writer for `meta.yaml` and `config.calendar_path()`; use its commands for status and
   progress changes.
3. Read the available Outlook Calendar skill before remote calendar work. Use the calendar
   connector, never add calendar routes or permissions to the email provider.
4. Use `.venv/bin/python` for repository scripts. Keep disposable mailbox material only under
   `local/email-assistant/`; never put message bodies or personal event data in this public skill.

## Ownership and Ordering

Use this sequence so a failed remote write is safe to retry:

1. Read and classify exact email evidence.
2. Audit every in-progress company and role against full message bodies when the request is a
   mailbox-wide reconciliation.
3. Match one exact application and posting, or retain evidence at company scope when the posting
   remains ambiguous.
4. Update application status, progress, local `calendar.md`, and communication notes.
5. Reconcile Outlook Calendar from that validated local/evidence state.
6. Verify both surfaces and report created, updated, already-present, ambiguous, and skipped items.

The tracker transactionally couples `meta.yaml` and local `calendar.md`; Outlook is a separate
system and cannot join that transaction. Never roll back correct local evidence because Outlook is
temporarily unavailable. A repeated run must search first and converge without creating a duplicate.

## 1. Build a Complete Evidence Set

- By default, use the email assistant to discover every Outlook mail folder and sync all existing
  mail, then verify store freshness. This includes Inbox, Sent Items, Drafts, Deleted Items,
  Archive, Junk, and user-created folders that Microsoft Graph exposes. Use a bounded window only
  when the user explicitly requests one. Deleted Items covers messages still retained in that
  Outlook folder, not permanently purged mail Microsoft no longer exposes.
- For every application folder currently rolled up to `in_progress`, search
  the complete stored subject, participants, and raw body for the company name, every tracked role,
  job/requisition IDs, recruiter domains, and established thread aliases. Produce a coverage row
  for every company and role even when it has zero matches. Use `store-coverage
  --in-progress-applications` plus recruiter-domain/thread-alias query families so independent
  literals share one complete scan and retain per-folder provenance. Use conjunctive `store-search`
  only to narrow and read the exact matches. Never substitute subject-only search, snippets, or a
  title-only grep for this pass.
- Treat Drafts as unsent work. Never record them in the sent timeline or use them as proof that
  availability, a booking, or a reschedule request was sent.
- Read the exact relevant messages. Skip alerts, newsletters, generic job matches, and messages
  that are not part of an application process.
- Deduplicate messages by stable evidence before editing notes. Consolidate automated confirmation,
  organizer-invitation, reminder, and RSVP copies only when company, role, start, and meeting link
  prove they are the same occurrence; keep distinct rounds and conversations separate. Store only a
  neutral message key and concise paraphrase; never copy a full body, signature, opaque provider ID,
  or irrelevant personal detail into an application.
- For each interview fact, capture only supported fields: company, exact role or job ID, round,
  confirmed/proposed/cancelled/rescheduled state, start, end or duration, timezone, interview
  format, interviewer, recruiter, meeting link or location, and evidence date. Leave missing facts
  unknown.

## 2. Match and Update the Application

- Require one unambiguous application and posting using exact company plus role, job ID,
  recruiter domain, or established thread evidence. Company alone is insufficient when more than
  one posting could match.
- Apply per-role evidence with `status.py --update-job`; use `--update` only for evidence that
  clearly covers every posting in an application. Never let one role's rejection close an active
  sibling role.
- Record the specific hiring phase and workflow state with `status.py --update-progress` and the
  neutral `--email-ref`. Scheduling is always per-role.
- Maintain `Upcoming Events & To-Dos`, `People`, and `Email Timeline` in `notes.md` using the
  email-assistant protocol. Preserve hand-written content, deduplicate people, and update an
  existing message entry instead of appending it again.
- Put exact interview time and reschedule history in the tracker's marked local calendar entry;
  link each distinct occurrence from the ordered `jobs[].progress.calendar_items` list. Multiple
  blocks for one role—including several on the same day—remain separate entries. Do not duplicate
  timestamps into free-text metadata.

Map evidence conservatively:

- Proposed availability, an uncompleted booking link, or “we will schedule” -> no Outlook event;
  record `booking_required` or `awaiting_schedule` and an open note/calendar todo.
- Explicit confirmed start, timezone, and duration/end -> `scheduled`; eligible for Outlook
  reconciliation. Append a new occurrence for an additional confirmed block; never classify a
  parallel block as a reschedule merely because another time is already linked.
- Explicit reschedule with a confirmed replacement -> append local history and reconcile the
  replacement. Preserve the old local occurrence as superseded.
- Cancellation without a replacement -> record the cancelled occurrence; never infer rejection.

### Human-first company and interview view

The private local `calendar.md` carries one generated view for every application whose folder
rollup is `in_progress`. Refresh it with the application tracker; do not hand-maintain a second
status table.

- Lead with a top-level **Do now** table so owner work is visible before the schedule. Follow it
  with one confirmed occurrence per chronological table row using separate **Date**, **Time**,
  **Company**, **Role**, and **Prepare for** columns; never join events into a sentence or day cell.
  Waits and company commentary never compete with the preparation agenda.
- If confirmed or actionable evidence cannot yet be matched to one posting, keep it in those same
  tables labeled **posting link unresolved**. Markdown and HTML must share that supplemental item;
  never hide it in prose, omit it from one surface, or invent an application link.
- Put past confirmed occurrences and the full role/status/latest-update projection in collapsed
  detail blocks. Keep each role's canonical `status`, `progress.phase`, `progress.state`, and
  `progress.label` from `meta.yaml` there, including every posting in a multi-role folder.
- Keep the raw tracker-action/schedule sections collapsed as a reference. They must stay complete
  and machine-readable, but they do not compete visually with the preparation table. When useful,
  generate the optional offline `calendar.html` companion with
  `status.py --refresh-calendar --write --html`; it is a linked visual projection, never a source
  of truth.
- Show the latest concise company update and whether it came from explicit human input or matched
  email evidence. Use the tracker's deterministic precedence: newest standardized email-timeline
  outcome/summary, then human `next_action`, then canonical role progress. Prefer a dated
  company-scope update when new evidence is real but the exact posting is unresolved; keep the
  affected roles visibly marked unresolved instead of copying the evidence into both roles.
- Link the row to the private application notes. Preserve hand-written calendar content outside the
  generated markers, and make repeated refreshes byte-stable and duplicate-free.
- This company view is a planning projection, not an Outlook event. Only a confirmed occurrence
  satisfying the event gate below may be written to Outlook.

## 3. Search Outlook Before Every Write

1. Read mailbox settings for the preferred timezone and identify the default personal calendar
   unless the user names another calendar.
2. Search a bounded window around the confirmed time, then search by company, role, round label,
   recruiter/interviewer, and meeting link as available. Fetch every plausible match before
   deciding.
3. Treat an event as the same interview when the exact start and at least one strong identity
   signal agree: company plus role/round, organizer/interviewer, or the same meeting link. Do not
   rely on title text alone.
4. Prefer an organizer-created invitation as the canonical remote event. Leave it unchanged and
   mark application notes `calendar: confirmed`.
5. If multiple plausible events remain, create or update nothing. Report the ambiguity. Never
   delete an existing duplicate without the user's explicit approval.

## 4. Create or Update a Personal Event

Create only when no canonical event exists and the evidence explicitly confirms start, timezone,
and duration/end. Do not add external attendees; that could notify them.

Use this event shape:

- **Title:** `Interview — <Company> — <Round or Role>`
- **Time:** exact confirmed start/end in the stated timezone
- **Availability:** busy
- **Reminder:** 30 minutes before
- **Location:** explicit physical location or meeting link when supported
- **Description:** concise blocks for Company, Role, Round/format, interviewer(s), recruiter,
  a one- or two-sentence description of the interview, logistics link/location, and email evidence
  date. Omit unknown fields and mailbox-internal IDs.

Update only an unambiguous personal event created for this purpose. For an explicit reschedule,
move that event rather than creating a second one. Never edit an organizer-owned invitation,
respond to an invite, change attendees, guess a timezone/duration, or create an event from proposed
availability.

When enriching an existing personal event, preserve accurate subject/body information, meeting
links, location, reminder, and availability unless evidence explicitly changes them. Keep the body
brief and operational; application notes hold the full communication timeline.

## 5. Verify and Report

- Re-fetch every created or updated Outlook event and repeat the bounded duplicate search. The
  result must be exactly one canonical event for that confirmed occurrence.
- Run `status.py --refresh-calendar --write`, then `status.py --check-metadata` and
  `status.py --check-calendar`; after status moves, run `status.py --sync-log`. Confirm that every
  in-progress application and every one of its roles appears exactly once in the company view, then
  repeat the refresh without `--write` and require it to report no change.
- Confirm application notes contain one entry per matched message and one `People` row per person.
- Report each application/status/progress change and each Outlook event as `created`, `updated`,
  `already present`, `ambiguous`, or `skipped`, with the evidence date and a plain-language reason.
- Surface open scheduling actions prominently. Do not claim a proposed time is booked, a Draft was
  sent, or a remote event was changed when a connector call failed.

## Failure Boundaries

- Mail authentication, folder-coverage, or freshness failure: keep the review read-only and use the
  email skill's exact-window fallback; do not claim a full-mailbox audit or write from an incomplete
  evidence set.
- Ambiguous application, role, timezone, duration, or Outlook event: fail closed and ask for the
  missing fact only after exhausting repository and connector evidence.
- Local tracker write failure: do not attempt the Outlook write.
- Outlook write failure after valid local reconciliation: leave the correct local state in place,
  report the retryable remote gap, and rely on search-first idempotence during the next run.
