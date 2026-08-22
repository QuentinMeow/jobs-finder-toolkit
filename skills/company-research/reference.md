# Company Research Operational Reference

**This file is read by section, on demand.** `SKILL.md`'s On-Demand Map names the
sections to read for each focused output; a full-folder run reads this file
completely. The hard gates in `SKILL.md` and the sourcing rules in
`dossier-guide.md` remain controlling.

## Handy Fetches

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

For funding/headcount/ratings/H-1B, web search (Bing HTML or the DuckDuckGo HTML endpoint via `curl`; they rate-limit — space them out) pointed at
Crunchbase/Dealroom/press/Glassdoor/h1bdata.info usually surfaces figures. Record the date; these change. Levels.fyi may be cited from user-supplied research,
but **never scrape it or schedule public-page collection**. Automated benchmark ingestion is allowed only from a user-supplied licensed export or licensed API
access, with the license/access method recorded in provenance.

When role research contributes reusable leveling or compensation facts, keep them in the schema-v2 company-level cache (the company-levels cache file format —
a different file from application `meta.yaml`, whose only supported schema is v5) rather than the `research/` folder: employer postings first, employer-authored
ladders second, licensed market benchmarks last. Record provenance per fact (provider, URL, retrieved date, geography, confidence, method, sample
size/statistic, and access/license). Keep base, stock, bonus, and total compensation separate, preserve location-specific bands, and never infer total
compensation.

## Maturity fetches

The two fetches that settle whether a product is GA, beta, or only announced
(`dossier-guide.md` § "AI Strategy Template" holds the maturity ladder these feed). A product-directory listing or a docs landing
page sometimes carries a stage badge and often does not, and its silence proves nothing; the statement that settles it lives in the launch post and in the **body** of the docs
overview and pricing pages. Strip each to text and grep it rather than reading the rendered nav:

```bash
# 1. The product's launch / announcement post, and the changelog entry if there is one.
#    Match PHRASES, not the bare word: a vendor's blog renders its whole tag list into every post,
#    and a tag cloud containing "Beta" otherwise produces a false hit on 100% of that vendor's posts.
STRIP='import sys,re,html;t=sys.stdin.read();t=re.sub(r"<(script|style).*?</\1>","",t,flags=re.S);t=re.sub(r"<[^>]+>"," ",t);print(re.sub(r"\s+"," ",html.unescape(t)))'
STAGE='(generally available|general availability|out of (open |private |closed )?beta|now GA|GA release|in (open|private|closed|public) beta|currently in beta|is in beta|enters? .{0,20}beta|early access|in preview|is experimental|waitlist|request access)'
NAV='([A-Z][A-Za-z]+ ){5}'   # 5+ consecutive Title-Case words = the site's tag list or nav, never a sentence
curl -s -L -A "Mozilla/5.0" "<launch-post-url>" | .venv/bin/python -c "$STRIP" \
  | grep -o -i -E ".{140}$STAGE.{140}" | grep -v -E "$NAV"
# Verified 2026-07-31 on three posts of one vendor: drops the tag-cloud false positive to zero while
# keeping both real "in private beta" sentences and the real "General Availability" sentence.

# 2. The docs OVERVIEW, PRICING and CHANGELOG/release-notes pages — body text, same grep.
#    For a vendor that ships continuously the DATED changelog entry usually settles it outright.
curl -s -L -A "Mozilla/5.0" "<docs-overview-url>" | .venv/bin/python -c "$STRIP" | grep -o -i -E ".{140}(beta|preview|early access|experimental|generally available).{140}"

# Many docs sites publish a plain-text mirror that skips the nav entirely. GREP it, never read it —
# these run to megabytes (Cloudflare's per-product llms-full.txt was ~1.1 MB / 31,553 lines on 2026-07-31).
# The `tr` is NOT optional: these mirrors are hard-wrapped, `.` never matches a newline in grep -E, and
# a 140+140 window almost never fits on one line — without it the command returns ZERO hits on a file
# that contains the answer three times, which this gate would then misread as `Ambiguous`.
curl -s -L "<docs-root>/llms-full.txt" | tr '\n' ' ' | grep -o -i -E ".{140}(beta|preview|generally available).{140}" | head
```

Read what the grep returns in context before classifying: "free during the open beta" on a pricing page is a **beta** statement, while "Available on all plans" is a
plan-entitlement line that says nothing about lifecycle stage, and a bare "Beta" inside a nav list or a blog tag cloud is not a statement at all. A zero-hit grep on both
fetches is the `Ambiguous` rung — but first confirm the grep can actually hit: run `grep -c -i beta` on the same fetch, and if that is non-zero while the windowed grep
returns nothing, your command is wrong, not the evidence. Record which URLs you checked; never promote a zero-hit to shipped.

## Output Location and Structure

Write to `config.companies_root()/<company>/research/` —
`private/me/interviews/companies/<company>/research/` with the overlay mounted, or
`examples/me/interviews/companies/<company>/research/` in a public checkout. The folder is
reusable interview preparation and outlives any one application (see `AGENTS.md` →
"Public vs Private"):

```text
<companies_root>/<company>/research/
├── README.md                                  # index, research date, TL;DR, sources
├── for-interview/                              # discuss/demonstrate WITH interviewers
│   ├── 01-company-overview.md                  # what they do, founding, stage, SIZE (headcount/revenue/valuation), thesis
│   ├── 02-product-and-technology.md            # products, how it works, architecture, stack
│   ├── 03-technical-challenges-deep-dive.md    # the HARD problems, why hard, how solved (multi deep-dive)
│   ├── 04-business-customers-competitors.md    # customers, market, monetization, rivals + 1–100 competitor scorecard (company vs each rival)
│   ├── 05-competitive-moat-and-differentiation.md  # why UNIQUE + moat/defensibility/growth (5-Whys, evidence)
│   ├── 06-ai-strategy-and-future.md            # AI embrace PUBLIC + PRIVATE; shipped vs planned, non-obvious AI edge, future bets
│   ├── 07-engineering-team-and-culture.md      # eng org, sibling teams, how they ship, values
│   ├── 08-role-deep-dive.md                    # THIS job: charter, scope, stack, fit, gaps
│   ├── 09-question-bank.md                     # WHY THIS COMPANY / why-not-competitors pitch + deep questions
│   └── 10-why-this-company.md                  # personalized "why you / why us / why not competitor X" answers (≥2 angles)
└── for-myself/                                 # personal offer-decision facts (not talking points)
    ├── 01-funding-and-company-stage.md
    ├── 02-compensation-and-benefits.md
    ├── 03-work-life-balance.md
    ├── 04-employee-ratings-and-sentiment.md
    ├── 05-visa-sponsorship-and-logistics.md
    └── 06-company-rating.md                    # 1–100 work-at score; company + working style only, NO personal prefs
```

## Per-File Rubrics and Templates

The blocks below are the per-file rubrics and skeletons `SKILL.md` points at. Read
only the one named for the file you are about to write. The depth bar, sourcing
rules, and the `03`, `05`, `06`, and `09` requirements live in
`dossier-guide.md`.

### Competitor Scorecard Template (in `04-business-customers-competitors.md`)

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

### 5 Whys, worked example (`05-competitive-moat-and-differentiation.md`)

Do this, don't just assert "network effects":

> Claim: "Our marketplace has network effects." → *Why a moat?* more buyers attract
> more sellers. → *Why can't a rival copy it?* they'd start with no liquidity. →
> *Why can't they buy liquidity with funding?* ... → if the honest answer is "a
> well-funded rival could subsidize both sides in a region," the moat is **local and
> contestable**, not absolute. **Evidence:** check take-rate stability, multi-homing
> rates, and whether a funded competitor already gained share in any market.

### Question Bank examples (`09-question-bank.md`)

Model questions for the three required groups in `09` (`dossier-guide.md` §
"Question Bank Guidance" holds the rules these illustrate):

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
  they *still* couldn't replicate from <product/repo> — and how do you know it's holding?
- (Growth) After <named customer> adopted <product>, where does its next 10x of
  revenue come from — new segments, new products, or deeper penetration — and what's
  the biggest risk to that path?

### AI Strategy & Adoption

- (Strategy) You've shipped <AI feature>; where's the line right now between what's in
  production and what's still a prototype, and what's the next thing you'd ship?
- (Moat under AI) As models commoditize <layer>, what's the part a well-funded rival
  *still* can't copy — your first-party data, distribution, or workflow lock-in?
- (Internal adoption) In <engineering post/repo>, you described <specific agent/eval
  workflow> — where has it actually replaced manual work, and where has it not?
```

### Why-This-Company Template (`10-why-this-company.md`)

The single most common interview question is "why do you want to work here (and why us
over competitor X)?" Prepare a **personalized, honest** answer grounded in the
candidate's *real* background and career interests — **not** generic enthusiasm.
Provide **at least two angles**, and when the application spans multiple role types
(e.g. a multi-posting `meta.yaml`), give an angle per distinct role type so the same
company research serves each interview.

**Personalization (read this):** ground every angle in the candidate's actual
background and **career-direction preferences** — from the profile
(`config.profile_md_path()`) and, when present, this skill's private notes at
`config.skill_references_dir()`, which **OVERRIDE** the generic guidance here (see
`dossier-guide.md` § "Before You Start"). In public / example mode (no such folder), derive the threads from the profile and JD
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

### Company Rating Template (`for-myself/06-company-rating.md`)

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
