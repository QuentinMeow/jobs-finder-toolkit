# Execution plan

The implementation spec for [the workspace layout](README.md). Written for an agent that has
read `AGENTS.md` and nothing else about this design. Every line/​path reference below was
verified against the tree on 2026-07-28; re-verify before editing, since line numbers drift.

Target layout: [README.md](README.md). Gate spec: [review-gate.md](review-gate.md).
Topology decision: [`memory/decisions/workspace-layout-public-root-plus-review-gate.md`](../../memory/decisions/workspace-layout-public-root-plus-review-gate.md).

## How to work this plan

1. **One phase per PR pair.** A phase that touches both repos lands as two PRs that merge
   together; neither half merges alone.
2. **The PR that moves a path updates every literal naming it.** Do not defer path fixes to a
   later phase — that is what made an earlier version of this plan unexecutable.
3. **Every `git mv` is its own commit**, separate from content edits, so `git log --follow`
   survives.
4. **STOP on an unmet precondition.** Each phase lists blocking preconditions. If one is unmet
   or a decision it depends on is unanswered, do **not** proceed on a guess: move the task to
   `tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
   `templates/queue/decision.md` with options and a recommendation, and stop. Partial credit
   is worse than no credit here, because several gates in this repo fail *open*.
5. **Never delete owner data.** `AGENTS.md` guardrail: application folders, interview prep,
   company dossiers, and store payloads are removed by the user only. Migration moves things;
   it never removes them. If a move would orphan something, file it, don't drop it.
6. **A handover is not a work record.** Anything unresolved at the end of a session gets its
   own queue item or task carrying full context.

Gate command after every phase:

```bash
.venv/bin/python automation/reconcile/reconcile.py --check \
  && .venv/bin/python automation/publish/check_public.py \
  && .venv/bin/python automation/maintenance/gardener/verify_links.py \
  && .venv/bin/python automation/vendoring/sync_vendored.py --check
```

---

## Phase 0 — make the gates fail closed

**Why first:** four checks report success while inspecting nothing. Until they are fixed, no
later phase can prove it did not break something. This phase is independently valuable and
should ship even if the rest of the plan is abandoned.

**Blocking preconditions:** none. Start here.

### 0.1 — The leak guard passes with zero tokens

Reproduced: a tracked file containing the owner's real name, in a tree where config discovery
finds nothing, yields `active tokens: 0` … `OK: no public-repo leaks detected. Safe to
publish.` and exit 0.

- `automation/publish/check_public.py:312` `_identity_tokens()` returns early at line 325–326
  (`if active == example: return toks`) — so the example config contributes no tokens.
- `automation/publish/check_public.py:93` `LEAK_TOKENS_FILES` points at
  `private/leak_tokens.txt` (11 non-comment lines).
- `personal_tokens()` (line 366) unions them.

**Fix:** track the identity-derived set separately from the union. Exit non-zero when the
**identity** set is empty, with a message naming the missing config, unless `--allow-unarmed`
is passed. Gating on the union does **not** work: `leak_tokens.txt` alone keeps it non-empty
while the name, email, and handles are absent.

Also update `automation/hooks/pre-push` (the arm-detection block near line 126) so the unarmed
state is a hard stop for a push to the public remote, not a warning it proceeds past.

**Test:** a case in `automation/publish/tests/` that runs the guard against a fixture tree with
no config and asserts a non-zero exit; and one asserting `--allow-unarmed` still passes.

### 0.2 — The leak guard never runs at commit time

`automation/hooks/pre-commit` runs vendoring drift, mail-safety, `compileall`, the instruction
budget, and the reconciler. No leak check.

**Fix:** add `check_public.py` over the **staged index** (not the worktree), and hard-fail on
any staged path under `private/`. One line covers the silent case:
`git diff --cached --name-only | grep -q '^private/' && exit 1` — verified that
`git add -f private/` (with the trailing slash) stages 30 private files with exit 0 and no
output, while the slash-less form warns.

### 0.3 — `_find_config_path()` falls back silently

`automation/shared/config.py:73` `CONFIG_FILENAME = "config.yaml"`; discovery walks up from
`Path.cwd()` then from `_HERE`, and falls through to `EXAMPLE_CONFIG`.

**Fix:** stop the upward walk at the first `.git` directory, and **raise** rather than falling
back when no real config is found and `JOBHUNT_CONFIG` is unset. Keep the example fallback
reachable only via an explicit env var — CI already sets `JOBHUNT_CONFIG` at
`.github/workflows/ci.yml` (3 call sites), so CI is unaffected.

Re-vendor after this edit: `automation/vendoring/sync_vendored.py` mirrors
`automation/shared/**` byte-identically into four skills. Every `config.py` change is a 5-file
change.

### 0.4 — Five lists disagree about which skills are public

| Source | Says | Wrong how |
|---|---|---|
| `skills/*/SKILL.md` frontmatter `visibility:` (the declared SSOT) | 10 public | — |
| `automation/publish/export_public.py:44` `PUBLIC_SKILLS` | 9 | missing `search-recall-audit` |
| `.claude-plugin/marketplace.json` | 9 | missing `search-recall-audit` |
| tracked `.claude/skills/*` | 10 | — (re-verified 2026-07-29; an earlier draft of this table said 9, missing `interview-calendar` — that was already fixed in the tree) |
| tracked `.cursor/skills/*` | 10 | — (same correction) |

**Live consequence: `search-recall-audit` has never shipped in any export and is not
installable.**

**Fix:** derive `PUBLIC_SKILLS` from frontmatter at runtime (`check_public.py:427`
`parse_frontmatter_visibility` already exists). Regenerate `marketplace.json` and both runtime
symlink trees from the same source. Add a reconciler check that all four agree.

### 0.5 — The exporter walks the filesystem and skips silently

`automation/publish/export_public.py:165-169` — `_copy_tree` returns on a missing directory
with no warning, and line 170 uses `os.walk`, so **untracked** files are exported.

**Fix:** enumerate via `git ls-files`; warn on a missing allowlisted directory and fail under
`--strict`.

### 0.6 — The exported repo's CI is already red

`.github/workflows/ci.yml` runs `automation/store/validate_store.py`, but `automation/store/`
is not in `ALLOWLIST_DIRS` (line 67). `automation/bootstrap_overlay.py`, `CLAUDE.md`, and
`CONTRIBUTING.md` are likewise unexported.

**Fix:** reconcile `ALLOWLIST_DIRS` × `ci.yml` × `marketplace.json` × frontmatter in one pass.
Prove it with an export dry-run whose tree passes its own CI script list.

### 0.7 — `check_public.py`'s structural checks are hardcoded, and its tests hide that

Constants: `:93` `LEAK_TOKENS_FILES`, `:102` `PERSONAL_OVERLAY_PREFIXES = ("private/",)`,
`:110-111` `REFERENCES_PRIVATE_DIRNAME` / `_REFERENCES_PRIVATE_RE`, `:116` `EXAMPLES_PREFIX`,
`:122` `_DENY_TREES` (5 regexes). `automation/publish/tests/test_leak_guard.py` builds
synthetic fixtures from the same literals, so a rename leaves the tests green and the detector
dead.

**Fix:** make `_DENY_TREES` an **append-only union** of historical and current private root
names — never remove `interviews/` when the name changes — and add tests that scan the real
tracked tree rather than synthetic fixtures.

### 0.8 — `registry.py` treats a missing blacklist as "no blacklist"

`skills/job-search/scripts/registry.py` builds the overlay blacklist path from two bases and
falls through with no warning when neither exists. The live file is `companies: []`, so a
broken accessor passes every test.

**Fix:** add `config.blacklist_path()`; print a one-line notice when an overlay is mounted and
the file is absent. **The green gate must plant a real blacklist row** and assert the
preflight honours it — running the existing tests proves nothing.

### 0.9 — `verify_links.py` checks 23 files

`automation/maintenance/gardener/verify_links.py:100-105` `_instruction_files()` = `AGENTS.md`
plus `skills/*/{SKILL,LESSONS,reference,AGENTS}.md`. So ~155 tracked docs are never opened as
sources. `STRICT_ROOT_PREFIXES` (line 39) also lists `hooks/` and `docs/`, neither of which
exists at the public root today.

**Fix:** widen `_instruction_files()` to every tracked `.md` **first**, fix the findings that
appear, *then* widen `STRICT_ROOT_PREFIXES` to include `handbook/ design/ roadmap/ evals/
templates/ memory/ tasks/ message-queue/ history/`. Make `check_symlinks()` fail when it finds
zero link roots instead of passing.

### 0.10 — The private repo has no hooks

`private/.git/hooks/` holds only `.sample` files.

**Fix:** install `pre-commit` (private-scope reconciler + a staged-set guard rejecting
`store/*/{raw,derived,state}` and any staged set above a file/byte threshold) and `pre-push`
(assert the remote is the private one). Wire them through `automation/bootstrap_overlay.py`.

### 0.11 — Do NOT close the reconciler's missing-root no-op

`automation/reconcile/reconcile.py` guards each check with `if not <root>.is_dir(): return`
(lines 89, 111, 146, 194, 211, 224). This is **documented behaviour**, not a defect: the module
docstring says every check no-ops if its folder is absent so any subset of the process folders
can be adopted or deleted. `memory/ tasks/ message-queue/ roadmap/ history/` are not in
`ALLOWLIST_DIRS`, so closing it would turn the **published** repo's CI red.

**Fix:** add a `--require-roots` flag, used only in a maintainer checkout, that asserts the
expected roots exist. Separately fix `file_retries()` (line ~254), which
`mkdir(parents=True, exist_ok=True)`s `message-queue/needs-agent/retries` unconditionally even
with zero findings.

### 0.12 — Config accessors every later phase needs

Add to `automation/shared/config.py`, then re-vendor:

`candidate_dir()`, `tailoring_card_path()`, `applications_log_path()`,
`company_search_log_path()`, `blacklist_path()`, `story_bank_path()`, `calendar_path()`
(promote from derived to a first-class key), `search_profiles_dir()`,
`skill_references_dir()`, `companies_root()`.

Each replaces a literal that currently fails silently. The three that bite hardest:

- `applications_root() / "0_profile" / …` is a literal in **15 files**, including
  `skills/application-tracker/scripts/status.py:152`, four vendored `config.py` copies, and
  every gardener routine.
- `skills/resume-writer/scripts/build_tailoring_card.py` derives the story bank as
  `applications_root().parent / "interviews/behavioral/story-bank"` and embeds a sha256 of
  that directory, mirrored in 4 files including 2 benchmark fixtures. Move both halves without
  the accessor and you get a card with **no stories and a still-valid hash**.
- `registry.py`'s blacklist path (0.8).

**Green gate for phase 0**

- Plant a file containing a personal token → the guard **fails**.
- Run the guard with no config → it **fails** (and passes with `--allow-unarmed`).
- Plant a blacklist row → the job-search preflight honours it.
- Delete a process root → `--require-roots` fails while plain `--check` still passes.
- `sync_vendored.py --check` clean; export dry-run ships `automation/store/` and 10 skills.

---

## Phase 1 — orphans

**Blocking preconditions:** phase 0 merged.

- `private/todo/tasks/yoe-adjacent-context-cross-contamination.md` → refile as
  `private/tasks/0_backlog/<YYYY-MM-DD>-yoe-adjacent-context-cross-contamination/task.md`
  using `templates/task/task.md`; then remove the empty `todo/` tree. (Retired by the
  2026-07-22 process-folders decision.)
- `private/email-assistant/reviews/2026-07-20-recent-job-email-review.md` →
  `private/message-queue/needs-human/reviews/<kebab-slug>.md`, reformatted to
  `templates/queue/review.md`. Remove the now-empty `email-assistant/` tree.
- Sweep `tmp/` (102 untracked files across 22 purpose folders). **Do not delete** — this is
  scratch, but confirm with the owner before removing anything that looks like a captured
  artifact, per the never-delete guardrail.

**Green gate:** reconciler + tests.

---

## Phase 2 — public-side cleanup

**Blocking preconditions:** phase 0 merged. **Q4 answered** (docs consolidation confirmed —
answered: yes, with a superseding ADR).

- `automation/maintenance/gardener/` → `automation/gardener/`
- `automation/maintenance/search_recall_audit/` → `automation/search-recall-audit/`
- `automation/maintenance/import_company_levels.py` → `automation/company-levels/`
- **Fix 8 `parents[N]` depth constants in the same commit** — they resolve `REPO_ROOT` by
  counting levels and will point at the *parent of the repo* after the move:
  `gardener/_common.py:24`, `gardener/tests/test_store_report.py:22,29`,
  `gardener/tests/test_skill_drift.py:19`, `search_recall_audit/audit.py:43`,
  `search_recall_audit/field_fidelity.py:45`, `search_recall_audit/store_refilter.py:14`,
  `import_company_levels.py:34`. Prefer replacing the arithmetic with an upward walk for a
  `.git` marker.
- `handbook/` → `docs/handbook/`; `design/` → `docs/designs/`; `roadmap/` → `docs/roadmap/`.
  Re-create the `CLAUDE.md → AGENTS.md` sibling shim under `docs/designs/`.
- `evals/` absorbs measurement: `ab-protocol.md` and `design/stage-benchmarks/{protocol,stage-map}.md`
  → `evals/protocols/`; `evals/<skill>/canaries.yaml` → `evals/canaries/<skill>.yaml` (8
  folders holding one file each; one is empty). The *rationale* docs stay in `docs/designs/`.
- `tmp/` → `local/`, updating `.gitignore` and `handbook/file-organization.md`'s scratch rule.
- **Same PR:** `.github/workflows/ci.yml` (12 pinned paths),
  `.github/pull_request_template.md` (pins the gardener path), `ALLOWLIST_DIRS`,
  `marketplace.json`, and every doc reference.
- Write the superseding ADR for the `docs/` reversal into `memory/decisions/` — the prior
  decision is recorded in `handbook/file-organization.md` ("the former generic `docs/` was
  dissolved into `handbook/` + `design/`").

**Green gate:** full gate command + export dry-run + instruction budget
(`automation/metrics/instruction_budget.py --strict`).

---

## Phase 3 — the review gate

**Blocking preconditions:** phase 0 merged. **Q1 and Q2 answered** — answered: watch every
tracked public file except the ledger; one row may cover a commit range; an agent may sign its
own review, with a human row required only when the advisory detector fires.

Build per [review-gate.md](review-gate.md):

- `automation/publish/review_gate.py`
- `automation/publish/review_ledger.yaml` — seeded with the current HEAD; the gate never
  demands a retroactive review of history
- `automation/publish/tests/test_review_gate.py`
- Wire into `automation/hooks/pre-commit` and `.github/workflows/ci.yml`

Verified primitives (re-check before coding):

```bash
git log --oneline <last-ack>..HEAD
git diff --name-only <last-ack>..HEAD -- . ':!automation/publish/review_ledger.yaml'
git diff <last-ack>..HEAD -- . ':!automation/publish/review_ledger.yaml' | shasum -a 256
```

The ledger exclusion is load-bearing: without it, acknowledging a change is itself a change
and the gate never converges.

The advisory detector is **hints only**. Measured: the naive form (flag any public file naming
a company in the private tree) matches **51 of 177** private company tokens across the current
public tree — `canonical` 114 files, `writer` 103, `render` 85, `lambda` 59, plus `customer`,
`iterable`, Google, Microsoft, Amazon, Anthropic. Narrow it to: diff-only, subtract the
pre-change baseline, match display names from `companies/_index.yaml`, skip `examples/` and
`skills/job-search/companies.yaml`.

**Green gate:** a public commit fails the gate; a valid row passes it; a row with a wrong
digest still fails; the gate is silent when nothing changed.

---

## Phase 4 — layer 1: no private path wears a public name

**Blocking preconditions:** phases 0 and 3 merged.

Delete all eight inbound symlinks created by `automation/bootstrap_overlay.py:101`
`_overlay_links()`:

| Link (public tree) | Replacement |
|---|---|
| `skills/job-search/profiles/<personal-name>.yaml` ×4 | `config.search_profiles_dir()` → `private/job-search-profiles/` (→ `private/market/searches/` after phase 5). `search_jobs.resolve_profile()` already returns an absolute path first and documents the no-symlink case; `validate_filter_variants.py` resolves `HERE.parent/"profiles"` and needs the same accessor |
| `skills/<skill>/references_private/` ×2 | `config.skill_references_dir()` → `private/skills/references_private/<skill>/` |
| `skills/coding-interview{,-cleanup}/` ×2 | `.claude/skills/<name>` and `.cursor/skills/<name>` pointing directly at `private/skills/<name>` (git-ignored entries) |

Then remove the corresponding `.gitignore` rules (the four `skills/job-search/profiles/*.yaml`
negations, the two `references_private` pairs, the two `skills/coding-interview*` rules) and
strip `_overlay_links()` down to nothing but hook installation.

**Why this matters most:** those four profile symlinks put a personal name *in a filename in
the public tree*, protected only by a gitignore glob with two negations. After this phase the
rule has no exceptions: **if a path does not start with `private/`, what you write there is
published.**

**Green gate:** `git ls-files | grep -i <each personal token>` returns nothing; the runtime
lists 12 skills; a fresh public clone with no overlay still runs the job-search skill using the
tracked example profile.

---

## Phase 5 — the lifetime taxonomy inside `private/`

**Blocking preconditions:** phases 0 and 4 merged. **Q5 and Q6 answered** — answered: rendered
artifacts stay in the application folder and the *user* may delete a rejected application (an
agent never does); handovers are local-only.

Target tree: [README.md](README.md#the-private-overlay). Moves:

| From | To | Note |
|---|---|---|
| `applications/0_profile/{profile,baseline,company-levels→market,tailoring-card}` | `me/` | 15 files hold the `0_profile` literal — fix with the phase-0 accessors |
| `applications/0_profile/resumes/` | `me/resume/` | the third resume home |
| `inputs/master-resume/` | `me/resume/` | |
| `templates/resume/reference.docx` | `me/resume/reference.docx` | |
| `applications/0_profile/{applications-log,company-search-log}.yaml` | `market/logs/` | |
| `applications/0_profile/company-levels.yaml` | `market/logs/` | **keep whole** — 27 YAML anchors cannot shard per company |
| `applications/0_profile/calendar.md` | `me/interviews/calendar.md` | promote `calendar_path()` to a first-class config key |
| `applications/1_discoveries/` | `market/scans/{current,archive}/` | |
| `job-search/{blacklist,manual-check-companies}.yaml`, `company-universe/` | `market/` | |
| `job-search-profiles/` | `market/searches/` | |
| `interviews/behavioral/story-bank/` | `me/interviews/stories/` | |
| `interviews/behavioral/question-bank/{README,_general_*,sources,tests}` | `me/interviews/questions/` | |
| `interviews/behavioral/question-bank/{amazon,runpod}-*.md` | `companies/<key>/derived/behavioral.md` | **build outputs** — `skills/behavioral-interview-prep/scripts/answer_bank.py` must emit cross-tree targets; `test_answer_sources.py` hardcodes `parents[5]` |
| `interviews/common-message-replies/` | `me/interviews/replies/` | |
| `interviews/company-specific/<c>/company-info/` | `companies/<key>/research/` | 265 files, mechanical |
| `interviews/company-specific/<c>/coding/` | `companies/<key>/coding/` | 151 files. Karat is a company — `companies/karat/` |
| `interviews/company-specific/TODO/` | keep as-is | an **untracked** screenshot inbox two private skills poll; moving it orphans them |
| `data/` | `store/` | ships **in the same commit** as a sed of all 9 ignore patterns |
| `benchmark/`, `config.benchmark.yaml`, `evals/` | `evals/{fixtures,runs,canaries}/` | |
| `docs/harness-engineering…` | `docs/` | update `gardener/_common.py`'s `DESIGN_DOC` literal |
| `cursor-rules/private-skills.mdc` | `skills/` | |
| `history/` (both repos) | `private/local/history/` | never committed; re-point the reconciler's handover check and mark it local-only |

Then re-point every `paths.*` in `config.yaml`.

**~47 files are genuine judgment calls, not mechanical moves** — flat `coding/*.py` files
needing a problem folder and a company-vs-`me/interviews/practice/` call (a file whose header
says "LeetCode 146" is generic; one saying "Airbnb-style" is generic too),
`whatnot/product-sense/` (a round type the schema does not model),
`amazon/coding/oa-references/*.pdf` (cross-problem aggregates), and
`altara/outreach-reply-draft.md`. Route each through the owner rather than guessing.

**Also:** ~300 relative links inside `interviews/` that no checker covers
(`verify_links.py`'s `SKIP_PREFIXES` skips `interviews/` and `private/interviews/`). Fix them
in the same PR and remove those skip entries.

**Green gate:** `git -C private check-ignore` returns IGNORED for a fixed canary list covering
all 9 store patterns; every gardener routine runs; `status.py` reports the same pipeline as
before; level enrichment exercised; the tailoring card rebuilds **with its stories**.

---

## Phase 6 — the skip-log becomes authoritative

**Blocking preconditions:** phase 5 merged.

`skills/application-tracker/scripts/status.py:1954` `sync_log()` does
`APPLICATIONS_LOG.write_text(...)` — a wholesale regeneration from a scan of the application
folders. So deleting a rejected application and re-syncing drops its rows and job-search
re-surfaces the posting as fresh. This is the reason phase 5's "applications are disposable"
is unsafe on its own.

- New `market/logs/applications.jsonl` — append-only, one line per (posting, status-event),
  **keyed by URL**. Not per-company markdown: `search_jobs.already_considered()` matches
  normalized URL first and falls back to `(company, role)` through `registry.match_keys()`, so
  it is deliberately key-independent; sharding by company key would turn every alias split
  into a re-drafted application, and 213 file opens per search measured a **+25% token
  regression** on the draft leg.
- Demote `--sync-log` to a union-only upsert that can add rows but never truncate.
- One-time backfill from the 242 application folders plus the existing log.
- Two consumers read the old file and must be updated together: `search_jobs.load_considered`
  (expands through the registry) and `handoff._posting_keys` (raw `_norm()`).
- `search_jobs.profile_dir()` probes `config.profile_md_path().parent`, then
  `applications_root()/0_profile`, and **returns the first candidate when none holds a log** —
  after phase 5 that silently disables both skips. Fix it to use the accessors.

**Green gate:** delete a rejected application (as the user would), re-run search, confirm the
posting does **not** resurface.

---

## Phase 7 — the company key

**Blocking preconditions:** phase 5 merged, and the key-assignment approach decided (filed
non-blocking as its own task; default is one proposal PR).

242 application folders carry **213 distinct free-text company strings**; `registry.canonical()`
resolves only 119 — 44% unresolvable, including Google, Microsoft, Adobe, Netflix, Uber,
Salesforce, Oracle, Snap, T-Mobile, and *both* spellings of Canonical. Live splits:
`Canonical`/`Canonical Ltd.`, `Cursor`/`Cursor (Anysphere)`, `Arize`/`Arize AI`,
`Palantir`/`Palantir Technologies`, `Temporal`/`Temporal Technologies`. Two folders both
claiming `Komodo Health` carry different slug prefixes.

- `companies/_index.yaml`: `key → {display, aliases[], parent, kind}`. `kind` distinguishes an
  employer from an interview-running company like Karat; `parent` handles subsidiaries and JVs
  (`aws→amazon`, `alibaba-cloud→alibaba`, `warpstream→confluent`, `tiktok-usds→tiktok`).
- `meta.yaml` gains `company_key` alongside the human `company:` string — 242 edits.
- Retire the other three alias registries (`companies.yaml` `aliases:`,
  `company-search-log.yaml` per-row `aliases:`, `company-levels.yaml` per-company `aliases:`)
  by generating them from `_index.yaml` or deleting them.
- Reconciler check: every `company_key` resolves; no two keys share an alias.
- `skills/email-assistant` emits `durable: true|false` per `timeline.md` entry, and a `promote`
  command moves flagged entries into `companies/<key>/`. Without this the durable/disposable
  split degrades every time the assistant runs.

---

## Phase 8 — instruction surface

**Blocking preconditions:** phases 2, 4, 5 merged.

- `AGENTS.md`: the private-tree map, routing into `private/`, the new guardrails.
- 8 of 12 `SKILL.md` files name a moved path — heaviest are `resume-writer` (17 hits),
  `application-tracker` (17), `ask-me-anything` (15), `behavioral-interview-prep` (11),
  `company-research` (10), `gardener` (9), `job-search` (7), `search-recall-audit` (5).
- **`skills/company-research/SKILL.md` is at 595 lines against a hard 600-line pre-commit
  budget.** Land a slimming PR *before* this phase or it cannot merge.
- 5 handbook docs: `private-overlay.md` (44 mentions of `private/`),
  `public-private-split.md` (8), `repo-map.md` (4), `architecture.md` (4),
  `file-organization.md`.
- `examples/` reshaped to mirror the private tree (`me/`, `companies/`, `applications/`,
  `store/`), fixing the two violations it carries today: `examples/data/` is a generic bucket
  and `examples/templates/` collides with the root `templates/`.
- This is a "large" edit under the risk-based eval gate — **canaries run for every touched
  skill**, recorded in `evals/results/`.

---

## Verified facts and hazards

Re-verify anything you are about to depend on; these were measured 2026-07-28.

| Fact | Value |
|---|---|
| Public tracked files | 649 |
| Private tracked files | 3,138 (applications 2,401 · interviews 518 · benchmark 112) |
| Private files that actually move | ~782 — `applications/` keeps its path |
| `notes.md` → `timeline.md` | 133 renames |
| Literal `private/` in public files | 241 lines across 84 files |
| `0_profile` literal | 15 files |
| `parents[N]` under `automation/maintenance/` | 8 |
| `.venv/bin/python` in docs | 240 occurrences (unchanged by this plan) |
| `private/data/` | 432 MB, 12 tracked files, 9 ignore patterns |
| Unignoring risk | renaming `data/`→`store/` without the sed exposes **82,318 files**, incl. 36,465 raw email |

**Hard hazards:**

- `git clean -ffdx` in the public repo **deletes the entire private repo** (plain `-fdx` skips
  it: "Would skip repository private/"; `-ffdx`: "Would remove private/").
- `git add -f private/` — trailing slash — stages private files with exit 0 and no output.
- `git stash -a` inside `private/` swallows `local/` and the 432 MB store into a git object.
  Use `-u`.
- `automation/vendoring/sync_vendored.py` mirrors `automation/shared/**` into 4 skills
  byte-identically. Every `config.py` edit is a 5-file change plus a drift check.

**Pre-existing breakage to fix opportunistically (file, don't silently repair):** a job-search
profile references `interviews/common-message-**relies**/` (typo); a benchmark fixture symlink
points at an uncompressed target that exists only as `.gz`; and
`skills/job-search/profiles/<personal-name>-default-bench.yaml` cannot be bootstrapped because
its source lives under `private/benchmark/`, which `_overlay_links()` does not scan.

> Never spell a profile symlink's real filename in this tree — the guard fails on it, which is
> exactly the problem phase 4 removes.

## Human questions / additional tasks

<!-- Free space. -->
