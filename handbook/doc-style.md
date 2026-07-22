# Design-doc writing style

Rules for every document under `docs/design/`. Purpose: the owner (or any
cold reader) must be able to open any single section and understand it
without having read the rest of the family, without decoding reference
codes, and without following links just to parse a sentence.

## 1. Every section stands alone

- A section opens by stating, in one or two sentences, what it covers and
  why the reader should care — even if that repeats a sentence from the
  intro.
- If a section depends on a concept defined elsewhere, restate the concept
  in half a sentence **and** link to the full definition. The link is a
  convenience, never a requirement: `…the build ledger (the record of which
  fetches have already been processed — see [Write discipline](01-store-core.md#7-write-discipline--concurrency))…`
- Never write a sentence whose meaning depends on a bare pointer the reader
  can't click or expand in place. Banned forms: `per §6b`, `see 01 §2`,
  `rule R5 applies`, `as in P1`.

## 2. References are clickable or spelled out — never coded

- Cross-references are markdown links with descriptive text:
  `[the store's zone contracts](01-store-core.md#1-zones-and-their-contracts)`,
  not `01 §1`, not `doc 01`.
- No invented identifier systems (finding codes like `AE-7`, reviewer
  initials, bare rule numbers). When a rule or principle needs a handle,
  give it a **descriptive name** ("the capture-before-parse rule",
  "raw-is-sacred") and use the name.
- The one sanctioned label family is decision IDs (`Q-A`, `Q-B`, …),
  because the owner uses them as answer handles ("Q-I: yes"). Every use of
  a decision ID outside its own block must link to the block and gloss it
  in a few words: `gated on the polling-cadence decision
  ([Q-I](02-job-postings-pipeline.md#q-i-adopt-a-scheduled-board-polling-habit))`.

## 3. Review findings are prose, not codes

Findings tables name the reviewing lens in words ("the adversarial review of
the email design", "the token-economics review"), state the finding as a
complete plain-language sentence a cold reader can evaluate, and link the
resolution to the section that implements it. A reader must never need a
legend.

## 4. Figures: every concept diagram ships in BOTH forms

- Anything that shows **flow, dependency, or relationships** appears
  twice, back to back: a ```mermaid``` diagram (GitHub renders these
  natively) **and** an ASCII version in a plain code block labeled "Same
  picture, plain text". Mermaid auto-layout can scatter; the ASCII version
  is the layout the author controls — readers use whichever renders better
  in their viewer.
- ASCII versions use box-drawing characters with aligned columns and short
  labels — never sprawling arrow art. If the ASCII version needs more than
  ~20 lines, the diagram is too complex: split it.
- Plain fenced code blocks alone (no Mermaid twin) are for things that
  literally *are* monospaced text: directory trees, file contents,
  commands.
- Every figure gets a one-line caption immediately above or below stating
  the single takeaway ("Takeaway: only raw/ is irreplaceable; everything in
  the shaded box can be deleted and rebuilt from it.").

## 5. Open questions are self-contained decision blocks

Every question the owner must answer uses this exact shape, under its own
`### Q-X: <question in plain words>` heading:

```markdown
### Q-X: <the question, phrased so yes/no/option-letter is a valid answer>

**Decide by:** <which stage/PR is blocked> · **Default if unanswered:** <what happens on silence>

**Context.** 2–4 sentences of background sufficient to decide — restated
here even if it duplicates the design body.

**Options.**
| | Option | What you get | What it costs / risks |
|--|--------|--------------|------------------------|
| A | … (recommended) | … | … |
| B | … | … | … |

**Recommendation.** A, because <one sentence>.

**Your answer:** ______
```

A family README lists every question as one line + link; the full block
lives exactly once, in the doc that owns the decision.

## 6. Async collaboration fields (human-read documents)

Design docs are a conversation with the owner that happens asynchronously,
across sessions. Two structures make that work:

- **Decision blocks are two-way.** When the owner writes into a
  `**Your answer:**` line, the next agent session treats it as the decision
  event: fold the answer into the design text, move the block into a
  compact "Decisions (resolved)" table linking the ADR record in
  `memory/decisions/`, and prune the now-dead options. If the "answer" is
  itself a question, answer it **inside the block** (with concrete
  examples), keep the block open with a fresh answer line, and mirror the
  open question into `message-queue/needs-human/decisions/` so it can't be lost.
- **Resolved tables stay two-way.** The owner may amend a
  "Decisions (resolved)" table row just like an answer line; agents check
  resolved tables for owner edits on every visit, not only open blocks.
- **Every human-read document ends with a `## Human questions / additional
  tasks` section** — free space the owner can write into at any time.
  Agents check it on every visit to the doc: questions get answered in
  place (append the answer under the question, dated); tasks get filed
  into `message-queue/` and back-linked. Never delete the owner's text; append
  below it.

Full queue semantics (statuses, folders, boot ritual): `AGENTS.md` →
"Async collaboration".

## 7. General prose rules

- Define every term of art at first use in each document (not once per
  family). Tier/mode names (`token_saving`, "capture tiers") get a
  half-sentence gloss at first mention per doc.
- Prefer named concepts over numbering wherever the name will be used more
  than twice; numbers are for ordered sequences only (stages, steps).
- Tables carry facts; the sentence before a table says what to conclude
  from it.
- Status lines at the top of a doc are plain language ("Revised after
  review; awaiting owner decisions Q-A…Q-R"), never process jargon.
