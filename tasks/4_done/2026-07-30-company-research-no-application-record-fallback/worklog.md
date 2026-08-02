# Worklog — 2026-07-30-company-research-no-application-record-fallback

## 2026-07-31 — session 1 (agent, fix/10-company-research-correctness)

- Verified the claim: `SKILL.md` "Before You Start" step 3 said only "Find the application
  record under `config.applications_root()/<status>/<slug>/`" with no branch for its
  absence, and `09`'s rule to "link to the fuller `10-why-this-company.md`" had no case for
  `10` not existing. Both hold exactly as filed.
- Confirmed the case is the common one, not an edge: under the example config there is one
  application (Example Corp), so every Cloudflare canary in the frozen set runs with no
  application record — 4 of the 6 canaries take this path.
- Answered the task's three questions in `SKILL.md` step 3, in one place:
  1. **Full folder**, not a reduced set. Only three outputs are posting-specified; the
     other 14 are company-level and unaffected, so stopping before `08` would drop work
     that needed no posting.
  2. **Marked** `[JD-dependent]`, so a later run with the application re-targets those
     lines instead of rewriting the file — the cheaper of the two improvised answers.
  3. **Link forward**, never inline. The summary `09` already owes is the deliverable and
     the link is a pointer; inlining a whole template duplicates content that then drifts.
- Gave the three posting-dependent outputs a real subject rather than a scope apology: the
  role family from the company's own ATS board, which the skill already fetches and which
  needs no application.
- Added a `cr-full-research-structure` rubric bullet + failure mode so the path is tested.

### After the canary run (same session)

Three fixes, all from cases the runs hit that the first draft did not name:

- **The requested role family may not exist on the ATS board.** The canary's company has no
  req with the requested title and ~10 platform-adjacent reqs under four different readings
  of the word. The run built a four-readings table unguided. Now instructed: enumerate the
  closest real reqs, name the ambiguity, `[JD-dependent]`-tag the choice, never invent a
  posting.
- The request often names no role at all — added.
- "Produce the whole folder anyway" read as mandating a full folder even for a single-file
  request. Now: company scope changes a file's *subject*, never how many files you write.
