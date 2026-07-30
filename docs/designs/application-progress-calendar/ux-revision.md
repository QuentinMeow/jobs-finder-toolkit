# Calendar UX revision after owner review

**Status:** implemented on 2026-07-22. This revision supersedes the original
calendar presentation and extends its workflow coverage; the original design
remains the record of why progress and scheduling are stored separately.

The first calendar was mechanically safe but human-hostile: event rows did not
show their time, todos did not state the action or deadline, and a multi-line
machine payload dominated the source. This revision makes the planning view an
agenda and task list first, with repository state remaining behind the link.

## Research translated into product rules

The useful convergence across calendar, task-list, accessibility, and ATS
guidance is to keep the overview compact while preserving a deeper record:

- The [GOV.UK task-list guidance](https://design-system.service.gov.uk/components/task-list/)
  recommends short task names, optional one-sentence hints only when needed,
  visible statuses, sensible grouping, and a linked row. Calendar todos now
  lead with a short verb and place role context behind one link.
- The [W3C reminder pattern](https://www.w3.org/WAI/WCAG2/supplemental/patterns/o7p07-reminders/)
  treats appointments and deadlines as distinct time-bound information that
  should reduce transcription and memory load. Calendar events therefore show
  exact local time; tasks show a due or follow-up date when one exists.
- Microsoft's [Mail and Calendar design history](https://microsoft.design/articles/digital-design-is-never-done-evolving-windows-10-mail-and-calendar/)
  pairs a compact event list with a detailed daily view. This Markdown version
  uses the same information hierarchy: one-line agenda row, linked detail.
- [Greenhouse's interview-plan model](https://support.greenhouse.io/hc/en-us/articles/115002194903-Interview-plan-overview)
  separates a broad stage from one or more interviews inside it, while
  [Workable's pipeline guidance](https://help.workable.com/hc/en-us/articles/4413312707991-Recruiting-pipeline-best-practices)
  recommends a small number of reporting stages and warns against turning
  scheduling or feedback tasks into stages. The tracker keeps broad phases,
  uses `label` for employer wording, and uses workflow state plus calendar
  action text for the work within a phase.

## Human calendar contract

Every managed row now answers the minimum useful questions in scan order:

| Kind | First signal | Context | Optional timing |
| --- | --- | --- | --- |
| Confirmed event | Bold local date and time | Company + role link, then phase/label | End time |
| Owner todo | Bold verb-led action | Company + role link, then phase/label | Due date |
| Waiting item | Bold wait status | Company + role link, then phase/label | Follow-up date |

The full application context lives in linked `notes.md` when present, otherwise
linked `meta.yaml`. The marker below the row is a single hidden JSON comment.
`status.py --refresh-calendar [--write]` upgrades existing managed rows without
changing progress, while unmarked personal text remains byte-preserved.

## Interview-process transition coverage

The tracker represents phases broadly and captures the changing owner/employer
responsibility in `state`. The table shows how unusual company processes fit
without adding one-off enums.

| Process moment | Phase | State now | Typical next state |
| --- | --- | --- | --- |
| Application submitted | `application_review` | `waiting_employer` | recruiter action or closure |
| Availability or booking requested | current interview phase | `booking_required` | `awaiting_schedule` |
| Exact time confirmed | current interview phase | `scheduled` | `awaiting_result` |
| Employer or candidate needs a new time | current interview phase | `reschedule_required` | `reschedule_pending` → `scheduled` |
| Take-home, coding test, presentation, or portfolio work assigned | `assessment` or current phase | `action_required` | `in_progress` → `awaiting_result` |
| Recruiter, hiring-manager, technical, executive, or domain conversation | matching broad phase; employer name in `label` | scheduling flow | `awaiting_result` or next phase |
| Multi-round virtual or onsite loop | `interview_loop`; round details behind the role link | scheduling flow | `awaiting_result` |
| No-show or unanswered next-step question | current phase | `follow_up_required` | reschedule, wait, or closure |
| Team selection | `team_match` | `waiting_employer` or scheduling flow | offer or closure |
| References requested | `reference_check` | `action_required` | `waiting_employer` |
| Offer review, negotiation, or deadline | `offer`; exact wording in `label` | `decision_required`, `in_progress`, or `waiting_employer` | pre-employment or closure |
| Background screening | `background_check` | action/wait states | work authorization or onboarding |
| Visa or employment-authorization paperwork | `work_authorization` | action/wait states | onboarding |
| Accepted offer and pre-start work | `onboarding` | action/wait states | complete outside the interview tracker |
| Headcount freeze or explicit employer hold | current phase | `paused` | resume, follow up, or closure |
| Rejection, withdrawal, filled/cancelled role, declined/rescinded offer | retain last phase; exact reason in `label` | `closed` via the coarse-status command | terminal |

Cancellation of one calendar occurrence is not application closure. It records
the cancelled time in history and creates the next action; explicit evidence is
still required to close the role. A time passing likewise never fabricates an
interview outcome.

## Human questions / additional tasks

*Owner space — questions are answered in place and additional work is routed
through the repository queues.*

- (none right now)
