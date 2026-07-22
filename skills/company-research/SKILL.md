---
name: company-research
visibility: public
description: Deeply research a company and the specific role for an interview — product, the hard technical challenges and why they're hard, competitive moat/defensibility/growth (evidence-based, 5-Whys — not company claims), AI strategy, eng culture, the role deep-dive, plus offer-decision facts (funding/stage, comp, WLB, ratings, visa/H-1B) and a hiring-manager/engineer question bank. Use when the user asks to research a company, prep for an interview, understand a company's product/challenges/moat/defensibility/growth/strategy, or build company-info for an application.
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
- **Go past the homepage.** Read engineering blog posts *in full*, docs
  architecture pages, conference talks, founder interviews/podcasts, GitHub
  issues/design docs, and HN/Reddit threads. Cite the specific artifact.
- **Be concrete.** Name the subsystem, the repo, the blog post, the customer, the
  competitor. Generic statements ("scalable, reliable infra") are banned.

If a section could have been written without reading anything specific to this
company, it is not done yet.

## When to Use

Use this skill when the user asks to:
- research a company they're interviewing with (product, challenges, moat, stage)
- understand the specific team/role they're applying for
- prep deep questions to ask a hiring manager or engineer interviewer
- gather personal-decision facts (funding/stage, comp, WLB, ratings, H-1B)
- build or refresh `interviews/company-specific/<company>/company-info/`

## Before You Start

1. Read `AGENTS.md` for repo guardrails (never fabricate; traceability).
2. Read this skill's `LESSONS.md` for operational knowledge.
   - **Personalization / private overrides:** if this skill folder has a
     `references_private/` directory, read every file in it — those candidate-specific
     notes and examples OVERRIDE the generic examples in this SKILL.md. When it is
     absent (public / example mode), use the generic examples here and take all
     candidate specifics from `config` and the profile.
3. Find the application record under `config.applications_root()/<status>/<slug>/`: its
   `meta.yaml`, the JD file(s) `source/JD-*.md`, and `notes.md` if present.
4. Skim your candidate profile (`config.profile_md_path()`) so research and questions connect to
   the candidate's real background and needs — take their domain/experience from the profile
   and their location + visa-sponsorship requirements from `config.location_policy()` and the
   profile's sponsorship flags (never assume a specific metro or visa status here).
5. **Scratch stays in `tmp/`** (fetched HTML/JSON in `tmp/web_artifacts/`, probe scripts in
   `tmp/scratch/`) — never the repo root or the `interviews/` tree (only finished notes belong
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

### Handy fetches

```bash
# Company GitHub org + top repos (languages, stars, activity = real signal)
curl -s "https://api.github.com/orgs/<org>"
curl -s "https://api.github.com/repos/<org>/<repo>"

# Ashby ATS: team list + all open roles (org structure & sibling teams)
curl -s -X POST "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams" \
  -H "Content-Type: application/json" \
  -d '{"operationName":"ApiJobBoardWithTeams","variables":{"organizationHostedJobsPageName":"<org>"},"query":"query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!){ jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName){ teams{ name parentTeamId } jobPostings{ title teamId locationName employmentType } } }"}'
# Greenhouse ATS board (teams + roles):
curl -s "https://boards-api.greenhouse.io/v1/boards/<org>/jobs?content=true"

# Strip a page (blog/docs/marketing) to readable text for close reading
curl -s -L -A "Mozilla/5.0" "<url>" | .venv/bin/python -c "import sys,re,html;t=sys.stdin.read();t=re.sub(r'<(script|style).*?</\1>','',t,flags=re.S);t=re.sub(r'<[^>]+>',' ',t);print(re.sub(r'\s+',' ',html.unescape(t))[:12000])"
```

For funding/headcount/ratings/H-1B, web search (Bing HTML or the DuckDuckGo HTML
endpoint via `curl`; they rate-limit — space them out) pointed at
Crunchbase/Dealroom/press/Glassdoor/h1bdata.info usually surfaces figures. Record the
date; these change. Levels.fyi may be cited from user-supplied research, but **never
scrape it or schedule public-page collection**. Automated benchmark ingestion is allowed
only from a user-supplied licensed export or licensed API access, with the license/access
method recorded in provenance.

When role research contributes reusable leveling or compensation facts, keep them in the
schema-v2 company-level cache (the company-levels cache file format — a different file from
application `meta.yaml`, whose only supported schema is v3) rather than `company-info/`:
employer postings first,
employer-authored ladders second, licensed market benchmarks last. Record provenance per
fact (provider, URL, retrieved date, geography, confidence, method, sample size/statistic,
and access/license). Keep base, stock, bonus, and total compensation separate, preserve
location-specific bands, and never infer total compensation.

## Output Location & Structure

Write to `interviews/company-specific/<company>/company-info/` (real interview products mount
under the private overlay — `private/interviews/...`; see `AGENTS.md` → "Public vs Private"):

```
interviews/company-specific/<company>/company-info/
├── README.md                                  # index, research date, TL;DR, sources
├── for-interview/                              # discuss/demonstrate WITH interviewers
│   ├── 01-company-overview.md                  # what they do, founding, stage, size, thesis
│   ├── 02-product-and-technology.md            # products, how it works, architecture, stack
│   ├── 03-technical-challenges-deep-dive.md    # the HARD problems, why hard, how solved (multi deep-dive)
│   ├── 04-business-customers-competitors.md    # customers, market, monetization, rivals
│   ├── 05-competitive-moat-and-differentiation.md  # why UNIQUE + moat/defensibility/growth (5-Whys, evidence)
│   ├── 06-ai-strategy-and-future.md            # AI thesis, roadmap signals, future bets
│   ├── 07-engineering-team-and-culture.md      # eng org, sibling teams, how they ship, values
│   ├── 08-role-deep-dive.md                    # THIS job: charter, scope, stack, fit, gaps
│   └── 09-question-bank.md                      # deep questions for HM / engineers / leadership
└── for-myself/                                 # personal offer-decision facts (not talking points)
    ├── 01-funding-and-company-stage.md
    ├── 02-compensation-and-benefits.md
    ├── 03-work-life-balance.md
    ├── 04-employee-ratings-and-sentiment.md
    └── 05-visa-sponsorship-and-logistics.md
```

Rules:
- Create the whole folder. Scaffold thin files with `[unverified]` + where-to-look;
  never invent to fill space.
- `for-interview` = things to *discuss/demonstrate* (depth + POV);
  `for-myself` = things to *know/decide*. Keep comp/WLB/visa out of the question
  bank; they live in `for-myself`.
- Always produce `03`, `05`, and `09` — the deep-dive and differentiation files and
  the question bank are the point of this skill.

## What Goes in Each File

**for-interview/**
- **01 company-overview** — one-liner, founding, HQ/remote, stage, headcount, the
  company *thesis* (the bet they're making about the world) — with confidence tags.
- **02 product-and-technology** — product portfolio, **how it actually works**
  (architecture / data flow, not a feature list), the real tech stack (JD + docs +
  GitHub), OSS footprint, what's technically notable.
- **03 technical-challenges-deep-dive** — the centerpiece. See template below.
  **3–6 deep dives**, each on a genuinely hard problem at their scale.
- **04 business-customers-competitors** — who pays and why, named customers, market
  and monetization model, the competitor set (named).
- **05 competitive-moat-and-differentiation** — the second centerpiece. See
  template below. Why the product/path/direction is *unique* (the contrarian bet) and
  a rigorous, **evidence-based** assessment of the **product moat / sustainable
  competitive advantage**, **how defensible it is against each competitor**, and its
  **growth potential** — every moat/defensibility/growth claim stress-tested with a
  **5-Whys** chain that stops at evidence, not company claims.
- **06 ai-strategy-and-future** — the AI thesis, how AI reshapes the roadmap,
  recent launches as evidence, and plausible/defensible future directions.
- **07 engineering-team-and-culture** — eng org and sibling teams (ATS list is
  gold), how they ship, engineering values, OSS/community posture.
- **08 role-deep-dive** — the team's charter, concrete scope, stack, success bar,
  an honest **fit map** to the user's real experience, and **gaps to prepare for**.

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

## Question Bank Guidance (`09-question-bank.md`)

Questions must make the user look like they already understand the product *and its
hard problems and strategy*. Beyond product-depth questions, this file **must**
include two deep groups:

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
```

## Formatting Conventions

- Start each file with a title, one-line purpose, `Last researched: <date>`, and the
  confidence legend note. End every file with `## Sources` (URLs + the specific
  artifact, e.g. a blog post title, not just the domain).
- Deep-dive and differentiation files can run long — depth over brevity there.
  Overview/role/for-myself files stay scannable (bullets, short sections).
- Confidence/inference tags go on the specific claim, not the whole file.
- README index: 4–6 bullet TL;DR ("the pitch + the bet, in your words"), file map,
  research date, master source list.

## Workflow

```
- [ ] Read AGENTS.md, LESSONS.md, the app meta.yaml + JD(s) + notes, and profile
- [ ] First-party pass: site (about/careers/blog/pricing/docs), GitHub, ATS teams/roles
- [ ] DEPTH pass: read eng blog posts/talks/founder interviews/HN in full (cite artifacts)
- [ ] Secondary pass: funding/valuation, headcount, ratings, visa (cite + date)
- [ ] Write 02 product/tech, then 03 technical-challenges-deep-dive (3–6 dives + My read)
- [ ] Write 05 moat & differentiation: contrarian bet + moat (5-Whys + evidence) +
      defensibility scorecard + growth potential + risks + My read
- [ ] Write 01, 04, 06, 07, 08 (facts + POV + confidence tags + Sources)
- [ ] Write for-myself/ 01–05
- [ ] Write 09 question-bank incl. Hard-Problems and Differentiation/Moat/Growth groups
- [ ] Write README index + TL;DR
- [ ] Final check (below)
```

## Final Checks

- **Depth:** Does every `for-interview` file contain something you could only write
  after reading company-specific material? Does `03` explain *why each problem is
  hard*, and `05` explain *why the path is unique* — each with a **My read** POV?
- **Moat rigor:** In `05`, is each moat claim tested with a **5-Whys chain that ends
  in evidence** (not a restated company claim)? Is there a **defensibility verdict**
  per competitor/threat and an **evidence-based growth-potential** read? Are
  **Claim / Evidence / Judgment** kept distinct?
- **Concreteness:** Named subsystems/repos/posts/competitors/customers, not
  generalities?
- **Questions:** Do they probe the hard problems, the moat's durability, and growth —
  not generic curiosity? Could a senior engineer at the company tell the user did
  real homework?
- **Honesty:** Every fact defensible under push-back or tagged `[unverified]`/
  `[inference]`? Nothing fabricated?
- **for-myself:** Genuinely useful for an offer decision; visa/H-1B flagged where
  unconfirmed? Every file ends with Sources; README carries the research date?
