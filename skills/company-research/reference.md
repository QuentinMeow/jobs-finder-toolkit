# Company Research Operational Reference

Read this reference before live research and again before writing company-info outputs. The sourcing rules in `SKILL.md` remain controlling.

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
a different file from application `meta.yaml`, whose only supported schema is v3) rather than `company-info/`: employer postings first, employer-authored
ladders second, licensed market benchmarks last. Record provenance per fact (provider, URL, retrieved date, geography, confidence, method, sample
size/statistic, and access/license). Keep base, stock, bonus, and total compensation separate, preserve location-specific bands, and never infer total
compensation.

## Output Location and Structure

Write to `interviews/company-specific/<company>/company-info/` (real interview products mount under the private overlay — `private/interviews/...`; see
`AGENTS.md` → "Public vs Private"):

```text
interviews/company-specific/<company>/company-info/
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
