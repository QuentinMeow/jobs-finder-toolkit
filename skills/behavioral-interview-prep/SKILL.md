---
name: behavioral-interview-prep
visibility: public
description: Prepare grounded behavioral answers from real project stories, map projects to common software engineer questions, and generate validated multi-project answers with connected STAR paragraphs, prominent impact, timed quick answers, technical expansions, and reusable story references. Use when the user asks for behavioral interview prep, STAR answers, story bank creation, leadership/conflict/failure questions, or company-specific behavioral coaching.
---

# Behavioral Interview Prep

## When to Use

Use this skill when the user asks to:
- build a behavioral story bank from their profile, resume, or raw notes
- create, expand, or backfill a project-based story-bank file
- rewrite a story into a stronger behavioral interview answer
- map one story to multiple common question families
- turn notes into validated quick, combined, and technical behavioral answers
- prepare for Amazon, Google, Meta, or other company-specific behavioral rounds
- work in `private/interviews/behavioral/story-bank/` or
  `private/interviews/behavioral/question-bank/`

## Before You Start

1. Read `AGENTS.md` for repo guardrails.
2. Read your candidate profile (`config.profile_md_path()`) unless the user already provided complete story material.
3. If the prep is company-specific, read the relevant JD file(s) — `config.applications_root()/<status>/<slug>/source/JD-<job title>.md` (one per posting) — and that folder's `notes.md` if present (the app usually lives in the `4_in_progress/<slug>/` folder by interview time).
4. Read relevant company-prefixed files in `private/interviews/behavioral/question-bank/`.
5. **Personalization / private overrides:** if this skill folder has a
   `references_private/` directory, read every file in it — those candidate-specific
   notes and examples OVERRIDE the generic examples in this SKILL.md. When it is absent
   (public / example mode), use the generic examples here and take all candidate
   specifics from `config` and the profile.
6. Read `QUESTION_BANK.md` when selecting question families, follow-ups, or company overlays.
7. Read `reference.md` before designing or changing timed answer modules or validation rules.
8. Never fabricate facts, metrics, conflict, ownership, or technologies. Reframe only what is real.
9. **Scratch stays in `tmp/`** (never the repo root or the `interviews/` tree — only finished
   story/answer files belong there). See `AGENTS.md` → "Scratch & Temporary Files".

## Core Rules

- Use real experience only.
- Write story and answer prose in first person. Use `I` for the candidate's actions and decisions;
  use `we` only for genuinely shared work or outcomes. Do not erase collaborators or claim team
  work as personal work, and do not replace `I` with a name or third-person narration.
- Keep Situation and Task brief. Action should be about half the answer.
- Quantify outcomes where honest. If no number exists, use scope, risk reduced, or workflow impact.
- End with result plus learning, especially for failure, conflict, and feedback questions.
- Sanitize confidential names when the user wants a safer external version.
- Prefer versatile stories that can answer 2-4 different question families.
- A story is easier to trust when it has one clean tension, a few concrete actions, and a
  visible outcome. If it can't be summarized clearly in one sentence, it isn't yet sharp
  enough for interview use.
- Before polishing, run a credibility pass. Flag altered or compressed chronology that changes
  causality, invented motives or impact, unsupported metrics or praise, implausible solo credit,
  unexplained role changes, and details the candidate cannot defend. Clarify, qualify, or omit
  those claims instead of making the story more impressive by inventing support.
- Prep follow-up readiness for every strong story: what alternatives you considered, how you
  measured success, what you'd do differently now, and how stakeholders reacted / how you kept
  alignment.
- Treat project story-bank files as the canonical source of truth for behavioral stories. Question-based answer files should be shorter derived views that select and summarize only the relevant parts.
- **Story-bank content is read-only by default.** Never create, expand, backfill, correct, or
  rephrase a file under `behavioral/story-bank/` unless the user specifically asks to change the
  story bank. Moving an unchanged file during an explicitly requested folder migration is allowed.
- A story-bank file is one project or major workstream, not one interview question. Make it intentionally long and chronological, with details from all useful aspects: context, stakes, ownership, constraints, technical decisions, execution, collaboration, conflict, mistakes, trade-offs, results, metrics, and lessons.
- In story-bank detail sections, every paragraph should begin with a short parenthesized tag that combines targeting area and content summary, such as `(Ambiguity - monolith-to-microservices split had unclear service boundaries)` or `(Influence - component owners needed reproducible evidence before engaging)`.
- If user-provided facts for a question answer differ from or extend a story-bank file, use the
  user's correction in the question source, flag the mismatch, and leave the story bank unchanged
  unless the user also asks to update it.
- Similar or near-identical behavioral questions share one company-neutral YAML source under
  `behavioral/question-bank/sources/`. Name the source after the question family, such as
  `deliver-results.yaml`, never after one company's principle.
- Every source declares an ordered `outputs` list. The first output slug must be
  `_general_03_<source-stem>` (for example, `_general_03_deliver-results`). Add one
  company-prefixed output alias per matching principle or value, such as
  `amazon-deliver-results`; all aliases render from the same answers.
- Hand-maintained question-bank Markdown uses numbered `_general_` prefixes by purpose:
  - `_general_01_<topic>.md` — non-obvious or special-purpose answers (for example, Tell me about
    yourself); no YAML source; exempt from STAR/timing validation.
  - `_general_02_story_<project>.md` — reusable general project story packs (not tied to one
    question family); hand-maintained.
  - `_general_03_<question-family>.md` — generated from YAML; behavioral STAR answers.
  - `<company>-<principle-or-value>.md` — company overlays generated from the same YAML (for example,
    `amazon-deliver-results.md`).
- In interview answers, avoid employer-internal product codenames when a generic description is
  clearer: say **image GC and cross-region replication service**, **self-hosted container registry
  (similar to ECR)**, and **remote shell for Kubernetes containers (similar to kubectl exec)** instead
  of internal service names.
- Every generated question source must contain at least two answer options. Store them as an
  `answers` list; every item must have a distinct `project_title` and use one project/angle.
- In persisted answer-bank Markdown files, keep the `#` title visible. Wrap each project answer in
  a collapsed outer `<details>` block whose summary uses **Answer N** in bold plus the project
  title in normal weight, then a horizontal rule before nested sections. Nested module summaries
  use *italic* labels and word-count timing; do not bold nested titles.
- When the user wants bullet-style answers, make each bullet start with a short parenthesized tag like `(Signal)`, `(Context)`, `(Judgment)`, or `(Impact)`.
- Do not force STAR onto `Tell me about yourself`; use `present -> past -> future` there even if
  the rest of the bank is STAR-based. End the concise default answer with a natural bridge that
  offers optional technical follow-ups, such as, "If useful, I can go deeper on either project."
- Every project answer has four modules: a self-contained `quick_answer`, a self-contained
  `combined_answer` that integrates the quick answer with the short deep-dive material, an additive
  `technical_deep_dive_short`, and an additive `technical_deep_dive_long`.
- The quick answer targets 90 seconds and must be between 75 and 130 seconds at the configured
  speaking rate. Default to a conservative 120 words per minute. This gate applies to chat answers
  and proposed packages too; count the actual words instead of merely declaring timing settings.
- Render each module as four compact visual paragraphs: `(Situation) ...`, `(Task) ...`,
  `(Action) ...`, `(Result) ...`. Do not render large STAR headings or isolated summary lines.
  The labels are navigation aids and are not spoken.
- Each module must sound like one connected story when the labels are removed. Use cause, contrast,
  and sequence transitions such as “because,” “so,” “after,” “while,” and “as a result.” Do not
  produce a stack of disconnected short sentences.
- Make personal ownership explicit and factually correct: distinguish being on-call, being assigned,
  volunteering, and taking ownership. Never replace one with another because it sounds stronger.
- Impact is a primary answer component, not an afterthought. State who or what benefited, the
  measurable or directional change, the risk avoided, and the durable effect. Give Result enough
  space to be memorable while keeping Action the largest paragraph.
- Introduce expansions with a natural bridge such as, "If useful, I can explain how I made that
  rollout safe." The bridge is navigation text, not part of STAR timing.
- Append two general-story references to every project answer: a tagged timeline view with explicit
  logical connections, and tagged isolated focus areas. Every isolated focus area must state the
  specific problem, what the candidate personally did, and the impact.
- For company culture/principle prep, optimize for interview-time navigation: create exactly one
  company-prefixed generated answer file per principle or value, not one giant aggregate file.
- Enumerate every requested principle before drafting. Generate a principle source only when at
  least two distinct grounded stories support it; list unsupported principles as evidence gaps
  instead of inventing a second story or silently omitting them.
- A principle package is complete only when every proposed file has full source-valid modules and
  both reference views. Do not substitute an outline, “combined-answer additions,” or a module
  summary for the actual answer content. If the package is large, finish it in explicit waves.
- Put each visual STAR label at the start of its spoken paragraph, for example
  `(Situation) The service...`. Never emit a standalone STAR label or summary sentence.
- Avoid generic section titles that only describe the format in interview-time prep files. Use a descriptive project-and-angle heading, then start the STAR labels immediately.
- Use plain, spoken language: familiar words, short sentences, contractions where natural, and one
  idea per sentence. Avoid ornamental wording and interview jargon.

## Default Workflow

1. Identify the input mode:
   - `raw story notes`
   - `profile or resume bullets`
   - `project story-bank creation or expansion`
   - `specific question`
   - `company-specific prep`
2. Select grounded source material:
   - derive or select the relevant project/workstream
   - read the relevant story-bank file and other user-provided evidence
   - do not modify story-bank content unless the user explicitly requested that modification
   - preserve source-grounded details and mark unknowns or source conflicts instead of inventing them
3. Map each story to likely question families.
4. For a specific behavioral question, write the source YAML before the Markdown:
   - choose a company-neutral question-family slug and primary natural question
   - list similar question variants and ordered `_general_03_` / company-prefixed output aliases
   - create an `answers` list with at least two titled projects
   - create a self-contained `quick_answer` targeting 90 seconds within the 75-130 second gate
   - create a self-contained `combined_answer` that integrates the quick and short-deep-dive facts
   - create non-repeating short and long additive technical expansions
   - write one connected paragraph per STAR point and make impact explicit
   - add both tagged general-story reference styles for every project
   - validate the YAML, render the Markdown, and check that generated output is current
5. Tailor the framing:
   - Amazon: LP fit, ownership, customer impact, dive deep, delivery
   - Google: collaboration, ambiguity, learning, leadership, judgment
   - Meta: impact, speed, iteration, prioritization, ownership
6. Run a final quality check:
   - answers the question asked
   - action-heavy and specific
   - believable under follow-up
   - passes the credibility review for chronology, causality, motives, metrics, role, and credit
   - length fits spoken delivery
   - every quick answer's measured word count passes the 75-130 second gate
   - every proposed source passes `answer_bank.py validate`; for response-only work, validate
     temporary sources under top-level `tmp/` and delete them afterward
7. If persisting to an answer bank:
   - create or update the neutral question-family YAML source
   - validate it before rendering
   - render every declared output alias deterministically
   - run the private content tests under `behavioral/question-bank/tests/`
   - wrap each answer and nested module in collapsed `<details>` blocks (combined → quick → deep dives → references)

## File Location

All real behavioral products live under `private/interviews/behavioral/`.
Use `private/interviews/behavioral/question-bank/` for question-based answers. Specific behavioral
answers are generated Markdown aliases backed by shared, company-neutral YAML under
`question-bank/sources/`. Generated behavioral question files use `_general_03_<family>.md`;
company overlays use `<company>-<principle>.md`. Hand-maintained files use `_general_01_` or
`_general_02_story_` prefixes (see Core Rules). Content tests live under `question-bank/tests/`.
Use `private/interviews/behavioral/story-bank/` for canonical project-based stories.
Each file should be one project or major workstream, for example
`private/interviews/behavioral/story-bank/payments-microservices-migration.md`.

Reusable company-principle answers belong in the answer bank and use a company-prefixed output
name, such as `question-bank/amazon-deliver-results.md`, while the shared source remains
`question-bank/sources/deliver-results.yaml`. Keep company-specific behavioral products in this
same question bank; use company-prefixed filenames instead of a separate company folder.

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

When the user explicitly asks to add story-bank coverage and the material is incomplete, a useful
skeleton should list known facts, chronological paragraphs, likely question families, reusable
proof points, and explicit gaps to fill later. Do not create it during question-answer work alone.

## Preferred Output

Only when the user explicitly asks to create or change a project story-bank file, prefer this
structure:

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

#### Quick answer
[(Situation), (Task), (Action), and (Result) paragraphs; connected and self-contained]

#### Self-contained combined answer
[quick answer plus short technical detail, rewritten as one connected answer]

#### Technical deep dive - short
[optional additive expansion containing only new detail]

#### Technical deep dive - long
[optional additive expansion containing only new detail]

#### General story reference - timeline
[tagged chronological paragraphs with cause-and-effect transitions]

#### General story reference - isolated areas
[tagged problem -> personal action -> impact paragraphs]
```

When the user gives a single story and wants question mapping, use:

```markdown
## Best-fit Questions
- [Question family 1]
- [Question family 2]
- [Question family 3]

## Recommended Angle
[Why this story works for those questions]

## Quick answer
...

## Self-contained combined answer
...

## Technical deep dive - short
...

## Technical deep dive - long
...
```

Specific behavioral answer Markdown is rendered from a shared source's output aliases. Prefer this
generated structure:

```markdown
# [Question or principle name]

## Similar questions
- [variant]
- [variant]

## Answer 1 — [Project title]

<details>
<summary><strong>Answer 1</strong> — [Project title]</summary>

---

<details>
<summary><em>Self-contained · quick + short deep dive</em> · [N] words / about [M:SS]</summary>

[(Situation), (Task), (Action), and (Result) paragraphs that integrate both layers.]

</details>

<details>
<summary><em>Quick answer</em> · [N] words / about [M:SS] · target 1:30</summary>

(Situation) [Connected setup paragraph.]

(Task) [Accurate ownership and responsibility paragraph.]

(Action) [Largest paragraph with reasoning, decisions, and execution.]

(Result) [Prominent measurable/directional impact and durable effect.]

</details>

<details>
<summary><em>Technical deep dives</em></summary>

<details>
<summary><em>Deep dive · short</em> · [N] words / about [M:SS] · new material</summary>

[Natural bridge.]
[Compact STAR paragraphs containing only new detail.]

</details>

<details>
<summary><em>Deep dive · long</em> · [N] words / about [M:SS] · new material</summary>

[Natural bridge.]
[Deeper compact STAR paragraphs containing only new detail.]

</details>

</details>

<details>
<summary><em>Reference</em> · timeline</summary>

(Context: [area]) [Paragraph.]
(Execution: [area]) [Paragraph.]
(Impact: [area]) [Paragraph.]

</details>

<details>
<summary><em>Reference</em> · isolated problem / action / impact</summary>

(Technical: [area]) [Problem.] To address that, [personal action.] As a result, [impact.]

</details>

</details>
```

For `_general_01_tell-me-about-yourself.md`, use `present -> past -> future` and hand-maintain the
Markdown. It may use optional follow-up modules, but it is not a STAR answer and must not be placed
under `question-bank/sources/`. In chat and persisted versions, include an explicit spoken bridge
from the default answer to those optional follow-ups.

Company culture/principle answers use the same generated structure as other specific behavioral
questions. Keep one principle per company-prefixed file, with at least two titled project answers.

## Answer Module Guidance

- `Quick answer`: the self-contained default. Target 90 seconds; enforce 75-130 seconds. Keep setup
  short, make Action the largest paragraph, and give Result explicit impact and durable effect.
- `Self-contained combined answer`: integrates the quick answer and short technical material into
  one smooth answer. Do not mechanically concatenate two scripts.
- `Technical deep dive - short`: an optional follow-up containing only detail not already spoken
  in the quick answer.
- `Technical deep dive - long`: an alternative expanded follow-up containing only new detail.
  Add trade-offs, failure modes, stakeholder handling, and lessons.
- `General story references`: append both a connected timeline and isolated problem/action/impact
  views. These are reference material, not timed scripts.

## Special Cases

- `Failure`: include ownership, recovery, and learning. Do not make the story sound like somebody else caused everything.
- `Conflict`: focus on professional disagreement, alignment steps, and improved working relationship.
- `Weakness`: use a real but manageable weakness, then show a concrete improvement plan and evidence of progress.
- `Tell me about yourself`: use `_general_01_<topic>.md`; use `present -> past -> future`, not STAR,
  and end the default answer with a bridge to optional technical follow-ups.
- `Why this company`: connect the user's background to the team's work and mission. Avoid generic praise.

## Optional Persistence

If the user wants prep saved for a specific application:
- save reusable company-specific answers in `private/interviews/behavioral/question-bank/` with a
  company-prefixed output alias backed by a neutral shared source
- change `private/interviews/behavioral/story-bank/` only when the user explicitly asks
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
- quick answer: connected, self-contained STAR paragraphs with prominent impact
- combined answer: a natural rewrite that integrates quick and short technical detail
- short expansion: new technical detail only, used after asking permission
- long expansion: alternative deeper detail, still without repeating the core
- story references: one connected timeline plus isolated problem/action/impact areas

## Final Checks

- Would this still sound true if the interviewer drilled into the technical details?
- Are chronology and causality explicit, with unsupported motives, metrics, praise, or solo credit
  qualified or removed?
- Is the ownership wording exact — on-call, assigned, volunteered, or took ownership?
- Does each answer read as one connected spoken story after removing the visual STAR labels?
- Is the impact prominent, concrete, and tied to a beneficiary, risk, metric, or durable change?
- Is there more action than setup?
- Does the quick answer target 90 seconds and stay within 75-130 seconds?
- Is the combined answer self-contained instead of a mechanical concatenation?
- Do the technical expansions add detail instead of repeating the quick answer?
- Does every project answer end with both required tagged general-story reference styles?
- Does every `Tell me about yourself` answer include a natural bridge to optional technical depth?
- Does the neutral source start with `_general_03_<source-stem>` and include every applicable
  company-prefixed alias?
- Are there at least two distinct project answers?
- Did the YAML validate and generate every current Markdown alias exactly?
- Did you tailor the framing without changing the facts?
