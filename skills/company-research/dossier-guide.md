# Company Research — Dossier Guide

This is the long-form requirements and quality guide. `SKILL.md` selects a mode and
routes here by section; a full-dossier run reads this file completely. A quick,
chat-only request does not load this guide unless its answer needs one of the named
specialized methods.

Build **deep, interview-ready** research on a company **and** the specific role.
The user should walk in sounding like an engineer who has studied the product and
formed opinions — not someone who read the homepage. Separately, they get the
personal-decision facts (comp, stability, WLB, visa) to evaluate an offer.

## The Depth Bar

The failure mode this skill exists to prevent: **shallow research that anyone
could get from the first page of a Google search.** Facts alone are not enough.
Every `for-interview` file must show *understanding and a point of view*, not just
retrieved facts. Enforce this:

- **Answer "so what?" and "why is this hard?"** for every major fact. A number or a
  product name is a starting point, not the finding.
- **Reason from constraints.** Given their scale, latency budget, consistency
  needs, cost, and threat model — what problems *must* they be fighting? Derive the
  hard problems even where they aren't spelled out, and label the reasoning.
- **Explain choices, not just features.** For each architecture/product/GTM choice,
  ask *"why this over the obvious alternative?"* and articulate the trade-off.
- **Interrogate claims with evidence and the 5 Whys — never take a moat at face
  value.** A company's own claims ("we're the leader," "our network effects protect
  us") are *hypotheses to test*, not findings. For any claim about moat,
  defensibility, or growth, run a **5-Whys** chain and stop at *evidence* (adoption/
  retention numbers, pricing power, who chose them and why, competitor moves,
  switching costs, financials), not at another claim. Explicitly separate **Claim**
  (what they say) → **Evidence** (what's observable) → **Judgment** (your call).
- **Form a synthesis / POV.** End deep-dive sections with a short **My read** —
  what's genuinely impressive, what's marketing, what's the risk. Be specific.
- **Explain before analyzing.** Assume the reader has never heard of the company,
  used the product, or learned its domain vocabulary. State in plain language what
  the product is, who uses it, and what job it performs before naming components,
  architecture, strategy, or implementation details.
- **Go past the homepage.** Read engineering blog posts *in full*, docs
  architecture pages, conference talks, founder interviews/podcasts, GitHub
  issues/design docs, and HN/Reddit threads. Cite the specific artifact.
- **Be concrete.** Name the subsystem, the repo, the blog post, the customer, the
  competitor. Show at least one realistic end-to-end use case with actors, inputs,
  steps, and outputs; a product-name inventory is not an explanation. Generic
  statements ("scalable, reliable infra") are banned.

If a section could have been written without reading anything specific to this
company, it is not done yet.

## When to Use

Use this skill when the user asks to:
- research a company they're interviewing with (product, size, challenges, moat, stage)
- understand the specific team/role they're applying for
- rate a company as a place to work, or score it against its competitors
- prep a "why this company / why not competitors" answer, or deep questions to ask
- gather personal-decision facts (funding/stage, comp, WLB, ratings, H-1B)
- build or refresh `config.companies_root()/<company>/research/`

## Before You Start

1. Read `AGENTS.md` for repo guardrails (never fabricate; traceability).
2. Read this skill's `LESSONS.md` for operational knowledge.
   - **Personalization / private overrides:** if `config.skill_references_dir()` for this
     skill exists in the overlay, read every file in it — those candidate-specific
     notes and examples OVERRIDE the generic examples in this guide and
     `reference.md`. When it is absent (public / example mode), use the generic
     examples here and take all candidate specifics from `config` and the profile.
3. Find the application record under `config.applications_root()/<status>/<slug>/`: its
   `meta.yaml`, the JD file(s) `source/JD-*.md`, and `notes.md` if present.
   **No application record is the ordinary case** — research usually runs before an
   application exists. Do not improvise an accommodation; switch to **company scope**:
   - Produce **whatever the request asked for, in full** — the whole folder for a
     full-research request, one file when one file was asked for. Company scope changes a
     file's *subject*, never how many files you write. Only the three outputs below are
     specified in terms of a posting; everything else is company-level and unchanged.
   - The subject of `08`, of `10`'s angles, and of `09`'s level/scope questions becomes the
     **role family named in the request** (e.g. "Senior SWE, Platform"), sourced from the
     company's own open postings on its ATS board — real, fetchable evidence that needs no
     application. **The request often names no role** ("research company X"), or names one no
     posting carries — companies use their own title vocabulary and one word like "Platform"
     routinely spans several orgs. Either way: never invent a posting. Enumerate the closest
     real reqs, name the ambiguity, `[JD-dependent]`-tag the choice, and pick the reading
     closest to the candidate's profile.
     Put `Scope: company-level — no saved posting; grounded in the ATS board as of <date>`
     under the title of `08` and `10`, and under `09`'s level/scope heading.
   - When a live board role supplies the scope, put `[JD-dependent]` on the same line as
     every individual sentence, bullet, question, or pitch line that depends on that role's
     title, team, responsibility, or requirement; a section note or nearby tag is not enough.
     Leave company-level claims untagged. This lets a later run *with* the application
     re-target only the posting-dependent lines instead of rewriting the file.
   - A required cross-file link whose target this run did not produce (`09` → `10`, when only
     `09` was asked for) **stays a link**, marked `(not yet written)`. Never inline another
     file's template to avoid a dangling reference: the summary `09` already owes is the
     deliverable, and the link is only a pointer.
4. Skim your candidate profile (`config.profile_md_path()`) so research and questions connect to
   the candidate's real background and needs — take their domain/experience from the profile
   and their location + visa-sponsorship requirements from `config.location_policy()` and the
   profile's sponsorship flags (never assume a specific metro or visa status here).
5. **Scratch stays in `local/`** (fetched HTML/JSON in `local/web_artifacts/`, probe scripts in
   `local/scratch/`) — never the repo root or the company-research tree (only finished notes
   belong there). See `AGENTS.md` → "Scratch & Temporary Files".

## Research Method & Sourcing Rules

This skill writes notes the user takes into a live interview and uses to make an
offer decision. Wrong "facts" are worse than missing ones. So:

- **Do live research** — do not rely on memory. Fetch primary sources with `curl`
  (or a browser tool if available) and read them *fully*, not just the snippet.
- **Layered sources, in order:**
  1. First-party: company site (`/about`, `/careers`, `/blog`, pricing, docs),
     GitHub org/repos, the JD, the ATS board (teams + all roles = org structure).
  2. **Engineering primary sources** (this is where depth comes from):
     engineering blog posts, architecture docs, conference talks (YouTube),
     founder interviews/podcasts, notable RFCs/design docs, HN/Reddit discussion.
  3. Reputable secondary: funding/valuation, headcount, ratings, visa data.
- **Cite every non-obvious claim** with a source URL (inline or in `## Sources`).
- **Mark confidence** on claims that aren't first-party certain. In `README.md` and
  every `for-myself` file, every secondary or otherwise non-first-party claim must
  carry exactly one of these bracketed tags inline; prose labels such as “High,”
  “Medium,” or “Low” confidence do not satisfy this rule:
  - `[confirmed]` — stated by the company or a primary source
  - `[likely]` — consistent secondary reporting
  - `[unverified]` — single/weak source or an inference; flag to confirm
- **Never fabricate** headcount, funding, ratings, values, architecture, or product
  claims. If a fact can't be sourced, write `[unverified] — confirm` instead of
  guessing. Ratings especially: if Glassdoor/Levels/Blind can't be fetched,
  scaffold with where to look; do not invent numbers.
- **Distinguish inference from fact.** Reasoned inferences (e.g. "at this scale
  they must shard X") are *encouraged* for depth but must be labeled `[inference]`.
  In `README.md` and `for-myself`, `[inference]` is additional context and does not
  replace the required `[confirmed]`/`[likely]`/`[unverified]` confidence tag.
- **Scaffold unverifiable offer facts explicitly.** For a fictional company or any
  offer-decision fact that cannot be verified, name the source the user should
  check: Crunchbase for funding/stage, Glassdoor for sentiment/WLB, Levels.fyi for
  compensation, h1bdata.info for historical sponsorship filings, and the recruiter
  for current policy. Never infer current sponsorship from historical filings;
  visa remains `[unverified] — confirm with recruiter` until the recruiter confirms it.

### Acquisition and Output Reference

Before live research for a saved artifact, read `reference.md` §§ "Handy Fetches"
(canonical fetches, restricted-source rules, compensation-cache provenance) and
"Output Location and Structure" (private-overlay routing and the output tree). Read
§ "Maturity fetches" whenever an output names product lifecycle stage — always for
`04`, `05`, `06`, and products named in `09` questions. `SKILL.md`'s On-Demand Map
is the authoritative per-file router: read a template when its pointer fires, never
ahead of it, and never read either reference file end to end on your own initiative
for a focused request. A full-folder run reads both files completely.

Every reference section must remain reachable from the On-Demand Map. Adding one
requires adding its pointer there in the same edit.
Keep the sourcing guardrails above and the output rules below as the controlling gates.

Rules:
- Create the whole folder when the request is for research broadly; a request scoped to
  one file produces **that file only**. Scaffold thin files with `[unverified]` +
  where-to-look; never invent to fill space.
- `for-interview` = things to *discuss/demonstrate* (depth + POV);
  `for-myself` = things to *know/decide*. Keep comp/WLB/visa out of the question
  bank; they live in `for-myself`.
- **In a full-folder run**, always produce `03`, `05`, `06`, `09`, and `10`, the
  **1–100 competitor scorecard**
  in `04`, and the **1–100 company rating** in `for-myself/06` — the deep-dive,
  differentiation, AI-embrace, question bank, why-this-company pitch, competitor
  scorecard, and company rating are the point of this skill. (`06` scales with AI
  exposure: for a company AI barely touches, still answer its questions — briefly,
  and say *why* exposure is low — rather than skipping it.)
- **Two different 1–100 ratings, kept distinct:** the `04` competitor scorecard rates
  *product/competitive strength* of the company **and every named rival** (an
  outward, interview-facing comparison); the `for-myself/06` company rating scores
  *how good the company is to work at* (an inward, decision-facing index). Never
  conflate them or reuse one number for the other.

## What Goes in Each File

### for-interview/01 — Company overview

One-liner, founding, HQ/remote, stage, the company
  *thesis* (the bet they're making about the world), and — **always** — the company's
  **size**, stated as concretely as the evidence allows: total headcount (and its
  trend — growing / flat / post-layoffs, with dates), engineering headcount if
  findable, number of offices/geos, and the best available scale-of-business figure
  (annual revenue and market cap for public companies; last valuation + total raised
  for private; customer/user count if that's the truest size signal). Never omit size:
  if a figure can't be sourced, give a bounded estimate `[inference]` (e.g. "~500–800
  from LinkedIn headcount + team page") and say where to confirm. Tag every figure
  with confidence and a date.
### for-interview/02 — Product and technology

A **cold-reader product walkthrough**, not a
  component inventory. Assume zero prior company/product/domain knowledge. Start
  with a jargon-free 30-second answer: product category, user, problem, and outcome.
  Define prerequisite concepts and company terms in dependency order. Then show at
  least one concrete end-to-end scenario—what the user does, a realistic input or
  request, which components act in what order, and the visible output. Explicitly
  separate what the customer runs/owns from what the company hosts/owns, and say
  what the product does *not* replace. Map each major component to the persona and
  workflow that use it. Only after that foundation, cover architecture/data flow,
  the real tech stack (JD + docs + GitHub), OSS footprint, and what's technically
  notable. Label hypothetical teaching examples `[illustrative]` so they cannot be
  mistaken for sourced customer implementations.
### for-interview/03 — Technical challenges

The centerpiece. See template below.
  **3–6 deep dives**, each on a genuinely hard problem at their scale.
### for-interview/04 — Business, customers, and competitors

Who pays and why, named customers, market
  and monetization model, the competitor set (named), **and a 1–100 competitor
  scorecard** that rates the target company *and every named rival* on
  product/competitive strength (before writing it, read `reference.md` § "Competitor
  Scorecard Template"). This is a product review through a competitive lens: don't
  just list rivals, *rate* them.
### for-interview/05 — Competitive moat and differentiation

The second centerpiece. See
  template below. Why the product/path/direction is *unique* (the contrarian bet) and
  a rigorous, **evidence-based** assessment of the **product moat / sustainable
  competitive advantage**, **how defensible it is against each competitor**, and its
  **growth potential** — every moat/defensibility/growth claim stress-tested with a
  **5-Whys** chain that stops at evidence, not company claims.
### for-interview/06 — AI strategy and future

The third centerpiece for any AI-exposed company.
  Frame it explicitly around **how the company embraces AI on two axes: publicly
  (customer-facing AI products, launches, and announcements) and privately (internal
  AI usage and adoption inside the walls — dev tooling, agent/eval workflows,
  leadership mandates)**. See template below. Beyond the AI thesis, how AI reshapes
  the roadmap, recent launches as evidence, and plausible/defensible future
  directions, it must answer three questions explicitly: **(a) AI-era survival &
  strategy** — is AI a tailwind
  or an existential threat to this product, and what AI-first / AI-native strategy
  have they *already shipped* vs. only *announced / planned* (separate the two, with
  evidence and dates — run the **Maturity gate** below; a product-directory entry, a docs
  landing page, or a pricing tier is **not** evidence that something shipped);
  **(b) the non-obvious AI edge** — reasoned, often
  *not-publicly-stated* structural reasons this product is unusually well- (or
  poorly-) positioned to win as AI commoditizes its layer — derive them from their
  data/distribution/workflow/regulatory position, not their press releases, and label
  `[inference]`; **(c) internal AI adoption** — how aggressively they use AI *inside*
  the company (leadership mandates, dev tooling like Cursor / Claude Code, eval/agent
  workflows, hiring signals like this JD) and whether they ship AI in *both* internal
  tooling *and* user-facing product. End with a **My read** on how real the AI story
  is versus AI-washing.
### for-interview/07 — Engineering team and culture

Eng org and sibling teams (ATS list is
  gold), how they ship, engineering values, OSS/community posture.
### for-interview/08 — Role deep dive

The team's charter, concrete scope, stack, success bar,
  an honest **fit map** to the user's real experience, and **gaps to prepare for**.
### for-interview/09 — Question bank

The "why this company / why not competitors" pitch plus the
  deep questions to ask. See the Question Bank Guidance below.
### for-interview/10 — Why this company

The prepared, *personalized* answer to the single most
  common interview question ("why do you want to work here / why us over competitor
  X?"), grounded in the candidate's real background and career interests, with **at
  least two angles**. Before writing it, read `reference.md` § "Why-This-Company Template".

### for-myself/01 — Funding and company stage

Rounds/amounts/dates, lead + notable investors,
  valuation, total raised, growth signals; a plain read on stability.
### for-myself/02 — Compensation and benefits

Posted range (JD/meta), equity, benefits,
  remote/geo policy; benchmarks `[unverified]` if secondary. Add a negotiation read.
### for-myself/03 — Work-life balance

Realistic pace/hours/on-call/PTO; label stage+JD
  inferences as `[inference]`; add sourced Glassdoor/Blind data points.
### for-myself/04 — Employee ratings and sentiment

Glassdoor/Levels/Blind/Repvue numbers with
  dates + links; if unfetchable, list where to check and mark `[unverified]`.
### for-myself/05 — Visa sponsorship and logistics

H-1B transfer / green-card sponsorship
  (check h1bdata.info / MyVisaJobs / USCIS disclosures; JD often silent →
  `[unverified] — confirm with recruiter`), work location, time zones, relocation.
### for-myself/06 — Company rating

A single **1–100 "how good is this company to work at"
  score**, computed from a fixed, weighted rubric that judges the *company itself and
  its general working style only* (future/growth, stability, WLB, eng culture,
  comp competitiveness, career growth, sentiment). **Deliberately excludes personal
  preferences** (location, visa/sponsorship, commute, personal comp target, team
  vibe fit) — those live elsewhere in `for-myself` and must not move this number, so
  the score is comparable across every company you research. Before writing it, read
  `reference.md` § "Company Rating Template". Show the sub-scores, the weighted math,
  the band, evidence + confidence per dimension, and a one-line **My read**.

## Deep-Dive Template

Use one block per hard problem (aim for 3–6):

```markdown
## Challenge N: <specific problem, named concretely>

**The problem** — what exactly is hard, at what scale/constraint.
**Why it's genuinely hard** — the physics/scale/consistency/latency/cost/threat
  constraint that makes the naive approach fail.
**How they approach it** — their actual design from blogs/docs/talks (cite), with
  the trade-off they chose and what they gave up. Mark `[inference]` where derived.
**Where it still hurts / open questions** — the unsolved edge, the tension.
**My read** — a one-to-three-sentence engineer's POV: what's impressive, what you'd
  probe, how it connects to the role.
```

## Moat & Differentiation Template

This file must go beyond "why they're different" to a **defensibility and growth
verdict backed by evidence**. Do NOT restate the company's marketing. Every claim
about a moat, defensibility, or growth is a hypothesis you test with a **5-Whys**
chain that bottoms out in *evidence* (adoption/retention, pricing power, who chose
them and why, competitor moves, switching costs, unit economics), then your judgment.

```markdown
## The contrarian bet
What non-obvious thing this company believes that most competitors don't, and why
that shaped the product/path/direction.

## Competitor-by-competitor
For each real rival: what they do, and the *specific* structural axis on which this
company differs (not "we're better").

## Product moat / sustainable competitive advantage
For each candidate moat, name its TYPE and test it with 5 Whys + evidence. Use a
recognized lens (Hamilton Helmer's 7 Powers, or the classic economic moats):
network effects · switching costs · scale economies · brand/intangibles · cost
advantage · counter-positioning · cornered resource / process power.

For EACH candidate moat, write:
- **Claim:** the advantage (often the company's own framing).
- **5 Whys:** why is it an advantage? → why can't a competitor copy it? → why not?
  → ... until you hit bedrock (a structural reason) or the claim collapses.
- **Evidence:** the observable proof (or its absence) — numbers, customer behavior,
  competitor attempts, retention, pricing power. Tag `[confirmed]`/`[likely]`/
  `[unverified]`. When the proof is a *product capability*, carry its maturity tag from
  the `06` Maturity gate — a capability still in beta is weaker evidence for a moat than
  a GA one, and one whose stage you could not establish is weaker still.
- **Verdict:** REAL & durable / real but eroding / weak / just a feature. One line.

## Defensibility scorecard (vs. each threat vector)
A short table or list: for each competitor/threat (incl. incumbents, startups, and
platform/model owners moving in), rate how well the moat holds — Strong / Moderate /
Weak — with the one-line evidence-based reason. Every row must choose **exactly one**
of those three categories. Never write a hybrid/range (`Strong/Moderate`), a
conditional combined label, or multiple categories; put every qualification in the
evidence text. Be honest about where they're exposed.

## Growth potential
Evidence-based, not aspirational. Cover: the market (TAM/where it's expanding),
the concrete **expansion vectors** (new products, new segments, upsell/land-and-
expand, geography), the **growth ceiling / saturation risk**, and **what has to be
true** for the growth story to hold. Ground in evidence (revenue growth rate, net
retention, adoption, pricing power); mark aspiration as `[inference]`.

## Risks to the thesis
What would have to be true for the moat/growth to fail; who threatens it and how fast.

## My read
Your synthesized verdict: how wide and durable is the moat *really*, and how much
runway is left — stated as a judgment, distinct from the company's claims.
```

**Trigger — testing a moat claim with the 5-Whys chain (do this, don't just assert
"network effects"):** read ONLY `reference.md` § "5 Whys, worked example".

## AI Strategy Template

This file answers the question every candidate now faces: *in the AI era, does this
company win, survive, or get disrupted — and does it actually run on AI or just talk
about it?* Same discipline as `05`: separate **what they say** from **what's
observable** from **your judgment**, tag confidence, and label reasoned inferences
`[inference]`. Do NOT restate an "AI-first" tagline as a finding — test it.

### Maturity gate — apply this before writing the shipped-vs-planned split

Maturity is a **sourced claim, not a page impression**. One measured run produced four wrong
"shipped" calls here — one for a product fifteen months into open beta — because the pages this
skill sends you to carry no maturity badge at all. The candidate then says those sentences to
the person who built the product. So classify **every product you name** — in `06`, in any `09`
question you will ask out loud ("you've shipped X" to X's own engineer is the highest-stakes
place to be wrong), and wherever `04`/`05` reason from a shipped capability — down this ladder,
in order, stopping at the first match. Classify a **sub-feature** in its own right: a GA product
routinely carries beta pieces.

1. **Beta / preview** — the words *beta, preview, early access, experimental, waitlist, request
   access,* or *"free during the beta"* appear **in a sentence about that product** in its
   launch post, its docs **body**, its pricing page, or the changelog. Read the hit in context:
   a bare keyword in a nav list, tag cloud, or sidebar is not a statement. **A stage statement
   beats any GA-looking signal**, unless a *dated* GA announcement is newer than the newest
   dated beta statement, or rung 4's staleness case applies.
2. **GA / shipped** — a dated launch, GA, or "out of beta" post or changelog entry; or a pricing
   page that bills it at a general price with no beta qualifier.
3. **Announced / planned** — a roadmap line, exec quote, press release, partnership, or job req,
   with no docs and no way to use it.
4. **Ambiguous** — you checked 1 and 2 and found no stage word either way, **or** the newest
   thing you found is a docs body updated *after* the last beta statement and silent on stage.
   That second case **overrides rung 1**, which would otherwise have stopped first: a silent
   refresh neither renews the old beta claim nor announces GA. Keep the last *stated* stage in
   the tag, mark the current stage `[unverified]`, and write the defensible sentence — "the
   <date> post called it <stage>; I found no <newer stage> announcement since" — rather than
   asserting either. Never resolve this case upward to GA.

**None of the following is evidence of GA**, and each has produced a wrong call: a
product-directory or "our products" listing · a docs landing/nav page carrying no stage word · a
plan-entitlement line ("Available on all plans", "Included in Pro" — a *pricing tier*, not a
lifecycle stage) · the existence of an API, SDK, dashboard tile, or docs · the **absence** of a
beta badge. A nav or sidebar stage pill is worth **recording in the ledger as corroboration** —
it is usually right — but it cannot establish a stage on its own, because it is rendered from
front-matter and goes stale silently. Two fetches settle it: the product's launch /
announcement post, then the **body
text** of its docs overview, pricing page and **dated changelog / release notes**
(`reference.md` § "Maturity fetches"). For a vendor that ships continuously the dated changelog
entry is usually the decisive artifact, not the launch post. A docs GA banner establishes the
*stage* but often not the *date* — take the date from the launch post or the changelog entry,
and never from the page you read the banner on.

**When it is ambiguous, say so.** File that product under its own `### Maturity unverified`
heading, never under `Already shipped`. Here an honest hedge is correct output and a confident
wrong call is the failure this gate exists to stop — never resolve an ambiguity toward shipped.

**Tag every product inline** with its stage, beside the usual source-confidence tag:
`[GA <date>]` · `[beta since <date> — <N> months]` · `[announced <date>, not shipped]` ·
`[maturity unverified — checked launch post + docs body]`. A beta always carries its
**duration**, because "in beta" and "in beta for fifteen months" are different facts about how
the company executes; when the start date is not findable, write `[beta, start date unverified]`
rather than dropping the stage. Back the tags with a short **Maturity evidence** table in the
file — product · tag · the sentence · the URL — so a reader can audit a stage call without
re-fetching, and so `Maturity unverified` shows what was actually checked.

```markdown
## AI-era survival & strategy
Is AI a **tailwind, a headwind, or an existential threat** to this product? Reason
from the product's job-to-be-done: what does AI make cheaper/obsolete, and what does
it make more valuable? Then inventory their AI strategy, **separating shipped from
promised**:
- **Already shipped (GA)** — features/products the maturity gate classified GA, with the
  dated launch/GA post or changelog entry that proves it. Tag `[GA <date>]` + `[confirmed]`.
- **Shipped but still beta / preview** — usable, but not GA. Give the stage, the date it
  entered it, and how long it has been there: `[beta since <date> — <N> months]`.
- **Announced / planned** — roadmap statements, exec quotes, job reqs (this JD is a
  signal), acquisitions/partnerships. Mark aspiration `[inference]`; do not treat a
  press release as a shipped capability.
- **Maturity unverified** — you checked the launch post and the docs body and neither
  states a stage. List it here rather than guessing; say what you checked.
- **AI-first / AI-native posture** — is AI bolted on (a chatbot on the side) or woven
  into the core product/architecture/business model? Give the concrete evidence.

## The non-obvious AI edge
Reasoned, often *not-publicly-stated* structural reasons this company is unusually
well- (or poorly-) positioned as AI commoditizes its layer. Derive these from their
assets, not their marketing — proprietary/first-party data, distribution &
integration lock-in, workflow/system-of-record ownership, regulatory or trust moats,
switching costs, unit-economics headroom to spend on inference. For each: state the
edge, WHY it matters specifically under AI (`[inference]`), and what observable proof
would confirm or kill it. Also name the *inverse* — where the same AI wave most
threatens them (a well-capitalized incumbent, a model owner moving down-stack, or
commoditization of what they charge for).

## Internal AI adoption
How aggressively the company uses AI *inside* the walls, and whether it ships AI on
*both* sides:
- **Engineering & ops adoption** — leadership mandates, mandated/encouraged dev tools
  (Cursor, Claude Code, Copilot), agent/eval/automation workflows, "AI-native
  engineer" expectations. Cite the signal (JD language, blog, exec post, Glassdoor);
  a JD like this one is itself strong evidence of an internal AI push.
- **Internal vs. user-facing AI** — do they build AI for internal productivity, for
  the customer-facing product, or both? Name each concrete surface.
- **What it signals** — culture (build-vs-buy, speed), and what daily work in this
  role would actually look like. Mark inferences `[inference]`.

## My read
Your synthesized verdict: is the AI story **real and structural**, **early but
credible**, or **AI-washing**? How exposed are they to disruption, and how much of the
edge is defensible? State it as a judgment, distinct from the company's claims.
```

## Question Bank Guidance

**Always open `09` with the candidate's own pitch — "Why this company / why not
competitors."** Before the questions to *ask*, `09` must lead with a required
`## Why this company / Why not competitors` section that answers the question the
candidate will be *asked*: summarize the prepared, personalized answer and link to the
fuller `10-why-this-company.md` (at least two angles, grounded in the candidate's real
background/interests; its shape comes from the trigger below). Name the specific
competitors this company is chosen *over* and the honest reason, drawn from `04`/`05`.
Keep personal specifics sourced from the profile / `config.skill_references_dir()`, never
invented.

Questions must make the user look like they already understand the product *and its
hard problems and strategy*. Beyond that pitch and the product-depth questions, this
file **must** include three deep groups:

- **Hard Problems & Challenges** — questions about the *specific* engineering and
  business challenges the company is solving (drawn from `03`). e.g. "In your
  `<incident/post>` about `<product>`, you described X at Y scale — how do you handle
  <the constraint that makes it hard>, and where does it break today?"
- **Differentiation, Moat & Growth** — questions about **what makes them stand out,
  how defensible the moat is, and where growth comes from** (drawn from `05`).
  e.g. "Competitor Z takes approach A; you chose B — what did you see that made B
  worth the cost?" / "As <competitor> commoditizes <layer>, what structurally keeps you
  the default — network effects, switching costs, or something else?" / "Where does
  `<product>` go after `<named customer>` — and what's the biggest thing that has to
  go right for the next order of magnitude of growth?"
- **AI Strategy & Adoption** — questions about **AI-era survival, the AI-native
  roadmap, and how AI is actually used inside** (drawn from `06`). e.g. "You've
  shipped <AI feature>; where's the line today between what's in production and what's
  still prototype?" / "As LLMs commoditize <layer of your product>, what's the part
  competitors *still* can't copy — and is it your data, your distribution, or your
  workflow lock-in?" / "Your `<engineering post/repo>` describes `<agent/eval
  workflow>` — where has that workflow actually replaced manual work?"

Also include: `Product & platform depth`, `Level, scope & team fit` (the level/scope group —
in company scope it carries the `Scope:` line from "Before You Start" step 3), `For the Hiring
Manager`, `For Engineers on the team`, `For a
Skip-level / Leadership`, `For the Recruiter (role/interview process only)`. Prefer
~4–8 sharp questions per group. **Every question in every group, without exception**
(including hiring-manager, engineer, leadership, level/scope, and recruiter
questions) goes on its own line with a short parenthesized intent tag and names a
*specific* company product, repo, post, competitor, incident, or customer. Generic
priority, coaching, disagreement, culture, or process prompts do not qualify. Keep
compensation, benefits, WLB, visa/sponsorship, work-model/remote policy, on-call
frequency, and office-cadence probes out of this file; those belong in `for-myself`.

**Trigger — drafting `09`:** read `reference.md` §§ "Question Bank examples" (a model question
per group) **and** "Why-This-Company Template" (the shape of the pitch `09` opens with, which
`09` needs whether or not `10` is written this run). Those two sections, and no others.

## Formatting Conventions

- Start each file with a title, one-line purpose, `Last researched: <date>`, and the
  confidence legend note. End every file with `## Sources` (URLs + the specific
  artifact, e.g. a blog post title, not just the domain).
- Deep-dive and differentiation files can run long — depth over brevity there.
  `02` can run long enough to teach the product from zero. Overview/role/for-myself
  files stay scannable (bullets, short sections).
- Confidence/inference tags go on the specific claim, not the whole file. In
  `README.md` and every `for-myself` file, every secondary or non-first-party claim
  has a bracketed `[confirmed]`, `[likely]`, or `[unverified]`; High/Medium/Low prose
  and `[inference]` do not substitute for that tag.
- README index: 4–6 bullet TL;DR ("the pitch + the bet, in your words"), file map,
  research date, master source list. Surface the headline numbers up top: company
  **size**, the **company rating (1–100)** with its band, and the company's rank +
  score in the **competitor scorecard**.

## Workflow

```
- [ ] Read AGENTS.md, LESSONS.md, the app meta.yaml + JD(s) + notes, and profile
      (no application record? company scope — see "Before You Start" step 3)
- [ ] First-party pass: site (about/careers/blog/pricing/docs), GitHub, ATS teams/roles
- [ ] DEPTH pass: read eng blog posts/talks/founder interviews/HN in full (cite artifacts)
- [ ] Secondary pass: funding/valuation, headcount, ratings, visa (cite + date)
- [ ] Write 02 as a cold-reader product walkthrough with a concrete end-to-end example,
      then 03 technical-challenges-deep-dive (3–6 dives + My read)
- [ ] Write 05 moat & differentiation: contrarian bet + moat (5-Whys + evidence) +
      defensibility scorecard + growth potential + risks + My read
- [ ] Write 06 AI embrace: public (customer-facing) + private (internal adoption);
      AI-era survival + shipped-vs-planned (Maturity gate: launch post + docs body, per-product
      stage tag, betas dated with duration) + non-obvious AI edge ([inference]) + My read
- [ ] Write 01 (incl. company SIZE — headcount/trend/revenue/valuation), 07, 08
      (facts + POV + confidence tags + Sources)
- [ ] Write 04 business/customers/competitors + the 1–100 competitor scorecard
      (company + every rival, weighted, banded, evidence)
- [ ] Write for-myself/ 01–05, then for-myself/06 company rating (1–100, weighted
      rubric, company + working style only, NO personal prefs, show the math)
- [ ] Write 09 question-bank: LEAD with "why this company / why not competitors", then
      Hard-Problems, Differentiation/Moat/Growth, and AI-Strategy/Adoption groups
- [ ] Write 10 why-this-company (≥2 personalized angles; per role type when multi-posting)
- [ ] Write README index + TL;DR (surface both 1–100 numbers: competitor rank + company rating)
- [ ] Final check (below)
```

## Final Checks

- **Depth:** Does every `for-interview` file contain something you could only write
  after reading company-specific material? Does `03` explain *why each problem is
  hard*, and `05` explain *why the path is unique* — each with a **My read** POV?
- **Cold-reader test:** Can someone with zero company, product, and domain knowledge
  explain what the product does, who uses it, what one real workflow looks like, and
  what the company versus customer operates after reading `02`? If they only know
  component names and architecture labels, `02` is not done.
- **Moat rigor:** In `05`, is each moat claim tested with a **5-Whys chain that ends
  in evidence** (not a restated company claim)? Is there a **defensibility verdict**
  per competitor/threat and an **evidence-based growth-potential** read? Are
  **Claim / Evidence / Judgment** kept distinct?
- **AI-strategy rigor:** Does `06` frame AI embrace on **both axes — publicly
  (customer-facing products/launches) and privately (internal adoption)** — and answer
  all three: **(a)** AI-era survival with shipped-vs-planned strategy separated
  (dates/evidence) — **and does every named product carry a maturity tag from the Maturity
  gate, with each beta dated and given its duration, and anything unsettled listed under
  `Maturity unverified` rather than folded into shipped?** **(b)** a non-obvious AI edge
  derived from real assets and labeled
  `[inference]` (plus the inverse threat), and **(c)** internal AI adoption covering
  *both* internal and user-facing AI — ending with a **My read** that calls real
  strategy vs. AI-washing? Is an "AI-first" tagline tested, not parroted?
- **Size:** Is the company's **size** stated concretely in `01` — headcount + its
  trend, plus the best scale-of-business figure (revenue/market cap or
  valuation/raised) — with dates and confidence, never omitted (bounded `[inference]`
  if unsourced)?
- **Ratings rigor:** Are **both 1–100 numbers present and kept distinct** — the `04`
  **competitor scorecard** (target company + *every* named rival, weighted, banded,
  evidence-tagged sub-scores) and the `for-myself/06` **company rating** (fixed
  weighted rubric, company + working-style only, personal prefs **excluded**, with the
  math shown)? Is neither number false-precision over `[unverified]` inputs?
- **Why-this-company:** Does `10` give **≥2 honest, personalized angles** grounded in
  the candidate's *real* background/interests (an angle per role type when the app is
  multi-posting), each with a specific **"why not competitor X"** — and does `09` lead
  with that pitch? Nothing invented beyond the profile / `config.skill_references_dir()`?
- **Concreteness:** Named subsystems/repos/posts/competitors/customers, not
  generalities?
- **Questions:** Do they probe the hard problems, the moat's durability, growth, and
  the AI strategy/adoption — not generic curiosity? Does **every** question,
  including hiring-manager/leadership/recruiter questions, name a specific company
  product, repo, post, competitor, incident, or customer? Are compensation, WLB,
  visa, work-model, on-call-frequency, and office-cadence probes absent? Could a
  senior engineer at the company tell the user did real homework?
- **Honesty:** Every fact defensible under push-back or tagged `[unverified]`/
  `[inference]`? Nothing fabricated?
- **for-myself:** Genuinely useful for an offer decision; visa/H-1B flagged where
  unconfirmed as `[unverified] — confirm with recruiter`? Does fictional/unverifiable
  scaffolding name Crunchbase, Glassdoor, Levels.fyi, h1bdata.info, and recruiter as
  verification sources? Does every secondary/non-first-party claim in these files
  and README carry a bracketed confidence tag? Every file ends with Sources; README
  carries the research date?
