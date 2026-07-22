# Execution plan — token-usage modes (staged hybrid)

**Status:** implemented; the final mode switch shipped in `446a954` after
the script-first and instruction-tiering stages. Companion to
[README.md](README.md) (measured baseline + the four approaches); this document turns
[Approach 4](approach-4-hybrid-recommended.md) into ordered work items with concrete
specs, PR boundaries, and gates. Wording is deliberately harness-agnostic: "delegate
to a subagent" means any coding agent the maintainer drives; nothing below depends on
a specific vendor or model.

## Ground rules (inherited from repo conventions, restated once)

- **PR discipline** per `CONTRIBUTING.md`: one focused change per PR, branch
  `<type>/<short-slug>`, all four checks green (publish tests, instruction budget
  `--strict`, leak guard clean, gardener `verify-links`), vendored copies in sync.
- **Eval gate**: any PR touching `.agents/skills/*/SKILL.md`, `LESSONS.md`, or
  `reference.md` runs that skill's `evals/<skill>/canaries.yaml` and records results
  per `evals/README.md`. Instruction edits are delta-only.
- **Vendoring** (AGENTS.md §Sharing Code Across Skills): a script used by one skill
  lives in that skill's `scripts/`; shared pure modules live canonically in
  `scripts/shared/` and are copied into consumers' `scripts/_vendor/` via
  `scripts/vendoring/sync_vendored.py` (drift-checked by pre-commit). Skills never
  import repo-root Python.
- **Budget headroom warning**: `AGENTS.md` is at ~490 of its 500-line budget.
  Stages 0–1 must not add lines to it — new script usage is documented in SKILL.md
  quickstart deltas only. Stage 2 is where AGENTS.md shrinks.
- **Privacy**: this public plan references overlay data only through config
  accessors (`config.profile_md_path()`, `<applications_root>/0_profile/…`), never
  literal overlay paths or real identities. Overlay-side work items are described
  generically and executed as commits in the maintainer's own overlay repo.
- **Measurement protocol** (README §How to re-measure): the benchmark scenario is
  "one search + two drafted applications, end-to-end" on the maintainer's real
  config, run by the maintainer's harness after each stage merges, on the same
  mid-tier model as the 2026-07-20 baseline (model-pinned for comparability).
  Per-subagent totals come from harness usage reporting; each run appends a row to
  the README projection table and a dated entry under `evals/results/` (from
  `TEMPLATE.md`). Projected numbers are expectations, not pass/fail bars: a result
  far outside its range (≥ ~25% worse than projected) pauses the next stage for
  analysis instead of proceeding.

## Stage 0 — Experiment follow-ups (land before Stage 1's benchmark)

Cheap fixes surfaced by the baseline experiment. S0.1 in particular removes ~1–2
render cycles from *every* future run, so it must land before the Stage 1
measurement or stage attribution is muddied. The README table gets no separate
Stage 0 row; the Stage 1 row's notes state that S0 landed with it.

### S0.1 — Baseline wording vs Never-list collision *(overlay commit, no public PR)*

The baseline resume's own wording contains a phrase that string-matches a
Never-listed skill name (a phrase-vs-tool false positive), in two places. Both
drafting agents in the baseline run burned ~2 render cycles each rediscovering it.

- **Change**: reword the two occurrences in the overlay baseline (and the matching
  profile phrasing if present) so the phrase no longer contains the blocked token.
- **Verify**: re-run the resume-writer validator (`check.py`) against a recent
  drafted application; the two false positives disappear and no new findings appear.

### S0.2 — Scraper dependency reconcile *(public PR: `fix/jobspy-dependency`)*

`search_jobs.py` enables its JobSpy stage by default (`--jobspy` on), but
`python-jobspy` is not in `requirements.txt`; when missing, stage-1 fetching
silently degrades (this cost 3 redundant full pipeline runs before diagnosis).

- **Change**: add `python-jobspy` to `requirements.txt` with a version bound,
  unless install-weight testing shows unacceptable transitive bulk — in which case
  document it as an extra in README/CONTRIBUTING instead. **Either way**,
  `search_jobs.py` must fail loud: when JobSpy is enabled but unimportable, print a
  prominent stderr banner naming the exact install command and stating which
  sources were skipped.
- **Tests**: unit test for the warning path (JobSpy absent → banner text present,
  run continues with remaining sources).

### S0.3 — LESSONS.md entries from the experiment *(public PR: `docs/job-search-lessons-remote-visa`, eval-gated)*

Two delta-only entries in `.agents/skills/job-search/LESSONS.md` (budget: 160
lines — confirm headroom before writing):

1. The market-scraper `remote` flag is unreliable (a whole run mistagged hybrid and
   on-site roles as remote): verify workplace type from the saved JD text before
   handing off or recording location facts.
2. The visa heuristic can false-positive on negated sponsorship phrases ("does not
   sponsor…" → `yes`): treat heuristic `yes` as a claim to verify against JD text,
   not a fact.

- **Gate**: job-search canaries green; results recorded per `evals/README.md`.

## Stage 1 — Script-first mechanics (four PRs, quality-risk-free)

Design source: [Approach 2](approach-2-script-first-handoff.md). Only deterministic
work moves from agent context into scripts; every judgment step stays with the
agent. PR-A and PR-B branch from `main` independently; PR-C stacks on PR-B; PR-D
branches from `main`. Merge order: A/B in any order → C → D (D is independent but
lands last so its SKILL.md delta can reference the handoff flow).

### PR-A `feature/search-snapshot-refilter` — fetch cache, `--refilter`, compact stdout

The baseline run paid for 7 full fetches (~12k postings from 100+ boards each) to
answer what were, after the first fetch, pure re-filter questions.

**Spec — snapshot cache:**

- After fetch + normalization, `search_jobs.py` always writes a snapshot of the
  normalized postings (pre-filter) to `--cache-dir` (default `tmp/search_cache/`,
  gitignored): `<profile>-stage<N>-<UTC timestamp>.json`, plus a
  `<profile>-stage<N>-latest` pointer. The snapshot records its fetch timestamp and
  the fetch-relevant parameters (profile, stage, sources actually reached).
- `--refilter [PATH|latest]` skips all fetching, loads the snapshot, and re-runs
  filter → score → rank with the current flags (`--max-age-days`, `--top-k`,
  `--visa-policy`, `--company-tags`, `--json-out`, …). Posting-age math uses the
  snapshot's fetch timestamp, never wall-clock now.
- **TTL**: `--refilter` refuses a snapshot older than **6 hours** unless
  `--allow-stale` is passed, and always prints the snapshot's age. Freshness is
  this toolkit's product; the cache is a within-session artifact, not a store.
- Flags that change what would have been *fetched* (`--stage`, `--aggregators`,
  `--no-companies`, …) are rejected under `--refilter` with a message saying a
  fresh fetch is required.

**Spec — compact stdout contract:**

- Default stdout becomes: a ~5-line run summary (sources reached, postings fetched,
  kept, snapshot path, discoveries/JSON paths) + the top-K compact table — rank,
  company, title, score, level, age, visa, URL — and nothing else. The full
  Markdown report continues to be written to the discoveries file exactly as today;
  `--json-out` behavior is unchanged. A new `--print-full` restores the old
  full-report stdout dump.
- SKILL.md documents one-liner field extraction from the JSON (so agents pull one
  field instead of dumping records).

**Tests**: snapshot round-trip; refilter equivalence (same snapshot, same flags ⇒
byte-identical ranking to the direct run that wrote it); TTL refusal + override;
fetch-affecting-flag rejection; compact renderer golden test.

**Instruction delta (eval-gated)**: job-search SKILL.md quickstart — when widening
windows or re-emitting JSON, use `--refilter`; read the compact table, not the file.

### PR-B `feature/jd-fetch-raw` — verbatim JD fetcher

Baseline behavior fetched each JD up to three times, once through an AI-summarizing
tool, and saved nothing verbatim.

**Spec**: `.agents/skills/job-search/scripts/fetch_jd.py <URL> --out <path>` —
downloads the posting page, extracts readable text (strip nav/script/boilerplate;
stdlib `html.parser`, no new heavy dependencies), saves it verbatim, and prints
only the saved path + byte count. Idempotent: if `--out` exists, it is kept
(`--force` overwrites). No AI summarization anywhere in the path.

**Tests**: local HTML fixtures only (no network in tests): extraction quality on a
representative ATS page fixture, idempotency, `--force`.

### PR-C `feature/handoff-scaffold` — the search → drafting bridge *(stacks on PR-B)*

Baseline drafting agents hand-transcribed ~10 structured fields into `meta.yaml`
and hand-built folders — token-expensive and where transcription errors happen.

**Spec**: `.agents/skills/job-search/scripts/handoff.py --json <search.json>
--select <rank | company/title>`:

1. Creates the application folder under the applications root per AGENTS.md
   §Application Folder Convention (the implementer reads that section; this plan
   does not restate it).
2. Fetches and saves `source/JD-<job title>.md` via `fetch_jd.py` (exactly one
   fetch, verbatim).
3. Writes `meta.yaml` (schema v3) carrying over every structured fact present in
   the search-JSON row — level, YOE, salary, URLs, dates, visa/remote flags —
   via the vendored metadata modules, preserving formatting conventions.
4. Validates before exit: the folder must pass metadata validation; on failure the
   script exits non-zero and says what's missing. Stdout: folder path + validation
   status only.

**Vendoring change**: `handoff.py` needs `job_metadata.py` (already vendored into
job-search) **and `metadata_editor.py` (today vendored into application-tracker
only)** — add `scripts/shared/metadata_editor.py → job-search/_vendor/` to
`sync_vendored.py` TARGETS and regenerate. `handoff.py` does *not* shell out to
another skill's scripts (self-containment); the tracker's `--enrich-metadata` /
`--check-metadata` remain the agent-invoked follow-ups and must pass on a fresh
handoff folder without edits.

**Tests**: end-to-end on the public example fixture — a synthetic search JSON row →
folder that passes metadata validation; missing-field diagnostics; no-overwrite of
an existing folder.

**Instruction deltas (eval-gated, both skills)**: job-search SKILL.md — end a
search by offering `handoff.py` for user-selected rows. resume-writer SKILL.md —
when the folder came from `handoff.py`, drafting starts at gap analysis; do not
re-verify or re-create what the scaffold already wrote.

### PR-D `feature/tailoring-card` — distilled candidate context

Baseline drafting agents each read ~17 KB profile+baseline plus a ~24 KB story
bank at full fidelity, regardless of need.

**Spec**: `.agents/skills/resume-writer/scripts/build_tailoring_card.py` compiles,
from the configured profile/baseline (`config.profile_md_path()`,
`config.baseline_path()`) and the story bank directory:

- identity/locked fields, target roles, key numbers;
- the three skills lists — **the Never list verbatim and complete** (a blocklist
  cannot be summarized; this is a hard rule with a test);
- a story-bank digest: per story, title + one-line summary + "read the full story
  when …" pointer;
- a generated-from header: source paths, their SHA-256s, generation timestamp.

Output: `<applications_root>/0_profile/tailoring-card.md`, target ≤ ~2k tokens
(≈8 KB; enforced by a size assertion with margin). The card is a derived artifact:
the gardener gains a staleness check (recorded hashes vs current file hashes →
flag, dry-run semantics like its other routines), and the build script itself
exits non-zero with a "stale sources" message if re-run against changed sources
without `--write`.

**Tests**: deterministic generation from the public example-candidate fixture
(`examples/profile/`); size ceiling; Never-list verbatim-inclusion test; staleness
detection.

**Instruction delta (eval-gated)**: resume-writer SKILL.md — drafting agents read
the card first; open the full profile/story bank only when the card's pointers or
the JD demand a deep dive. The full-fidelity files remain the source of truth for
any conflict.

### Stage 1 gate

1. All four PRs merged with checks + canaries green (job-search and resume-writer
   canaries run on the PRs that touch their instruction files).
2. Live benchmark run (protocol above). Expectation: ~245k total (−44%); the
   search agent's 7-fetch pathology and the drafting agents' transcription work
   should be visibly gone from the run logs. Row appended to the README table
   (noting Stage 0 landed with it); results recorded in `evals/results/`.
3. **Review pause**: maintainer reviews the measured row before Stage 2 starts —
   Stage 2 edits safety-critical instruction files and deserves a deliberate go.

## Stage 2 — Instruction tiering (eval-gated; starts only after Stage 1 review)

Design source: [Approach 1](approach-1-trim-instruction-stack.md). With Stage 1
merged, SKILL.md workflow sections genuinely shrink (procedures became script
calls), making the rewrite smaller and safer. Every PR here is eval-gated;
edits are delta-only restructures, never full-file rewrites, and consolidation
must not drop a domain edge case.

- **PR-E `docs/job-search-quickstart`**: restructure job-search SKILL.md — first
  ~50–60 lines become the self-sufficient standard path (exact commands incl. the
  new `--refilter`/`handoff.py` flow, hard gates, and explicit "read section X
  only when Y" triggers); body sections become on-demand reads.
- **PR-F `docs/resume-writer-quickstart`**: same treatment for resume-writer
  SKILL.md (tailoring-card-first context rule lives in the quickstart).
- **PR-G `docs/agents-core-annex`**: split AGENTS.md into a core contract
  (target ≤ ~150 lines: traceability, no-fabrication, leak guard, folder
  conventions pointer, subagent budget, vendoring pointer) + per-topic annexes
  under `docs/agents/`, each read only when its topic arises.
- **PR-H `chore/ratchet-instruction-budgets`**: lower `instruction_budget.py`
  budgets to measured-post-trim + ~10% headroom (e.g. AGENTS.md 500 → ~170;
  SKILL.md 600 → post-trim size; LESSONS.md stays 160) so the trim cannot
  silently regrow. Add budgets for the new annex files.

**Gate**: canaries green per edited skill; `instruction_budget.py --strict` passes
at the new numbers; live benchmark row (~185k expected, −58%); review pause.

## Stage 3 — The mode switch (thin composition; starts only after Stage 2 review)

Design source: [Approach 3](approach-3-two-modes.md). By now `token_saving` is
mostly composition of existing pieces. The quality floor — every validator and
hard gate — is mode-independent by construction.

- **PR-I `feature/generation-mode-config`**: `generation.mode: token_saving|full`
  in `config.example.yaml` (default `token_saving`), accessor in
  `scripts/shared/config.py` (+ vendor sync), `--mode` override on scripts whose
  behavior differs (initially: output verbosity only).
- **PR-J `docs/mode-semantics` (eval-gated, both skills)**: the Approach-3
  semantics table lands in each quickstart (token_saving column = the default
  path; `full` extras live in the body). Drafts record their generation mode (a
  notes line plus an optional `meta.yaml` field — optional so schema v3 needs no
  bump). token_saving's Step-7 skill categorization queues unknown JD skills to a
  pending file under `<applications_root>/0_profile/` for one later interactive
  session instead of in-run prompts.
- **PR-K `docs/mode-upgrade-path` (eval-gated)**: the documented upgrade path —
  `--mode full` re-run on an existing folder — plus the review-time prompt in the
  application-tracker flow ("this draft was produced in token_saving; re-run in
  full mode before submitting?").

**Gate**: canaries green **in both modes** for canaries whose behavior differs by
mode (mode-matrix only where behavior actually differs, to contain eval surface);
live benchmark in `token_saving` (~120k expected, −73%) plus one spot-check run in
`full` (~200k expected); README table completed.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Snapshot cache vs the freshness mission | 6-hour TTL, `--allow-stale` explicit, age printed on every refilter, age math anchored to fetch time |
| AGENTS.md budget (490/500) overflows before Stage 2 | Stages 0–1 add zero AGENTS.md lines; all new-script docs go in SKILL.md deltas |
| Instruction rewrite degrades safety-critical behavior | Eval gate per skill, delta-only edits, Stage 2 deferred behind a human review pause; budgets ratcheted only after canaries pass |
| Tailoring card goes stale or truncates the blocklist | Source-hash header + gardener staleness check + build-time stale exit; Never-list verbatim rule with a test |
| Cross-skill coupling via `handoff.py` | Vendored modules only; no cross-skill subprocess; tracker validation must pass on untouched handoff output |
| Mode split doubles eval surface | Mode-matrix only for canaries whose behavior differs; quality floor (validators) is mode-independent so most canaries stay single-run |
| Lazy loading is advisory — agents may over-read anyway | Quickstarts carry explicit read-triggers; canary efficiency metrics (total_tokens) flag regressions |
| Benchmark noise (live job boards vary day to day) | Same profile/flags/model pinned; per-agent audits identify *which* lever moved, not just the total |

## Delegation map

Each PR above is scoped to be executable by a single subagent with this plan
section as its spec, plus: the branch name, the repo conventions section, the
requirement to run the four CONTRIBUTING checks (and canaries when instruction
files are touched) before handing back, and a PR description per the template.
The orchestrating session reviews every diff, runs/records canaries, merges
base-first, and runs the stage-gate benchmarks. Stages 2 and 3 each begin only
after the maintainer reviews the previous stage's measured results.
