---
name: company-research
visibility: public
description: Deeply research a company and the specific role for an interview — product, company size, the hard technical challenges and why they're hard, competitive moat/defensibility/growth (evidence-based, 5-Whys — not company claims), a 1–100 competitor scorecard rating the company against each rival, how the company embraces AI publicly (customer-facing) and privately (internal adoption), eng culture, the role deep-dive, a prepared "why this company / why not competitors" pitch, plus offer-decision facts (funding/stage, comp, WLB, ratings, visa/H-1B) and a 1–100 "how good is this place to work" company rating and a hiring-manager/engineer question bank. Use when the user asks to research a company, prep for an interview, understand a company's product/challenges/moat/defensibility/growth/strategy, rate a company or its competitors, or build company-info for an application.
---

# Company Research

Build **deep, interview-ready** research on a company **and** the specific role.
The user should walk in sounding like an engineer who has studied the product and
formed opinions — not someone who read the homepage. Separately, they get the
personal-decision facts (comp, stability, WLB, visa) to evaluate an offer.

## The Depth Bar (read this first)

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
- build or refresh `interviews/company-specific/<company>/company-info/`

## Before You Start

1. Read `AGENTS.md` for repo guardrails (never fabricate; traceability).
2. Read this skill's `LESSONS.md` for operational knowledge.
   - **Personalization / private overrides:** if `config.skill_references_dir()` for this
     skill exists in the overlay, read every file in it — those candidate-specific
     notes and examples OVERRIDE the generic examples in this SKILL.md. When it is
     absent (public / example mode), use the generic examples here and take all
     candidate specifics from `config` and the profile.
3. Find the application record under `config.applications_root()/<status>/<slug>/`: its
   `meta.yaml`, the JD file(s) `source/JD-*.md`, and `notes.md` if present.
4. Skim your candidate profile (`config.profile_md_path()`) so research and questions connect to
   the candidate's real background and needs — take their domain/experience from the profile
   and their location + visa-sponsorship requirements from `config.location_policy()` and the
   profile's sponsorship flags (never assume a specific metro or visa status here).
5. **Scratch stays in `local/`** (fetched HTML/JSON in `local/web_artifacts/`, probe scripts in
   `local/scratch/`) — never the repo root or the `interviews/` tree (only finished notes belong
   there). See `AGENTS.md` → "Scratch & Temporary Files".

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
- **Mark confidence** on claims that aren't first-party certain:
  - `[confirmed]` — stated by the company or a primary source
  - `[likely]` — consistent secondary reporting
  - `[unverified]` — single/weak source or an inference; flag to confirm
- **Never fabricate** headcount, funding, ratings, values, architecture, or product
  claims. If a fact can't be sourced, write `[unverified] — confirm` instead of
  guessing. Ratings especially: if Glassdoor/Levels/Blind can't be fetched,
  scaffold with where to look; do not invent numbers.
- **Distinguish inference from fact.** Reasoned inferences (e.g. "at this scale
  they must shard X") are *encouraged* for depth but must be labeled `[inference]`.

### Acquisition and Output Reference

Before live research and before writing outputs, read `reference.md` completely. It contains the canonical fetches, restricted-source rules, compensation-cache
provenance requirements, private-overlay routing, and full output tree. Keep the sourcing guardrails above and the output rules below as the controlling gates.

Rules:
- Create the whole folder. Scaffold thin files with `[unverified]` + where-to-look;
  never invent to fill space.
- `for-interview` = things to *discuss/demonstrate* (depth + POV);
  `for-myself` = things to *know/decide*. Keep comp/WLB/visa out of the question
  bank; they live in `for-myself`.
- Always produce `03`, `05`, `06`, `09`, and `10`, the **1–100 competitor scorecard**
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

**for-interview/**
- **01 company-overview** — one-liner, founding, HQ/remote, stage, the company
  *thesis* (the bet they're making about the world), and — **always** — the company's
  **size**, stated as concretely as the evidence allows: total headcount (and its
  trend — growing / flat / post-layoffs, with dates), engineering headcount if
  findable, number of offices/geos, and the best available scale-of-business figure
  (annual revenue and market cap for public companies; last valuation + total raised
  for private; customer/user count if that's the truest size signal). Never omit size:
  if a figure can't be sourced, give a bounded estimate `[inference]` (e.g. "~500–800
  from LinkedIn headcount + team page") and say where to confirm. Tag every figure
  with confidence and a date.
- **02 product-and-technology** — a **cold-reader product walkthrough**, not a
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
- **03 technical-challenges-deep-dive** — the centerpiece. See template below.
  **3–6 deep dives**, each on a genuinely hard problem at their scale.
- **04 business-customers-competitors** — who pays and why, named customers, market
  and monetization model, the competitor set (named), **and a 1–100 competitor
  scorecard** that rates the target company *and every named rival* on
  product/competitive strength (see the Competitor Scorecard Template below). This is
  a product review through a competitive lens: don't just list rivals, *rate* them.
- **05 competitive-moat-and-differentiation** — the second centerpiece. See
  template below. Why the product/path/direction is *unique* (the contrarian bet) and
  a rigorous, **evidence-based** assessment of the **product moat / sustainable
  competitive advantage**, **how defensible it is against each competitor**, and its
  **growth potential** — every moat/defensibility/growth claim stress-tested with a
  **5-Whys** chain that stops at evidence, not company claims.
- **06 ai-strategy-and-future** — the third centerpiece for any AI-exposed company.
  Frame it explicitly around **how the company embraces AI on two axes: publicly
  (customer-facing AI products, launches, and announcements) and privately (internal
  AI usage and adoption inside the walls — dev tooling, agent/eval workflows,
  leadership mandates)**. See template below. Beyond the AI thesis, how AI reshapes
  the roadmap, recent launches as evidence, and plausible/defensible future
  directions, it must answer three questions explicitly: **(a) AI-era survival &
  strategy** — is AI a tailwind
  or an existential threat to this product, and what AI-first / AI-native strategy
  have they *already shipped* vs. only *announced / planned* (separate the two, with
  evidence and dates); **(b) the non-obvious AI edge** — reasoned, often
  *not-publicly-stated* structural reasons this product is unusually well- (or
  poorly-) positioned to win as AI commoditizes its layer — derive them from their
  data/distribution/workflow/regulatory position, not their press releases, and label
  `[inference]`; **(c) internal AI adoption** — how aggressively they use AI *inside*
  the company (leadership mandates, dev tooling like Cursor / Claude Code, eval/agent
  workflows, hiring signals like this JD) and whether they ship AI in *both* internal
  tooling *and* user-facing product. End with a **My read** on how real the AI story
  is versus AI-washing.
- **07 engineering-team-and-culture** — eng org and sibling teams (ATS list is
  gold), how they ship, engineering values, OSS/community posture.
- **08 role-deep-dive** — the team's charter, concrete scope, stack, success bar,
  an honest **fit map** to the user's real experience, and **gaps to prepare for**.
- **09 question-bank** — the "why this company / why not competitors" pitch plus the
  deep questions to ask. See the Question Bank Guidance below.
- **10 why-this-company** — the prepared, *personalized* answer to the single most
  common interview question ("why do you want to work here / why us over competitor
  X?"), grounded in the candidate's real background and career interests, with **at
  least two angles**. See the Why-This-Company Template below.

**for-myself/**
- **01 funding-and-company-stage** — rounds/amounts/dates, lead + notable investors,
  valuation, total raised, growth signals; a plain read on stability.
- **02 compensation-and-benefits** — posted range (JD/meta), equity, benefits,
  remote/geo policy; benchmarks `[unverified]` if secondary. Add a negotiation read.
- **03 work-life-balance** — realistic pace/hours/on-call/PTO; label stage+JD
  inferences as `[inference]`; add sourced Glassdoor/Blind data points.
- **04 employee-ratings-and-sentiment** — Glassdoor/Levels/Blind/Repvue numbers with
  dates + links; if unfetchable, list where to check and mark `[unverified]`.
- **05 visa-sponsorship-and-logistics** — H-1B transfer / green-card sponsorship
  (check h1bdata.info / MyVisaJobs / USCIS disclosures; JD often silent →
  `[unverified] — confirm with recruiter`), work location, time zones, relocation.
- **06 company-rating** — a single **1–100 "how good is this company to work at"
  score**, computed from a fixed, weighted rubric that judges the *company itself and
  its general working style only* (future/growth, stability, WLB, eng culture,
  comp competitiveness, career growth, sentiment). **Deliberately excludes personal
  preferences** (location, visa/sponsorship, commute, personal comp target, team
  vibe fit) — those live elsewhere in `for-myself` and must not move this number, so
  the score is comparable across every company you research. See the Company Rating
  Template below. Show the sub-scores, the weighted math, the band, evidence +
  confidence per dimension, and a one-line **My read**.

## Deep-Dive Template (`03-technical-challenges-deep-dive.md`)

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

## Moat & Differentiation Template (`05-competitive-moat-and-differentiation.md`)

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
  `[unverified]`.
- **Verdict:** REAL & durable / real but eroding / weak / just a feature. One line.

## Defensibility scorecard (vs. each threat vector)
A short table or list: for each competitor/threat (incl. incumbents, startups, and
platform/model owners moving in), rate how well the moat holds — Strong / Moderate /
Weak — with the one-line evidence-based reason. Be honest about where they're exposed.

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

**5 Whys, worked example (do this, don't just assert "network effects"):**
> Claim: "Our marketplace has network effects." → *Why a moat?* more buyers attract
> more sellers. → *Why can't a rival copy it?* they'd start with no liquidity. →
> *Why can't they buy liquidity with funding?* ... → if the honest answer is "a
> well-funded rival could subsidize both sides in a region," the moat is **local and
> contestable**, not absolute. **Evidence:** check take-rate stability, multi-homing
> rates, and whether a funded competitor already gained share in any market.

## AI Strategy Template (`06-ai-strategy-and-future.md`)

This file answers the question every candidate now faces: *in the AI era, does this
company win, survive, or get disrupted — and does it actually run on AI or just talk
about it?* Same discipline as `05`: separate **what they say** from **what's
observable** from **your judgment**, tag confidence, and label reasoned inferences
`[inference]`. Do NOT restate an "AI-first" tagline as a finding — test it.

```markdown
## AI-era survival & strategy
Is AI a **tailwind, a headwind, or an existential threat** to this product? Reason
from the product's job-to-be-done: what does AI make cheaper/obsolete, and what does
it make more valuable? Then inventory their AI strategy, **separating shipped from
promised**:
- **Already shipped** — AI features/products live in the hands of users or engineers,
  with dates and evidence (changelog, blog, release). Tag `[confirmed]`/`[likely]`.
- **Announced / planned** — roadmap statements, exec quotes, job reqs (this JD is a
  signal), acquisitions/partnerships. Mark aspiration `[inference]`; do not treat a
  press release as a shipped capability.
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

## Competitor Scorecard Template (in `04-business-customers-competitors.md`)

A product review is not finished at a *list* of rivals — **rate them**. Score the
target company **and every named competitor** on the same 1–100 scale so the reader
sees exactly where this company sits in the field. This is the *outward,
product/competitive-strength* rating (distinct from the `for-myself/06` company
rating, which is about working there).

Method — six weighted dimensions, each scored 0–100 from evidence, then a weighted
sum (weights must total 100; keep them fixed across all entities in the table):

| Dimension | Weight | What it measures |
|-----------|-------:|------------------|
| Product capability & breadth | 25 | how good/complete the product is at the core job-to-be-done |
| Market position & traction | 20 | share, named customers, adoption, revenue scale |
| Moat / defensibility | 20 | how hard it is to displace them (from `05`) |
| Technology & execution velocity | 15 | engineering quality, ship rate, reliability |
| Momentum / growth trajectory | 10 | are they gaining or losing ground, and how fast |
| AI positioning | 10 | how well-placed to win (not lose) as AI reshapes the layer (from `06`) |

Rules:
- Produce a **table**: one row per entity (the company first, then each rival), a
  column per dimension sub-score, and the final weighted 1–100. Then 1–2 sentences of
  **My read** per rival: on which axis the company beats or loses to them, with
  evidence.
- Sub-scores are evidence-based judgments, not vibes — tag the weak ones
  `[unverified]`/`[inference]`, and if a whole entity is thinly sourced, give a range
  and say so rather than a false-precision number.
- Band legend (reuse everywhere a 1–100 appears): **85–100** category leader ·
  **70–84** strong · **55–69** credible/mid-pack · **40–54** trailing · **<40** weak.

## Company Rating Template (`for-myself/06-company-rating.md`)

A single **1–100 "how good is this company to work at" score** from a fixed, weighted
rubric. It judges the **company itself and its general working style only** — so the
number is **comparable across every company you research**. **Hard exclusion:** do NOT
let personal preferences move it — location, visa/sponsorship, commute, your personal
comp target, or personal domain interest are handled elsewhere in `for-myself` and are
out of scope here.

Method — seven weighted dimensions, each scored 0–100 from evidence, then a weighted
sum (weights total 100):

| Dimension | Weight | What it measures (company-level, not personal) |
|-----------|-------:|------------------------------------------------|
| Future & growth potential | 25 | product/company trajectory, market tailwind, AI-era durability (from `05`/`06`) |
| Financial stability & stage | 20 | profitability/runway, funding health, layoff history, concentration risk (from `for-myself/01`) |
| Work–life balance & sustainability | 15 | realistic pace, hours, on-call, PTO culture (from `for-myself/03`) |
| Engineering culture & technical quality | 15 | rigor, autonomy, tooling, AI adoption, how they ship (from `07`) |
| Compensation competitiveness | 10 | pay/equity vs. market **as a company norm** (not your target) (from `for-myself/02`/`04`) |
| Career growth & learning | 10 | scope, mobility, mentorship, résumé/brand value |
| Employee sentiment & reputation | 5 | Glassdoor/Blind/Repvue trend + attrition signals (from `for-myself/04`) |

Rules:
- Show the **sub-score, the weight, and the contribution (sub-score × weight ÷ 100)**
  for each dimension, then the summed **final 1–100** and its band (same legend as the
  competitor scorecard).
- Cite evidence + a confidence tag per dimension. If key dimensions are `[unverified]`,
  give the score as a **range** and flag which facts would tighten it — never fake
  precision.
- End with a one-paragraph **My read**: the biggest upside, the biggest risk, and
  whether the headline number over- or under-states the reality.

## Why-This-Company Template (`10-why-this-company.md`)

The single most common interview question is "why do you want to work here (and why us
over competitor X)?" Prepare a **personalized, honest** answer grounded in the
candidate's *real* background and career interests — **not** generic enthusiasm.
Provide **at least two angles**, and when the application spans multiple role types
(e.g. a multi-posting `meta.yaml`), give an angle per distinct role type so the same
company research serves each interview.

**Personalization (read this):** ground every angle in the candidate's actual
background and **career-direction preferences** — from the profile
(`config.profile_md_path()`) and, when present, this skill's `references_private/`
notes, which **OVERRIDE** the generic guidance here (see "Before You Start"). In public
/ example mode (no `references_private/`), derive the threads from the profile and JD
only, and keep the candidate's specifics out of the tracked skill.

```markdown
## Angle 1 — <role type / framing> (e.g. the <specific posting> role)
- **The hook:** what *specifically* about this company/product/team pulls you in —
  concrete, drawn from `01`–`08` (a real product, hard problem, or bet), not a tagline.
- **Why you (fit):** the 2–3 genuine threads from your background + interests that
  connect to this exact role (traceable to the profile — never invented).
- **Why not competitor X / Y:** the specific, honest contrast (from `04`/`05`) — what
  this company has that the alternative doesn't, phrased as *your* reason to prefer it,
  not a knock on the rival.
- **The forward-looking line:** where you want to grow and why this role is the vehicle.

## Angle 2 — <different role type / framing>
(same structure, from a genuinely different angle)

## Curveballs
- "Why not <bigger rival / the obvious alternative>?" — a one-line honest answer.
- "Why leave your current company?" — grounded and non-negative.
```

## Question Bank Guidance (`09-question-bank.md`)

**Always open `09` with the candidate's own pitch — "Why this company / why not
competitors."** Before the questions to *ask*, `09` must lead with a required
`## Why this company / Why not competitors` section that answers the question the
candidate will be *asked*: summarize the prepared, personalized answer and link to the
fuller `10-why-this-company.md` (at least two angles, grounded in the candidate's real
background/interests — see the Why-This-Company Template). Name the specific
competitors this company is chosen *over* and the honest reason, drawn from `04`/`05`.
Keep personal specifics sourced from the profile / `references_private/`, never
invented.

Questions must make the user look like they already understand the product *and its
hard problems and strategy*. Beyond that pitch and the product-depth questions, this
file **must** include three deep groups:

- **Hard Problems & Challenges** — questions about the *specific* engineering and
  business challenges the company is solving (drawn from `03`). e.g. "You do X at Y
  scale — how do you handle <the constraint that makes it hard>, and where does it
  break today?"
- **Differentiation, Moat & Growth** — questions about **what makes them stand out,
  how defensible the moat is, and where growth comes from** (drawn from `05`).
  e.g. "Competitor Z takes approach A; you chose B — what did you see that made B
  worth the cost?" / "As <trend> commoditizes <layer>, what structurally keeps you
  the default — network effects, switching costs, or something else?" / "Where does
  the next order of magnitude of growth come from, and what's the biggest thing that
  has to go right?"
- **AI Strategy & Adoption** — questions about **AI-era survival, the AI-native
  roadmap, and how AI is actually used inside** (drawn from `06`). e.g. "You've
  shipped <AI feature>; where's the line today between what's in production and what's
  still prototype?" / "As LLMs commoditize <layer of your product>, what's the part
  competitors *still* can't copy — and is it your data, your distribution, or your
  workflow lock-in?" / "How AI-native is day-to-day engineering here — what's mandated
  vs. encouraged, and where has an agent/eval workflow actually replaced manual work?"

Also include: `For the Hiring Manager`, `For Engineers on the team`, `For a
Skip-level / Leadership`, `For the Recruiter (logistics)`. Prefer ~4–8 sharp
questions per group. Each question on its own line with a short parenthesized intent
tag; reference a *specific* product, repo, blog post, competitor, or customer.
Keep comp/WLB/visa probes out of this file (those are `for-myself`).

```markdown
### Hard Problems & Challenges

- (Architecture) Your <product> keeps <state> consistent across <N regions> — how
  do you handle <specific failure/consistency trade-off>, and where does it still
  hurt?

### Differentiation, Moat & Growth

- (Moat) <Competitor> bolts an agent layer on top of third-party transport; you own
  the whole stack — where does that vertical integration pay off most, and what does
  it cost you in speed?
- (Defensibility) If a well-funded rival copied <feature> tomorrow, what's the part
  they *still* couldn't replicate — and how do you know it's holding?
- (Growth) Where does the next 10x of revenue come from — new segments, new products,
  or deeper penetration — and what's the biggest risk to that path?

### AI Strategy & Adoption

- (Strategy) You've shipped <AI feature>; where's the line right now between what's in
  production and what's still a prototype, and what's the next thing you'd ship?
- (Moat under AI) As models commoditize <layer>, what's the part a well-funded rival
  *still* can't copy — your first-party data, distribution, or workflow lock-in?
- (Internal adoption) How AI-native is engineering day-to-day — what's mandated vs.
  encouraged (Cursor / Claude Code / agents), and where has an eval/agent workflow
  actually replaced manual work?

## Formatting Conventions

- Start each file with a title, one-line purpose, `Last researched: <date>`, and the
  confidence legend note. End every file with `## Sources` (URLs + the specific
  artifact, e.g. a blog post title, not just the domain).
- Deep-dive and differentiation files can run long — depth over brevity there.
  `02` can run long enough to teach the product from zero. Overview/role/for-myself
  files stay scannable (bullets, short sections).
- Confidence/inference tags go on the specific claim, not the whole file.
- README index: 4–6 bullet TL;DR ("the pitch + the bet, in your words"), file map,
  research date, master source list. Surface the headline numbers up top: company
  **size**, the **company rating (1–100)** with its band, and the company's rank +
  score in the **competitor scorecard**.

## Workflow

```
- [ ] Read AGENTS.md, LESSONS.md, the app meta.yaml + JD(s) + notes, and profile
- [ ] First-party pass: site (about/careers/blog/pricing/docs), GitHub, ATS teams/roles
- [ ] DEPTH pass: read eng blog posts/talks/founder interviews/HN in full (cite artifacts)
- [ ] Secondary pass: funding/valuation, headcount, ratings, visa (cite + date)
- [ ] Write 02 as a cold-reader product walkthrough with a concrete end-to-end example,
      then 03 technical-challenges-deep-dive (3–6 dives + My read)
- [ ] Write 05 moat & differentiation: contrarian bet + moat (5-Whys + evidence) +
      defensibility scorecard + growth potential + risks + My read
- [ ] Write 06 AI embrace: public (customer-facing) + private (internal adoption);
      AI-era survival + shipped-vs-planned + non-obvious AI edge ([inference]) + My read
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
  (dates/evidence), **(b)** a non-obvious AI edge derived from real assets and labeled
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
  with that pitch? Nothing invented beyond the profile / `references_private/`?
- **Concreteness:** Named subsystems/repos/posts/competitors/customers, not
  generalities?
- **Questions:** Do they probe the hard problems, the moat's durability, growth, and
  the AI strategy/adoption — not generic curiosity? Could a senior engineer at the
  company tell the user did real homework?
- **Honesty:** Every fact defensible under push-back or tagged `[unverified]`/
  `[inference]`? Nothing fabricated?
- **for-myself:** Genuinely useful for an offer decision; visa/H-1B flagged where
  unconfirmed? Every file ends with Sources; README carries the research date?
