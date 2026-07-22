# Approach 2 — Script-first handoff (move mechanical work out of agent context)

**Strategy:** The cheapest token is the one an agent never sees. Everything that is
deterministic — re-filtering search results, scaffolding an application folder,
copying structured facts into `meta.yaml`, fetching and saving a JD — becomes a
script the agent *invokes* instead of a procedure the agent *performs*. No mode
switch; quality is unaffected by construction because only mechanical steps move.

## Measured motivations (from the baseline experiment run)

- **Repeated full fetches.** Widening a freshness window (`--max-age-days 0.084` → `1`
  → `3`) plus one `--json-out` re-run cost 7 full pipeline invocations in one session
  — each re-fetching ~12k postings from 100+ boards. The fetch results were identical;
  only the filter changed. Each run also re-printed its output into agent context.
- **Manual fact transcription.** The drafting workflow has an agent copy ~10 structured
  fields (level, YOE, salary, URLs, dates) from search output into `meta.yaml` by hand
  — token-expensive, and the step where transcription errors happen.
- **Lossy, repeated JD fetching.** The search agent fetched JDs via an AI-summarizing
  web tool, then each drafting agent re-fetched the same URL again.
- **Raw dumps into context.** Full ranked tables and JSON records were printed into
  agent context when only a handful of fields were needed.

## How it works

1. **Fetch cache + re-filter.** `search_jobs.py --cache-dir tmp/search_cache/` writes
   the normalized postings snapshot; `--refilter` re-runs *filter → score → rank* from
   the snapshot without refetching. Widening a window, changing `--top-k`, or adding
   `--json-out` after the fact becomes seconds and near-zero tokens (and stops
   hammering the sources — a "Respect the sources" win too).
2. **`handoff.py` (job-search → resume-writer bridge).** Input: the search JSON + a
   selected row. Output: the application folder skeleton — `source/JD-<job title>.md`
   (fetched and saved as raw text), `meta.yaml` schema v3 with every structured fact
   carried over, `--enrich-metadata` invoked. The agent's first sight of the
   application is a folder that already passes `--check-metadata`; its job starts at
   gap analysis and tailoring, the judgment part.
3. **Compact output contract.** Default stdout becomes a top-K compact table (rank,
   company, title, score, level, age, visa, URL); full detail goes to the JSON file.
   Agents needing one field run a provided one-liner (`jq`-style) instead of dumping
   records.
4. **Tailoring card.** `build_tailoring_card.py` compiles the candidate profile,
   baseline, skills lists (Approved/Weak/Never), and a distilled story-bank digest
   into one regenerated-on-change context file (~1.5–2k tokens). Drafting agents read
   the card; the full profile + story bank become full-fidelity sources consulted
   only when the card flags a relevant deep-dive pointer.
5. **Raw JD fetcher.** A small script downloads a posting URL and extracts readable
   text verbatim (no AI summarization), so the JD saved to `source/` is faithful and
   fetched exactly once.

## Pros

- **Zero quality trade-off by design.** Only deterministic steps move; every judgment
  step (ranking interpretation, gap analysis, tailoring, prose) stays with the agent.
  Several steps get *more* reliable (schema written by code, JD saved verbatim,
  no transcription drift).
- **Fixes the worst measured hotspots** (repeat fetches, transcription, dumps) and
  reduces wall-clock and network load at the same time.
- **No new user-facing concepts.** No modes, no config. The SKILL.md workflow gets
  *shorter* (steps collapse into "run handoff.py"), which compounds with Approach 1.
- Savings scale with fan-out: every drafting agent skips the same mechanical steps.

## Cons

- **Engineering + maintenance cost.** New scripts need tests, vendoring sync
  (`scripts/shared/` rules), and eval-gated SKILL.md updates to teach agents to use
  them.
- **Doesn't touch the boot tax.** Agents still read the full instruction stack; the
  fixed ~30–40k tokens per drafting agent remain (that's Approach 1's job).
- **Cache invalidation semantics** need care (snapshot staleness vs "fresh postings"
  is exactly what this toolkit is about; the cache must be per-session/short-TTL).
- The tailoring card is a derived artifact — it can go stale relative to the profile
  if the regeneration hook (gardener / pre-commit) is skipped.
