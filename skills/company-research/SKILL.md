---
name: company-research
visibility: public
description: Research a company and role for interview preparation: product and size, engineering challenges, competitors, moat and growth, AI strategy and adoption, culture, role fit, a why-this-company pitch, interview questions, offer-decision facts, and 1–100 product and workplace ratings. Use for quick company questions, interview prep, company or competitor ratings, or saved company-research dossiers.
---

# Company Research

Give the candidate a sourced, engineer-level point of view on the company and role,
plus the facts needed to judge an offer. Explain the product to a cold reader before
analyzing it. Never turn company claims into findings without evidence.

## Choose the Mode First

### Quick / scoped chat-only

Use this mode when the user explicitly says **quick**, **brief**, **not
comprehensive**, **chat only**, or otherwise asks not to build the full dossier.
Also use it for one narrow company question when the user did not ask to save or
refresh research.

- Answer only the requested question in chat. Do not create or refresh the research
  folder, task, queue, worklog, or conversation-history artifacts.
- Do live research proportionate to the question. Prefer first-party material and,
  for technical claims, primary engineering sources. Cite the specific artifacts.
- Do not load the application, profile, `LESSONS.md`, `dossier-guide.md`, or the full
  output tree unless the answer genuinely depends on candidate-specific context or a
  specialized method below.
- Keep the same truth standard as an artifact: distinguish fact from inference,
  label uncertainty, never invent a number, and answer “so what?” rather than
  returning a fact list.
- If the question asks for product maturity, a competitor score, a 5-Whys moat test,
  a why-company answer, or a workplace score, read only the matching section named
  in the On-Demand Map below.

This mode is intentionally process-history-free. The chat answer is the complete
product. Stop after answering unless the user also asked to save research.

### Focused saved artifact

Use this mode when the user asks for one named research file or a narrow saved
artifact. Read the Artifact Preflight, then only the matching row in the On-Demand
Map. Produce only what was requested; keep required cross-file links and mark an
unwritten target `(not yet written)`.

### Full dossier

A broad request to research or prepare for a company, without an explicit brevity
or chat-only constraint, uses the full dossier. Read `LESSONS.md`,
`dossier-guide.md`, and `reference.md` completely, then build the output tree in
`reference.md` § “Output Location and Structure.” A full run must include all 16
research files plus the README; never silently reduce it to a summary.

## Hard Gates in Every Mode

- **Live evidence:** research current sources; do not rely on memory. Cite every
  non-obvious claim with the specific page, post, filing, talk, repository, or JD.
- **No fabrication:** never invent headcount, funding, ratings, compensation,
  architecture, product maturity, experience, or fit. Use `[unverified] — confirm`
  when evidence is missing and `[inference]` for reasoned deductions.
- **Literal confidence tags:** in `README.md` and every `for-myself` output, put
  exactly one bracketed `[confirmed]`, `[likely]`, or `[unverified]` tag on every
  secondary or otherwise non-first-party claim. Prose such as “High confidence”
  does not count; `[inference]` may be additional but never replaces the tag.
- **Evidence before judgment:** separate **Claim → Evidence → Judgment**. Test moat,
  defensibility, and growth claims rather than echoing marketing.
- **Company-specific depth:** name real products, constraints, customers,
  competitors, repositories, and artifacts. Explain why a technical problem is hard
  and why a choice beats its obvious alternative.
- **Maturity is sourced:** a docs page, plan-entitlement line, API, SDK, or missing
  beta badge does not prove GA. Apply the maturity ladder before calling a product
  shipped, and carry the stage into questions and moat evidence.
- **Personalization is traceable:** use only the candidate profile, saved JD, and
  configured private skill references. Be honest about fit and gaps.
- **Public/private boundary:** resolve identity, applications, company outputs,
  location, sponsorship, and private references through `config.*()`; never put
  candidate or researched-company facts into this public skill.
- **Keep the two ratings distinct:** the competitor scorecard measures product and
  competitive strength; the workplace rating measures the company and general
  working style, excluding personal preferences.
- **One moat category per row:** every categorical moat/defensibility scorecard row
  chooses exactly one of `Strong`, `Moderate`, or `Weak`. Put qualifications in the
  evidence text; never use a hybrid, range, slash, or conditional category.
- **Question-bank boundary:** every question, including hiring-manager,
  leadership, engineer, and recruiter questions, names a specific company product,
  repo, post, competitor, incident, or customer. Keep compensation, WLB, visa,
  work-model, on-call-frequency, and office-cadence probes out of `09`.
- **Unverifiable offer facts:** scaffold rather than guess, and explicitly direct
  verification to Crunchbase, Glassdoor, Levels.fyi, h1bdata.info, and the
  recruiter. Visa always stays `[unverified] — confirm with recruiter` unless a
  recruiter confirms the current policy.

## Artifact Preflight

For either saved-artifact mode:

1. Read `AGENTS.md` and `LESSONS.md`. If
   `config.skill_references_dir()` for this skill exists, read every file there;
   those private instructions override generic examples.
2. Read `dossier-guide.md` §§ “The Depth Bar,” “Before You Start,” “Research Method
   & Sourcing Rules,” and “Acquisition and Output Reference.” These sections define
   no-application company scope, `[JD-dependent]` tagging, profile use, and source
   confidence.
3. Read `reference.md` §§ “Handy Fetches” and “Output Location and Structure.” Read
   “Maturity fetches” only when the output names product lifecycle stage, including
   `04`, `05`, `06`, and `09`. Then follow only the per-file pointers below. A full
   dossier reads both reference files completely.
4. Keep fetched HTML/JSON in `local/web_artifacts/` and probes in `local/scratch/`.
   Only finished research belongs under `config.companies_root()`.

## On-Demand Map

Section names are exact. For a focused artifact—or a quick answer needing a
specialized method—read only the listed sections.

| Output or question | `dossier-guide.md` | `reference.md` |
|---|---|---|
| `README.md` | “Formatting Conventions” | “Output Location and Structure” |
| `for-interview/01` | “for-interview/01 — Company overview” | — |
| `for-interview/02` | “for-interview/02 — Product and technology” | — |
| `for-interview/03` | “for-interview/03 — Technical challenges”; “Deep-Dive Template” | — |
| `for-interview/04` or competitor rating | “for-interview/04 — Business, customers, and competitors” | “Competitor Scorecard Template”; “Maturity fetches” when capabilities affect the score |
| `for-interview/05` or moat test | “for-interview/05 — Competitive moat and differentiation”; “Moat & Differentiation Template” | “5 Whys, worked example”; “Maturity fetches” when capabilities support a moat |
| `for-interview/06` or product maturity | “for-interview/06 — AI strategy and future”; “AI Strategy Template” | “Maturity fetches” |
| `for-interview/07` | “for-interview/07 — Engineering team and culture” | — |
| `for-interview/08` | “for-interview/08 — Role deep dive”; “Before You Start” | — |
| `for-interview/09` | “for-interview/09 — Question bank”; “Question Bank Guidance” | “Question Bank examples”; “Why-This-Company Template”; “Maturity fetches” for products named in questions |
| `for-interview/10` or why-company answer | “for-interview/10 — Why this company” | “Why-This-Company Template” |
| `for-myself/01` | “for-myself/01 — Funding and company stage” | — |
| `for-myself/02` | “for-myself/02 — Compensation and benefits” | “Handy Fetches” |
| `for-myself/03` | “for-myself/03 — Work-life balance” | — |
| `for-myself/04` | “for-myself/04 — Employee ratings and sentiment” | “Handy Fetches” |
| `for-myself/05` | “for-myself/05 — Visa sponsorship and logistics” | “Handy Fetches” |
| `for-myself/06` or workplace rating | “for-myself/06 — Company rating” | “Company Rating Template” |

Before finishing a saved artifact, read `dossier-guide.md` § “Formatting
Conventions” and apply the relevant bullets in § “Final Checks.” A full dossier also
follows § “Workflow” in order.
