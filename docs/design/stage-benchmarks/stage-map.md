# Stage map — job-search → application-drafting

The operative stage decomposition that `protocol.md` pins: the two subject legs (search, draft)
broken into stages with per-stage token/wall-clock estimates (§A), and, for each stage, the pinned
fixture that isolates it plus its observable boundary (§D). Stage rows are comparable only against
other rows of the **same** stage (an isolated stage re-pays boot and loses cross-stage carryover —
see `protocol.md`, "Why stages"). Absolute per-stage numbers are estimates; the boundary definitions
are exact.

## Sources & method

- **Leg totals** (calibration anchors) from the most recent measured full row,
  `evals/results/stage3-benchmark-20260720.md` (token_saving default, `claude-sonnet-5`):
  - **search** 121,391 tok / 66 calls / ~9.1 min
  - **draft A** 169,243 tok / 63 calls / ~13.6 min
  - **draft B** 162,039 tok / 76 calls / ~13.4 min (a "typical draft" ≈ 165k / 70 / 13.5 min)
- **Self-audit byte deltas** from `stage2-benchmark-20260720.md`: post-tiering boot reads were
  AGENTS 13,449 B + job-search skill 17,299 B (search) / AGENTS 13,449 B + resume skill 24,844 B
  (draft); the draft leg additionally read **reference.md + validator source ≈ 59–70 KB**.
- **Live instruction/context file sizes** (bytes; `tok ≈ bytes/4`, the repo convention from
  `scripts/metrics/instruction_budget.py`):

  | Instruction / context file | bytes | ~tok | Boot? |
  |---|---:|---:|---|
  | `AGENTS.md` (core) | 14,282 | 3.6k | yes, both legs |
  | `docs/AGENTS-ANNEX.md` | 37,645 | 9.4k | on-demand |
  | job-search `SKILL.md` | 18,689 | 4.7k | yes, search |
  | job-search `reference.md` | 25,219 | 6.3k | on-demand |
  | job-search `LESSONS.md` | 6,921 | 1.7k | yes, search |
  | resume-writer `SKILL.md` | 26,950 | 6.7k | yes, draft |
  | resume-writer `reference.md` | 34,539 | 8.6k | **discretionary (full-read observed)** |
  | resume-writer `LESSONS.md` | 6,937 | 1.7k | yes, draft (render internals) |
  | `check.py` **source** | 36,824 | 9.2k | **discretionary (full-read observed)** |
  | application-tracker `SKILL.md` | 19,724 | 4.9k | discretionary (schema owner) |
  | tailoring card | 9,307 | 2.3k | yes, draft (card-first) |
  | baseline resume yaml | 4,320 | 1.1k | yes, draft |
  | candidate profile (`<profile>.md`) | 13,557 | 3.4k | on-trigger only |
  | story bank (1 file) | 23,874 | 6.0k | on-trigger only |
  | one JD (`source/JD-*.md`, median) | ~13,000 | ~3.3k | per candidate (range 10–26 KB) |

- **Per-stage token estimates** allocate each leg total across stages, weighted by (a) face-value
  reads/stdout, (b) share of tool calls, and (c) generation/reasoning volume, then calibrated so the
  stage shares sum to the measured leg total. The gap between summed face-value reads (~40k/draft)
  and the 165k leg total is **context carryover** (accumulated context is re-billed every turn) plus
  generation, distributed across stages proportional to how many turns each spans. Confidence stated
  per stage. **Key consequence for levers:** a byte cut at *boot* is amplified by carryover across all
  subsequent turns, so its realized cumulative saving exceeds its face value; a cut in a late,
  single-turn stage is not amplified.

---

## A. Stage map

### A.1 Search leg (~121k tok / 66 calls / ~9.1 min)

| # | Stage | Inputs read (files + ~KB) | Scripts invoked (+ typical stdout) | Network | Artifacts written | ~tok (share) | wall-clock share | Conf |
|---|---|---|---|---|---|---:|---:|---|
| S1 | Boot / instruction reading | `AGENTS.md` 14 KB, job-search `SKILL.md` 19 KB, `LESSONS.md` 7 KB (+ `config` accessor) | — | — | — | **18k (15%)** | ~1.0 min | M |
| S2 | Profile + config load | `profiles/<label>.yaml` ~1–2 KB; `config.location_policy()/generation_mode()` | — | — | — | 3k (2%) | ~0.2 min | H |
| S3 | Fetch (network) | — | `search_jobs.py --profile` → ~5-line summary + top-K compact table (~1–2 KB stdout); writes snapshot | fetch ~11k postings, 100+ boards + aggregators (~20s) | `tmp/search_cache/<profile>-stage1-<ts>.json` (+ `-latest`); `1_discoveries/<date>-<profile>.md` | 9k (7%) | ~0.7 min | M |
| S4 | Filter / rank + widening refilters | compact table stdout re-read | `search_jobs.py --refilter latest --max-age-days …` ×2 (2h→1d→3d), zero network, summary+table each | none (cache) | discoveries file overwrite | 7k (6%) | ~0.4 min | M |
| S5 | Duplicate + blacklist preflight | (scripted skip: registry + logs) | in-pipeline `already-considered/recently-searched/blacklist` skip; counts in summary. Folder-based dup scan | — | — | 4k (3%) | ~0.2 min | L-M |
| S6 | **JD-text verification per candidate** | **each candidate's JD ~13 KB read in full** (×~4–6: 2 handed off + rejections) | `fetch_jd.py <URL> --out …` per candidate (stdout = path+bytes only); ATS-API fallback for JS-rendered pages | 1 fetch/candidate + ATS-API refetches for JS pages | `tmp/web_artifacts/*.md` verbatim JD text | **34k (28%)** | ~2.8 min | M |
| S7 | Location / visa gates | reasoning over JD text (overlaps S6) | `status.py --check-locations` on handoff folders | — | — | 8k (7%) | ~0.4 min | L-M |
| S8 | Handoff scaffolding | selected search-JSON row | `handoff.py --json … --select "rank N"` ×2 → folder + verbatim `source/JD-*.md` + schema-v4 `meta.yaml`; validates; stdout = folder path + status | 1 JD re-fetch/handoff (via `fetch_jd`) | `6_drafted/<slug>/` folder, `meta.yaml`, `source/JD-*.md` | 10k (8%) | ~0.9 min | M |
| S9 | Metadata + present/finish | `--check-metadata` output | `status.py --check-metadata`; (`--sync-log` skipped in benchmark) | — | (log writes suppressed in benchmark) | 18k (15%) | ~0.5 min | L-M |
|   | *residual reasoning/carryover* | | | | | ~10k (8%) | | |

**Dominant search cost = S6 JD-text verification (~28%)** — multiple full ~13 KB JD reads plus the
ATS-API fallback for JS-rendered pages. Boot (S1, 15%) and present/finish (S9, 15%) are the next
tier. Network wall-clock concentrates in S6 (per-candidate fetch + JS fallback) and S8 (JD re-save).

### A.2 Draft leg (~165k tok / ~70 calls / ~13.5 min)

| # | Stage | Inputs read (files + ~KB) | Scripts invoked (+ typical stdout) | Network | Artifacts written | ~tok (share) | wall-clock share | Conf |
|---|---|---|---|---|---|---:|---:|---|
| D1 | Boot / instruction reading | `AGENTS.md` 14 KB, resume `SKILL.md` 27 KB, `LESSONS.md` 7 KB | — | — | — | **20k (12%)** | ~0.9 min | M |
| D2 | Card / profile context | tailoring card 9.3 KB + baseline 4.3 KB (card-first); full profile 13.5 KB + story sections **only on trigger** | `build_tailoring_card.py --check` if staleness suspected | — | (card rebuild only if stale) | 4k (3%) | ~0.3 min | M |
| D3 | JD analysis (Step 2) | JD ~13 KB read in full | — | — | — | 12k (7%) | ~0.6 min | M |
| D4 | Company research (per JD) | fetched web pages (2 × ~10–40 KB) | — (agent web fetch) | **≤2 web fetches / cover letter** | — | 15k (9%) | ~1.6 min | M |
| D5 | tailored.yaml authoring (Steps 3–5) | baseline (in ctx) | `cp <baseline> source/tailored.yaml` | — | `source/tailored.yaml` | 20k (12%) | ~1.4 min | L-M |
| D6 | **Discretionary source reads** | **`reference.md` 34.5 KB + `check.py` source 36.8 KB (≈70 KB) [± tracker SKILL 19.7 KB]** | — | — | — | **20k (12%)** | ~0.6 min | H (measured) |
| D7 | Pre-render layout budget (5.5) | estimate verdict line | `estimate_layout.py <folder>` (± simulate trims) | — | — | 5k (3%) | ~0.4 min | M |
| D8 | Render + check cycles (~2) | compact `render.py`/`check.py` stdout | `render.py <folder>` → DOCX + PDF (LibreOffice) + cover DOCX/PDF + auto `check.py`; ~2 cycles | — | `source/<stem>.docx`, `<stem>.pdf`, cover DOCX/PDF | 18k (11%) | **~2.8 min** | M |
| D9 | Cover letter + `.txt` bundling | JD/company facts (in ctx) | (bundle authored, then rendered in D8) | — | `<APPLICATION_STEM>_<title>.txt`, cover PDF | 15k (9%) | ~1.2 min | M |
| D10 | Step-7 skill queue | 3 profile skill lists (in card) | (in-context extract + dedup + 3-list diff) | — | (queued questions; profile edit only after answers) | 8k (5%) | ~0.5 min | M |
| D11 | Metadata / notes / finish | `--check-metadata` output | `status.py --enrich-metadata`, `--check-metadata`, notes.md | — | `meta.yaml` fills, `notes.md` | 8k (5%) | ~0.6 min | L-M |
|   | *residual reasoning/carryover* | | | | | ~20k (12%) | | |

**Dominant draft costs:** boot (D1, 12%), tailored.yaml authoring (D5, 12%), the **discretionary
70 KB source read (D6, 12%)**, and render cycles (D8, 11% tokens but the single largest wall-clock
block at ~2.8 min because LibreOffice PDF conversion is slow and runs twice for resume + cover).

---

## D. Fine-grained benchmark implications

For each stage, the pinned fixture that makes it independently benchmarkable and the observable
stage boundary (file written / script exit). This lets a lever be measured on the one stage it
touches instead of a whole noisy leg. Fixtures live in the private overlay under
`private/benchmark/fixtures/` (see `protocol.md`).

**Search leg**

| Stage | Pinned fixture that isolates it | Observable boundary |
|---|---|---|
| S1 boot | none needed (deterministic reads) | first tool call after last instruction Read |
| S2 profile/config | a frozen `profiles/bench.yaml` + pinned `JOBHUNT_CONFIG` | config accessor return |
| S3 fetch | **a frozen pre-filter snapshot** in `tmp/search_cache/<profile>-stage1-<ts>.json` format (already the cache format) — run with `--refilter` so no network | snapshot loaded (stderr "Refilter: loaded N …") |
| S4 filter/rank | same frozen snapshot; assert byte-identical ranking (refilter-equivalence test already exists) | discoveries file mtime / `--json-out` write |
| S5 dup/blacklist | a frozen applications tree + `blacklist.yaml` + logs under an isolated `JOBHUNT_CONFIG` | skip-count line in run summary |
| S6 JD verification | **a frozen `tmp/web_artifacts/JD-*.md` set** (mix of clean + JS-shell pages) so `fetch_jd` reads local fixtures, no network | `fetch_jd` stdout `path (N bytes)` per candidate |
| S7 location/visa | frozen JD fixtures with known workplace/visa strings + expected verdicts | `status.py --check-locations` exit + `match`/`other_us` line |
| S8 handoff | **a frozen search-JSON row** + empty target folder | `handoff.py` exit 0 + folder/`meta.yaml` written, validation status line |
| S9 metadata/present | a frozen handoff folder | `--check-metadata` exit 0 |

**Draft leg**

| Stage | Pinned fixture that isolates it | Observable boundary |
|---|---|---|
| D1 boot | none (deterministic) | first non-instruction tool call |
| D2 card/profile | **a frozen `tailoring-card.md` + baseline** (hash-pinned) under isolated config | card Read complete; `build_tailoring_card.py --check` exit |
| D3 JD analysis | **a frozen `source/JD-*.md`** | analysis presented (no artifact — bound by the next write) |
| D4 company research | a frozen local HTML fixture set + a `--no-web` / offline research flag (does not exist yet) | research section drafted |
| D5 tailored.yaml | frozen baseline | `source/tailored.yaml` written |
| D6 discretionary reads | n/a — measured directly by self-audit `wc -c` of files opened | (audit line) |
| D7 layout budget | **a frozen `tailored.yaml`** | `estimate_layout.py` verdict line (deterministic pt) |
| D8 render+check | **a frozen `tailored.yaml` (render-only timing)** — the cleanest isolate; measures pure render+PDF+check latency and cycle count | `render.py` DOCX/PDF paths + `check.py` `✓`/`FAIL` line + exit code |
| D9 cover/.txt | a frozen JD + company facts | `<APPLICATION_STEM>_<title>.txt` written; cover PDF path |
| D10 Step-7 | a frozen JD with known uncategorized skills + a frozen 3-list profile | the batched question set emitted |
| D11 metadata/notes | a frozen handoff folder | `--check-metadata` exit 0; `notes.md` written |

The two highest-value isolates are **(D8) a frozen `tailored.yaml` for render-only cycle/latency
timing** and **(S6) a frozen `tmp/web_artifacts/JD-*.md` set for offline verification timing** —
both remove the dominant network/LibreOffice noise so a lever's effect resolves at n=1–2.
