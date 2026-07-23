# Behavioral answer design reference

Use this reference when creating timed answer sources, changing validation rules, or coaching a
senior software engineer on delivery. `SKILL.md` remains the quickstart and hard workflow contract.

## Research basis

### Amazon senior software engineer interviews

Amazon's official [SDE III interview prep](https://amazon.jobs/content/en/how-we-hire/sde-iii-interview-prep)
says senior engineers are expected to advise their teams on technical and business issues, take a
system-wide architectural view, and build stable, scalable, maintainable systems. Its behavioral
guidance says interviewers examine the *what*, *how*, and *why* of past experiences. Candidates
should recall specific details, use metrics where applicable, cover risks, successes, failures, and
growth, and structure answers with STAR.

The official [Leadership Principles](https://www.amazon.jobs/content/en/our-workplace/leadership-principles)
define Deliver Results as focusing on key inputs and delivering them with the right quality and
timing despite setbacks. A senior Deliver Results answer should therefore make five things easy to
hear:

1. the business, customer, or operational outcome;
2. the key input or decision that unlocked progress;
3. the candidate's personal ownership and judgment;
4. how quality and blast radius were managed under constraints; and
5. quantified impact plus a durable result that outlasted the individual effort.

### STAR proportions and ownership

MIT Career Advising and Professional Development's
[STAR guidance](https://capd.mit.edu/resources/the-star-method-for-behavioral-interviews/) suggests
approximately Situation 20%, Task 10%, Action 60%, and Result 10%. The percentages are directional,
not exact quotas. MIT also recommends specific examples, clear `I` statements, and adaptable story
outlines rather than memorized scripts.

The validator therefore checks the durable signal—Action is the largest section—rather than
requiring exact percentages. Situation and Task establish only the context needed to understand the
decision. Result includes impact and, when useful, learning or what changed afterward.

### Timing and spoken language

[VirtualSpeech's speaking-rate guide](https://virtualspeech.com/blog/average-speaking-rate-words-per-minute)
places conversational speech around 120-150 words per minute and notes that complex content and
pauses slow delivery. Timed answer sources use 120 words per minute by default. The quick answer
targets 90 seconds and has a hard 75-130 second window, leaving room for natural pauses without
rewarding a thin sub-minute script. The self-contained combined answer may be longer because it
integrates the quick and short technical layers.

Word counts estimate delivery; they do not replace speaking practice. Record the answer and adjust
the configured rate if the speaker's measured pace is consistently different.

## Connected STAR paragraphs are the composition rule

The earlier summary-plus-details schema encouraged every sentence to stand alone. That made the
generated answer easy to scan but unnatural to say. The current rule keeps STAR as visual
navigation while treating each module as one spoken story:

1. render one paragraph for each STAR point as `(Situation) ...`, `(Task) ...`, `(Action) ...`,
   and `(Result) ...`; the labels are not spoken;
2. connect cause, contrast, and sequence explicitly, so removing the labels still leaves a coherent
   narrative rather than eight isolated declarations;
3. keep Situation and Task economical, make Action the largest paragraph, and make Result
   prominent enough to carry measurable or directional impact plus the durable effect;
4. state ownership precisely—on-call, assigned, volunteered, or took ownership are different facts;
5. keep short and long technical expansions additive, but provide a separate combined answer that
   rewrites quick plus short technical material into a self-contained narrative.

Do not force transitions into every sentence. Use enough natural connective language—“because,”
“so,” “after,” “while,” “which meant,” and “as a result”—to make the reasoning and sequence clear.

## Multiple projects and general-story references

A question source contains an `answers` list with at least two distinct projects. Each item names
one project, points to its factual story source, and carries its own timed modules. This provides
genuinely different options without blending their facts or making timing checks ambiguous.

Every project answer ends with two untimed reference views:

- **Timeline:** tagged chronological paragraphs that preserve causal and temporal connections.
- **Isolated focus areas:** tagged paragraphs built from a specific problem, the candidate's
  personal action, and its impact. These make technical, collaboration, judgment, and impact
  evidence easy to retrieve during follow-up.

These references are derived question-answer material. They do not authorize edits to the canonical
story bank; story-bank content changes only when the user explicitly requests them.

## Shared-source schema at a glance

Use schema version 3 under `behavioral/question-bank/sources/<question-family>.yaml`. The source
slug is company-neutral. Its ordered output aliases let one answer strategy serve the natural
general question and any equivalent company principles without duplicating answer content:

```yaml
schema_version: 3
slug: deliver-results
primary_question: Tell me about a time you delivered a result despite major obstacles.
similar_questions: [First variant, Second variant]
outputs:
  - slug: _general_03_deliver-results
    title: Tell me about a time you delivered a result despite major obstacles
  - slug: amazon-deliver-results
    title: Amazon — Deliver Results
settings:
  speaking_rate_wpm: 120
  quick_answer_target_seconds: 90
  quick_answer_min_seconds: 75
  quick_answer_max_seconds: 130
  combined_answer_max_seconds: 240
  long_path_max_seconds: 300
  max_sentence_words: 35
  banned_phrases: []
answers:
  - project_title: Project used for this answer
    source_stories: [../../story-bank/project.md]
    quick_answer:
      situation: One connected paragraph.
      task: One connected paragraph.
      action: One connected paragraph.
      result: One connected paragraph with impact.
    combined_answer:  # same four paragraph fields; self-contained
      situation: ...
      task: ...
      action: ...
      result: ...
    technical_deep_dive_short:  # additive
      bridge: If useful, I can explain ...
      situation: ...
      task: ...
      action: ...
      result: ...
    technical_deep_dive_long:  # additive; same fields as short
      bridge: If time allows, I can explain ...
      situation: ...
      task: ...
      action: ...
      result: ...
    story_references:
      timeline:  # at least four
        - {tag: "Context: area", text: "Connected chronological paragraph."}
      focus_areas:  # at least three
        - tag: "Technical: area"
          problem: Specific problem.
          action: I took a specific action.
          impact: The action improved a specific outcome.
  - project_title: A distinct second project
    # Repeat every module and both reference views.
```

The first output must use the `_general_03_<source-stem>` slug and the most natural question
framing. Later outputs use company prefixes and the company's published principle or value name. Every source
must contain at least two distinct project answers.

## Rendered Markdown layout

`answer_bank.py render` emits one file per output alias. Each project answer is a collapsed outer
`<details>` block. The summary bolds only **Answer N**; the project title follows in normal weight.
A `---` rule separates the answer header from nested sections when expanded. Nested summaries use
*italic* module labels plus word-count timing (not bold). Order inside each answer:

1. *Self-contained · quick + short deep dive*
2. *Quick answer* (with target timing)
3. *Technical deep dives* — nested group with *Deep dive · short* then *Deep dive · long*
4. *Reference · timeline*
5. *Reference · isolated problem / action / impact*

Do not use `<details open>` in generated files; expand sections at interview prep time.

## What code can and cannot validate

Hard checks are deterministic: neutral source and output naming, a leading `_general_03_` alias,
at least two distinct project answers, required modules, source-file existence, compact
one-paragraph STAR fields, quick-answer timing, maximum sentence length, Action as the largest
paragraph, minimum Result share, explicit ownership, quantified or directional impact, basic
connective-language and choppiness proxies, exact sentence reuse in additive expansions, both
general-story reference styles, and generated-file freshness.

Warnings identify review targets such as near-duplicate wording or a missing durable mechanism.
Code cannot prove that a claim is true, that a combined answer includes every intended fact, or
that prose sounds natural under real delivery. A grounded human review must therefore verify:

1. factual ownership and chronology against the source and user corrections;
2. no unexplained conclusion or missing causal step;
3. clear stakes, judgment, alternatives or constraints, personal action, impact, and learning;
4. natural spoken flow after the visual STAR labels are removed;
5. impact is memorable rather than compressed into a final throwaway sentence.
