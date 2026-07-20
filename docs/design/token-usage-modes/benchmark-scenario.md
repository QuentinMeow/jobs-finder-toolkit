# Benchmark scenario (v1.1) — one search + two drafted applications

**Status:** pinned (2026-07-20; v1.1 same day — the first v1 attempt was
invalidated when the day's heavily pre-mined pipeline state yielded zero
eligible candidates, so v1.1 pins the run *independent of mutable pipeline
state*; an invalidated attempt is recorded in the results file but its tokens
never enter a row). This is the fixed, testable definition of the
token-usage benchmark. Every future row in the README table and every stage
gate compares against a run of *this* scenario, like-for-like. The Stage-1
result (`evals/results/stage1-benchmark-20260720.md`) rose +15% partly because
the run's scope drifted from the baseline's — more profiles, deeper research,
more deliverables. This doc removes each of those drift axes so a row measures
**cost, not scope**.

**Reference row:** run the scenario below on `main` @ `627a393` from a worktree
checked out at that SHA, before any Stage-2 change merges. All later rows are
deltas against that reference.

**Runner model:** the same mid-tier model family pinned in the existing
`evals/results/` files (model-pinned protocol). A runner-tier change
invalidates comparison with every prior row — re-baseline the reference before
comparing. Implementation/verification of code may use a higher tier; the
measured subject agents run the pinned mid-tier.

## 1. Search — exactly one search subagent, one profile

- **Profile:** a **benchmark-labeled copy** of the owner's default profile
  (identical criteria, name suffixed for benchmark provenance) — **one profile
  only**. No second profile, no ad-hoc criteria. The copy keeps benchmark
  discovery artifacts separate from real runs and is passed by *name* (never a
  filesystem path — a path argument leaks into the discoveries filename).
- **Pipeline-state neutrality (v1.1):** run with `--include-recent` and
  `--include-considered` so the row does not depend on how recently the
  private pipeline was mined or synced — both skips key off mutable private
  logs that vary day to day. The **folder-based duplicate check** (below)
  remains the real gate against re-drafting anything already in the pipeline.
  The snapshot cache starts **cold** (cleared before the run), so every row
  pays exactly one fetch per widening step at most.
- **Freshness / widening policy (fixed):** start at **last 2 hours**
  (`--max-age-days 0.084`). Widen **stepwise to 1 day, then to 3 days**, and
  *only* when the current window yields **fewer than 2 eligible candidates**
  (eligible = passes location/visa/blacklist/log gates and JD-text
  verification, **and** has no existing folder for the same company+role in
  any stage of the owner's pipeline — a duplicate would trip the drafting
  skill's preflight refusal and measure a refusal, not a draft). Stop at the
  first window with ≥2 eligible, or at 3 days.
- **One fetch, then refilter.** Fetch once into the snapshot cache
  (`tmp/search_cache/`); perform each widening step with `--refilter latest`
  (zero network). A fresh fetch is permitted **at most once per widening step**
  and only when the snapshot is absent or stale (`--refilter` refuses a
  snapshot >6h old). Re-fetching when a refilter suffices is **forbidden**.
- **JD-text verification (required, every candidate).** Before any handoff,
  fetch each candidate's posting verbatim with `fetch_jd.py` and verify the
  real workplace/visa/role facts against the JD text (this is the checking the
  design deliberately keeps — the market-scraper `remote`/`visa` heuristics are
  advisory). On HTTP failure (e.g. a `403` from the source), save the
  scraper-extracted description **with a provenance note** and proceed — the
  documented fallback.
- **Selection + handoff:** take the **top 2 eligible candidates by rank** and
  scaffold each with `handoff.py` (`--select "rank N"`), which writes the
  folder, the verbatim `source/JD-<title>.md`, and a schema-v3 `meta.yaml`.
- **Forbidden (drift guards):** second-profile sweeps, market-scan / landscape
  reports, and re-fetching when a `--refilter` would answer the same question.

## 2. Drafting — exactly two drafting subagents, one handoff each

Each of the two drafting agents takes **one** handed-off folder and runs it
**end-to-end**: tailor (`tailored.yaml` from the baseline) → render → `check.py`
**PASS** → the bundled `..._Application_<title>.txt` and rendered cover letter
that the skill requires. Fixed caps:

- **Render cycles ≤ 3** (target **1–2**). The Stage-0 baseline-wording fix
  removed the collision that inflated cycles; a third cycle should be a genuine
  layout/gate catch, not a false positive.
- **Company/product research ≤ 2 web fetches per cover letter.** Research is
  per-JD and real, but capped.
- **Deliverable set is exactly the skill's required artifacts** for a
  single-role folder: one resume (DOCX in `source/` + PDF at root), one bundled
  application `.txt`, one cover letter (DOCX + PDF), `meta.yaml`, `notes.md`.
  **No extra deliverables** (no market memos, no secondary resumes, no
  speculative letters).
- **Step 7** (uncategorized-skill questions) runs per the skill's one-at-a-time
  protocol.
- **Benchmark hygiene:** mark each folder's `notes.md` with benchmark
  provenance, and **never run `status.py --sync-log`** — a benchmark run must
  not pollute the real applications/company-search logs.

## 3. Measurement

- **Per-subagent totals** — tokens, tool calls, wall clock — read from the
  harness's task-completion usage line, one row per agent (search, draft A,
  draft B, total).
- **Self-audit** — each agent reports the files it read (`wc -c`) and any large
  command outputs, as in the baseline experiment, so the boot tax and any
  archaeology stay visible.
- **Recording** — append one summary row to the README table under
  "Projected effect on the measured run", and record the full per-agent
  breakdown + analysis in a dated `evals/results/` file.

## 4. Invariants (identical to production — never relaxed for a benchmark)

The hard gates run exactly as in a real run: **blacklist + applications-log +
company-search-log pre-flight**, the **location gate** (`--check-locations` must
report `match`), **schema-v3 validation** (`--check-metadata`), **`check.py`**
(render + page + honesty gates), and the **no-fabrication** rules (every posting
traceable to a real `source`+`url`; every résumé claim traceable to the profile
or supporting library). Benchmark artifacts are written into the **private
overlay** and are **user-reviewed** (keep or delete) — they are never committed
to the public tree and never auto-logged.

## What this pins vs. the unpinned runs

The baseline (~437k) and the Stage-1 row (~502k) ran materially different
scopes. v1 fixes the four drift axes the Stage-1 analysis called out:

- **Profile count** — pinned to **one** profile (Stage-1 did a second-profile
  market sweep).
- **Verification depth** — **JD-text check of every candidate**, kept but
  bounded (one `fetch_jd.py` per candidate, documented `403` fallback).
- **Research depth** — **≤2 web fetches per cover letter** (Stage-1's per-letter
  research was uncapped).
- **Deliverable set** — **exactly the skill's required artifacts** for two
  single-role folders; no extra memos, scaffolds, or letters.

With these fixed, a later row moving up or down reflects the mechanism under
test (instruction tiering, card-first context, capped cycles), not a change in
how much work the scenario asked for.
