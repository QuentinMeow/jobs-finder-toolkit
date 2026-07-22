---
name: behavioral-interview-prep
visibility: public
description: Prepare project-based behavioral story banks from real experience, map stories to common software engineer behavioral question categories, and rewrite answers into reusable answer cores with optional short and long deep dives. Use when the user asks for behavioral interview prep, STAR answers, story bank creation, leadership/conflict/failure questions, or company-specific behavioral coaching.
---

# Behavioral Interview Prep

## When to Use

Use this skill when the user asks to:
- build a behavioral story bank from their profile, resume, or raw notes
- create, expand, or backfill a project-based story-bank file
- rewrite a story into a stronger behavioral interview answer
- map one story to multiple common question families
- turn notes into an `intro version`, a reusable high-level STAR answer, and optional short or long technical deep dives
- prepare for Amazon, Google, Meta, or other company-specific behavioral rounds
- work in `interviews/behavioral-story-bank/`, `interviews/behavioral-answer-bank/`, or `interviews/company-specific/<company>/behavioral/`

## Before You Start

1. Read `AGENTS.md` for repo guardrails.
2. Read your candidate profile (`config.profile_md_path()`) unless the user already provided complete story material.
3. If the prep is company-specific, read the relevant JD file(s) — `config.applications_root()/<status>/<slug>/source/JD-<job title>.md` (one per posting) — and that folder's `notes.md` if present (the app usually lives in the `4_in_progress/<slug>/` folder by interview time).
4. If a company-specific folder exists, read relevant files under `interviews/company-specific/<company>/behavioral/` (real interview products mount under `private/interviews/...`; see `AGENTS.md` → "Public vs Private").
5. **Personalization / private overrides:** if this skill folder has a
   `references_private/` directory, read every file in it — those candidate-specific
   notes and examples OVERRIDE the generic examples in this SKILL.md. When it is absent
   (public / example mode), use the generic examples here and take all candidate
   specifics from `config` and the profile.
6. Read `QUESTION_BANK.md` when selecting question families, follow-ups, or company overlays.
7. Never fabricate facts, metrics, conflict, ownership, or technologies. Reframe only what is real.
8. **Scratch stays in `tmp/`** (never the repo root or the `interviews/` tree — only finished
   story/answer files belong there). See `AGENTS.md` → "Scratch & Temporary Files".

## Core Rules

- Use real experience only.
- Default to `I` instead of `we`. Mention team context only when needed.
- Keep Situation and Task brief. Action should be about half the answer.
- Quantify outcomes where honest. If no number exists, use scope, risk reduced, or workflow impact.
- End with result plus learning, especially for failure, conflict, and feedback questions.
- Sanitize confidential names when the user wants a safer external version.
- Prefer versatile stories that can answer 2-4 different question families.
- A story is easier to trust when it has one clean tension, a few concrete actions, and a
  visible outcome. If it can't be summarized clearly in one sentence, it isn't yet sharp
  enough for interview use.
- Prep follow-up readiness for every strong story: what alternatives you considered, how you
  measured success, what you'd do differently now, and how stakeholders reacted / how you kept
  alignment.
- Treat project story-bank files as the canonical source of truth for behavioral stories. Question-based answer files should be shorter derived views that select and summarize only the relevant parts.
- A story-bank file is one project or major workstream, not one interview question. Make it intentionally long and chronological, with details from all useful aspects: context, stakes, ownership, constraints, technical decisions, execution, collaboration, conflict, mistakes, trade-offs, results, metrics, and lessons.
- In story-bank detail sections, every paragraph should begin with a short parenthesized tag that combines targeting area and content summary, such as `(Ambiguity - monolith-to-microservices split had unclear service boundaries)` or `(Influence - component owners needed reproducible evidence before engaging)`.
- Story banks may start as minimal skeletons. When a question answer contains new manually added facts, better phrasing, or extra detail that is not already in the relevant story-bank file, update the story bank first or immediately after updating the answer.
- If saving into an answer-bank folder, default to one numbered file per question.
- Reserve `00` for `Tell me about yourself`.
- One question file can contain multiple answer options when different projects fit the same prompt well.
- In persisted answer-bank Markdown files, keep the `#` title visible and wrap each main section in a collapsible `<details>` block. Each answer option, such as `Answer Option A` and `Answer Option B`, should be its own folded section.
- When the user wants bullet-style answers, make each bullet start with a short parenthesized tag like `(Signal)`, `(Context)`, `(Judgment)`, or `(Impact)`.
- Do not force STAR onto `Tell me about yourself`; use `present -> past -> future` there even if the rest of the bank is STAR-based.
- Prefer one reusable answer core over separate `1 minute`, `2 minute`, and `5 minute` scripts. The core should be high-level enough to speak shorter or longer depending on interviewer pacing.
- Use deep dives as optional follow-up modules. Introduce them with a bridge like, "If useful, I can go deeper on the technical design."
- For company culture/principle prep, optimize for interview-time navigation: create exactly one short numbered file per principle or value, not one giant aggregate file.
- Any tag, initial summary, or STAR label that introduces verbal talking material must be on its own line. Put the actual spoken answer text on the next line so it is easy to spot during an interview.
- Treat standalone STAR labels as header-like text with no trailing colon.
- Avoid generic section titles that only describe the format in interview-time prep files. Use a descriptive project-and-angle heading, then start the STAR labels immediately.

## Default Workflow

1. Identify the input mode:
   - `raw story notes`
   - `profile or resume bullets`
   - `project story-bank creation or expansion`
   - `specific question`
   - `company-specific prep`
2. Build or update the story bank:
   - derive or select the relevant project/workstream
   - create or update one long chronological story file per project
   - consolidate facts from profile, raw notes, existing answer files, and company-specific variants
   - preserve source-grounded details and mark unknowns as gaps instead of inventing them
3. Map each story to likely question families.
4. Generate reusable answer modules:
   - `Intro version`: one concise project/story summary for quick setup or story selection
   - `Reusable STAR answer`: high-level Situation, Task, Action, Result that can be spoken shorter or longer
   - `Technical deep dive - short`: optional follow-up with the most important implementation details
   - `Technical deep dive - long`: optional follow-up with trade-offs, failure modes, stakeholder handling, and lessons
5. Tailor the framing:
   - Amazon: LP fit, ownership, customer impact, dive deep, delivery
   - Google: collaboration, ambiguity, learning, leadership, judgment
   - Meta: impact, speed, iteration, prioritization, ownership
6. Run a final quality check:
   - answers the question asked
   - action-heavy and specific
   - believable under follow-up
   - length fits spoken delivery
7. If persisting to an answer bank:
   - create or update numbered files
   - keep formatting consistent across files
   - allow multiple answer options in one file when helpful
   - wrap persisted top-level sections in `<details>` blocks so the user can expand only the section they want to review

## File Location

Use `interviews/behavioral-answer-bank/` for reusable, company-neutral answers.
Use `interviews/behavioral-story-bank/` for canonical project-based stories.
Each file should be one project or major workstream, for example
`interviews/behavioral-story-bank/payments-microservices-migration.md`.
Use `interviews/company-specific/<company>/behavioral/` for company-specific
behavioral prep, recruiter screens, interview-loop notes, and tailored answer
variants. Related coding practice for the same company belongs in
`interviews/company-specific/<company>/coding/`.

For company culture principles or values, use one file per principle:
`interviews/company-specific/<company>/behavioral/NN-principle-name.md`.
If the company publishes 11 principles, create exactly 11 files. Keep each file
short enough to scan during an interview.

## Story Bank Coverage

Aim for 8-10 reusable project stories covering:
1. Leadership or initiative
2. Conflict or disagreement
3. Failure or mistake
4. Ambiguity or incomplete information
5. Influence without authority
6. Cross-functional collaboration
7. Customer or stakeholder focus
8. Tight deadline or prioritization
9. Learning or adaptation
10. Technical judgment or trade-offs

For canonical question families and company overlays, read [QUESTION_BANK.md](QUESTION_BANK.md).

When coverage is incomplete, create skeleton files anyway if there is enough real
material. A useful skeleton should list known facts, chronological paragraphs,
likely question families, reusable proof points, and explicit gaps to fill later.

## Preferred Output

When saving a project story-bank file, prefer this structure:

```markdown
# [Project or workstream name]

## Story Index

- Themes: leadership, ambiguity, technical judgment
- Best question fits: taking initiative; operating in ambiguity; difficult trade-off
- Strongest proof points: [metric or concrete outcome]; [workflow or artifact]; [learning]
- Known gaps to fill: [missing date/scope/stakeholder/detail]

## Chronological Story Detail

**(Context - [summary of what this paragraph explains])**
[Long factual paragraph.]

**(Task - [summary of responsibility or bar])**
[Long factual paragraph.]

**(Decision - [summary of trade-off])**
[Long factual paragraph.]

**(Execution - [summary of implementation detail])**
[Long factual paragraph.]

**(Collaboration - [summary of people/stakeholders])**
[Long factual paragraph.]

**(Setback - [summary of what did not go as planned])**
[Long factual paragraph.]

**(Result - [summary of impact])**
[Long factual paragraph.]

**(Learning - [summary of durable lesson])**
[Long factual paragraph.]

## Answer Generation Notes

- For initiative answers, emphasize ...
- For ambiguity answers, emphasize ...
- For failure answers, include ...
```

The chronological detail is intentionally verbose because it is the foundation.
Do not compress it into a polished interview answer. Derived question answers
should use this file as the foundation, then pick only the few paragraphs needed
for the specific prompt.

When building a high-level story bank in chat, use this structure:

```markdown
## Story Bank

### [Short story name]
- Themes: leadership, ambiguity, cross-functional collaboration
- Best question fits: taking initiative; influencing without authority; hard decision
- Hook: [1-sentence spoken opener]
- Situation: [2-3 sentences]
- Task: [your responsibility]
- Actions:
  - [action 1]
  - [action 2]
  - [action 3]
- Result: [quantified outcome]
- Learning: [what changed afterward]

#### Intro version
[one-sentence story/project summary]

#### Reusable STAR answer
[high-level answer core]

#### Technical deep dive - short
[optional focused follow-up]

#### Technical deep dive - long
[optional expanded follow-up]
```

When the user gives a single story and wants question mapping, use:

```markdown
## Best-fit Questions
- [Question family 1]
- [Question family 2]
- [Question family 3]

## Recommended Angle
[Why this story works for those questions]

## Intro version
...

## Reusable STAR answer
...

## Technical deep dive - short
...

## Technical deep dive - long
...
```

When saving a persisted answer bank to files, prefer this structure:

```markdown
# [Question text]

<details>
<summary><strong>What the recruiter is actually looking for</strong></summary>

- (Signal) ...
- (Signal) ...

</details>

<details>
<summary><strong>Answer Option A - [Project or angle]</strong></summary>

### Why this answer works
- (Fit) ...
- (Fit) ...

### Intro version
- (Hook) ...

### Reusable STAR answer

#### Situation
- (Context) ...

#### Task
- (Ownership) ...

#### Action
- (Judgment) ...
- (Execution) ...

#### Result
- (Impact) ...
- (Learning) ...

### Technical deep dive - short
...

### Technical deep dive - long
...

</details>

<details>
<summary><strong>Answer Option B - [Optional second project]</strong></summary>

...

</details>
```

For `00-tell-me-about-yourself.md`, prefer this structure instead:

```markdown
# Tell me about yourself

<details>
<summary><strong>What the recruiter is actually looking for</strong></summary>

- (Signal) ...

</details>

<details>
<summary><strong>Answer Option A - [Default version]</strong></summary>

### Why this answer works
- (Fit) ...

### Intro version
- (Present) ...
- (Project) ...
- (Future) ...

### Reusable answer core
- (Present) ...
- (Past) ...
- (Future) ...

### Technical deep dive - short
...

### Technical deep dive - long
...

</details>
```

When saving company culture/principle answers, prefer this compact structure:

```markdown
# NN. [Company Principle]

## [Project or workstream] - [specific story angle or outcome]

**Situation**
[brief setup]

**Task**
[your responsibility]

**Action**
[2-4 action-heavy sentences]

**Result**
[impact plus learning]

## Add More Examples

### Answer Option B - [Story]

**Situation**

**Task**

**Action**

**Result**
```

Avoid recruiter-analysis sections, long deep dives, and full indexes in these
principle files unless the user asks for them. The goal is fast navigation while
speaking.

## Answer Module Guidance

- `Intro version`: one sentence or a few short bullets. Use it to select or set up the story, not to answer the whole question.
- `Reusable STAR answer`: the default answer core. Keep setup short, make Action the largest section, and include result plus learning.
- `Technical deep dive - short`: a focused follow-up for the strongest technical design points. Keep it compact enough for an interviewer who asks one follow-up.
- `Technical deep dive - long`: an expanded follow-up for deep technical probing. Add trade-offs, failure modes, stakeholder handling, and lessons without repeating the whole answer core.

## Special Cases

- `Failure`: include ownership, recovery, and learning. Do not make the story sound like somebody else caused everything.
- `Conflict`: focus on professional disagreement, alignment steps, and improved working relationship.
- `Weakness`: use a real but manageable weakness, then show a concrete improvement plan and evidence of progress.
- `Tell me about yourself`: not full STAR; use `present -> past -> future`. Keep a project-summary intro, then a reusable high-level answer core, then optional short/long technical deep dives.
- `Why this company`: connect the user's background to the team's work and mission. Avoid generic praise.

## Optional Persistence

If the user wants prep saved for a specific application:
- prefer `interviews/company-specific/<company>/behavioral/` for reusable company-specific prep
- prefer `interviews/behavioral-story-bank/` when saving or expanding source project stories that multiple answer files will reuse
- update `config.applications_root()/<status>/<slug>/notes.md` only when the note is tied to one application record
- add a `## Behavioral Prep` section rather than editing the base profile
- do not edit your candidate profile (`config.profile_md_path()`) unless the user explicitly asks

## Example

Raw input:
- "Led migration of a monolithic payments service into independently deployable microservices, standardized deploys with CI/CD automation, and clarified service ownership boundaries across teams."

Strong mapping:
- leadership / initiative
- technical judgment / trade-offs
- ambiguity / ownership boundaries
- cross-functional collaboration

Strong answer-module shape:
- intro: one project summary
- reusable STAR answer: problem, action, result, learning
- optional deep dive: technical details only when invited

## Final Checks

- Would this still sound true if the interviewer drilled into the technical details?
- Is your role explicit?
- Is the result concrete?
- Is there more action than setup?
- Did you tailor the framing without changing the facts?
