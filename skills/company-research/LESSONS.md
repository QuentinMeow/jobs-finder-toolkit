# Company Research — Lessons

Operational sourcing gotchas + evidence pointers for this skill (not company-specific facts —
those go in the per-company research folders). The long-form depth bar, moat/5-Whys
method, and file requirements live in `dossier-guide.md`; `SKILL.md` routes the
requested mode. This file only carries what's additive to them.

Last reviewed: 2026-07-19

Lifecycle tags: each `##` section carries `<!-- added: <first-seen> · last_confirmed: <date> · status: active -->`
(gardener `lessons_report` parses these; `added` = the section's first git appearance, `last_confirmed` = last review date).

## Sourcing gotchas
<!-- added: 2026-07-18 · last_confirmed: 2026-07-19 · status: active -->
- The company's own **ATS board is the best org-structure signal**: the team list plus every
  open role reveals sibling teams, where the target team sits, and where headcount is going.
  Ashby exposes this via `ApiJobBoardWithTeams` (query in `reference.md`); Greenhouse/Lever have similar
  public JSON boards.
- A company's **GitHub org** gives real, uninflated signal: repo languages = actual stack,
  stars = adoption, `created_at` = age, commit recency = activity. Stronger than marketing copy
  for OSS-heavy companies.
- Marketing pages are usually **Next.js**; the readable copy is present in the HTML once you
  strip `<script>`/`<style>`/tags. `/about` often lists investors;
  `/blog` reveals the real roadmap by recency.
- **Funding figures conflict across sources and over time.** Record amount, round, date, lead
  investor, and source URL per data point; note the conflict rather than silently picking one.
- **Ratings sites (Glassdoor/Levels/Blind) frequently block `curl`.** If unfetchable, scaffold
  the file with links + `[unverified]` — do not invent a rating. Never scrape or schedule public
  Levels.fyi collection (reusable imports require a user-supplied licensed export/API + provenance).
- **Visa/H-1B**: JDs usually omit sponsorship policy; "Remote, U.S." ≠ sponsors. Default to
  `[unverified] — confirm with recruiter`; MyVisaJobs / USCIS H-1B data confirms *past*
  sponsorship, not current policy.

## What a usable exemplar looks like
<!-- added: 2026-07-18 · last_confirmed: 2026-07-31 · status: active -->
- Depth lives in the engineering blog, talks, and founder interviews — read those *in full* and
  extract the trade-off, not the headline. The posts worth citing name a constraint the company
  could not buy its way out of, and say what it cost: splitting a datastore that had outgrown one
  node and what that did to consistency; a real-time system's tail latency and cold-start budget
  forcing an architecture nobody wanted. If a section reads like a press release (headcount,
  funding, a tagline), it isn't done.
- **Name the companies in the per-company research folders, never in this file.** A company named
  here says which companies the candidate is researching, and the leak rule keeps real employers
  out of the public tree. Neither armed gate catches it — a company name is not an identity token
  — so it is on the editor. Describe the shape of the exemplar instead, as above.

## Best evidence sources for moat/growth
<!-- added: 2026-07-18 · last_confirmed: 2026-07-19 · status: active -->
- S-1/10-K/earnings (retention, cohort, segment growth, concentration risk), pricing pages
  (pricing power), churn/multi-homing discussion on HN/Reddit, and whether competitors' *funded*
  attempts actually moved share. TAM slides are marketing — mark aspirational reach `[inference]`.

## Writing
<!-- added: 2026-07-18 · last_confirmed: 2026-07-19 · status: active -->
- Overview/role files are **scanned** (keep tight); `03` technical-challenges and `05`
  differentiation are **studied** (let them run long, always end with a **My read** POV).
- The question bank lands best when a question names a **specific** product, repo, blog post,
  competitor, or customer. `dossier-guide.md` mandates **three** deep groups — "Hard Problems &
  Challenges", "Differentiation, Moat & Growth" and "AI Strategy & Adoption" — and that list,
  not this one, is authoritative.
