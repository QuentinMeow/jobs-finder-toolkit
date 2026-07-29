# Execution plan

The implementation spec for [the workspace layout](README.md). Written for an agent that has
read `AGENTS.md` and nothing else about this design.

**Status: phases 0, 3 and 4 are merged; phases 1, 2, 5, 6, 7 and 8 are not started.** The
merged three are recorded below as short records — what they changed and what the remaining
phases may now rely on — not as instructions. Every number in this document was re-measured on
2026-07-29 against `main` at commit `19d0829`; re-measure anything you are about to depend on,
because the tree moves under this plan faster than the plan does.

Target layout: [README.md](README.md). Gate spec: [review-gate.md](review-gate.md).
Topology decision: [`memory/decisions/workspace-layout-public-root-plus-review-gate.md`](../../memory/decisions/workspace-layout-public-root-plus-review-gate.md).

## How to work this plan

1. **One phase per PR pair.** A phase that touches both repos lands as two PRs that merge
   together; neither half merges alone.
2. **The PR that moves a path updates every literal naming it.** Do not defer path fixes to a
   later phase — that is what made an earlier version of this plan unexecutable.
3. **Every `git mv` is its own commit**, separate from content edits, so `git log --follow`
   survives.
4. **Every commit needs a review-ledger row, and the branch ends with a ledger-only commit.**
   This is new since phase 3 and it changes the shape of every PR below. The gate
   (`automation/publish/review_gate.py`, run from `automation/hooks/pre-commit` and CI) fails
   whenever any tracked file except the ledger changed since the last row in
   `automation/publish/review_ledger.yaml`. At pre-commit time HEAD is still the *previous*
   commit, so a row always acknowledges the commit before the one being made: you stage the row
   for HEAD alongside your next change and commit once. A branch therefore ends with a
   **ledger-only commit** — it changes no watched file, so it acknowledges the tip without
   creating new work, and that is how a branch lands green before pushing. When the gate fails
   it prints the exact row, already filled in; the row's `digest` is recomputed from the diff it
   claims, so it cannot be guessed, only pasted after reading. One row may cover a range of
   commits. An agent may sign its own review; `reviewed_by: human` is required only when the
   advisory company detector fires. A big mechanical phase (2 and 5 especially) will produce
   large ranges — read the diff, do not batch-acknowledge blind.
5. **STOP on an unmet precondition.** Each phase lists blocking preconditions. If one is unmet
   or a decision it depends on is unanswered, do **not** proceed on a guess: move the task to
   `tasks/2_blocked/`, file `message-queue/needs-human/decisions/<slug>.md` from
   `templates/queue/decision.md` with options and a recommendation, and stop. Partial credit
   is worse than no credit here, because several gates in this repo fail *open*.
6. **Never delete owner data.** `AGENTS.md` guardrail: application folders, interview prep,
   company dossiers, and store payloads are removed by the user only. Migration moves things;
   it never removes them. If a move would orphan something, file it, don't drop it.
7. **A handover is not a work record.** Anything unresolved at the end of a session gets its
   own queue item or task carrying full context.

Gate command after every phase (`verify_links.py` runs the vendoring drift check itself, so it
is not repeated):

```bash
.venv/bin/python automation/reconcile/reconcile.py --check --require-roots \
  && .venv/bin/python automation/publish/check_public.py \
  && .venv/bin/python automation/maintenance/gardener/verify_links.py \
  && .venv/bin/python automation/metrics/instruction_budget.py --strict \
  && .venv/bin/python automation/publish/review_gate.py --verify-all
```

---

## Merged: phase 0 — the gates fail closed

Merged as PRs #81–#84, commits `72d45e2`…`eb345e7`. Four checks used to report success while
inspecting nothing. They no longer do. What a later phase needs to know:

- **The leak guard is armed or it fails.** `automation/publish/check_public.py` tracks the
  identity-derived token set separately from the union with `private/leak_tokens.txt`, and
  exits non-zero when the identity set is empty unless `--allow-unarmed` is passed.
  `automation/hooks/pre-push` treats the unarmed state as a hard stop for the public remote.
- **It runs at commit time.** `automation/hooks/pre-commit` runs it over the **staged index**
  (`--staged --allow-unarmed`) and hard-fails on any staged path under `private/`.
- **Config discovery raises instead of falling back.** The upward walk stops at the first `.git`
  boundary; the example-persona fallback survives only for a fresh public clone with no overlay
  mounted (`JOBHUNT_REQUIRE_REAL_CONFIG=1` forces the raise everywhere). Recorded in
  [`message-queue/needs-human/decisions/config-discovery-example-fallback.md`](../../message-queue/needs-human/decisions/config-discovery-example-fallback.md).
- **`SKILL.md` frontmatter is the only source of skill visibility.**
  `automation/publish/sync_skill_manifests.py` derives the public set at runtime;
  `export_public.py`, `.claude-plugin/marketplace.json`, `.claude/skills/*` and `.cursor/skills/*`
  all follow it, and the reconciler's `skill-manifests` check fails when they disagree.
  `search-recall-audit` ships as a result.
- **The exporter enumerates through `git ls-files`**, warns on an allowlisted directory that
  resolves to nothing, and refuses under `--strict`. `ALLOWLIST_DIRS` now carries
  `automation/store`, and the root files `CLAUDE.md`, `CONTRIBUTING.md`, and
  `automation/bootstrap_overlay.py`, so the exported repo's own CI is green.
- **`check_public._DENY_TREES` is an append-only union.** It already carries the names phase 5
  introduces — `store/`, `me/`, `companies/`, `market/` — alongside the historical
  `applications/`, `interviews/`, `data/`, `job-search-profiles/`, `.agents/inputs/` and the two
  `skills/coding-interview*` trees. Two tests lock this: `test_deny_trees_are_append_only`
  fails if a name is removed, and `test_every_root_anchored_gitignore_product_rule_is_denied`
  fails if a root-anchored `/x/` rule is added to the **public** `.gitignore` without a matching
  deny entry.
- **`registry.py` reads `config.blacklist_path()`** and prints a notice when an overlay is
  mounted and the file is absent, instead of silently treating it as "no blacklist".
- **`verify_links.py` reads every tracked `.md`** — 264 files today, up from the 23 it used to
  open — and `STRICT_ROOT_PREFIXES` covers `handbook/ design/ roadmap/ evals/ templates/
  memory/ tasks/ message-queue/ history/`, each strict only in a tree that actually has that
  root. `check_symlinks()` fails when it finds zero link roots.
- **The reconciler gained `--require-roots`** (used by the maintainer pre-commit) while plain
  `--check` keeps its documented missing-root no-op, so the published repo's CI stays green.
  `file_retries()` no longer conjures `message-queue/needs-agent/retries` on a clean run.
- **The private overlay has hooks**: `automation/hooks/overlay-pre-commit` and
  `overlay-pre-push`, installed by `automation/bootstrap_overlay.py`. Whether a private-scope
  reconciler also runs is open in
  [`message-queue/needs-human/decisions/private-scope-reconciler.md`](../../message-queue/needs-human/decisions/private-scope-reconciler.md);
  the default is no, and the hook reports the skip.

### The eleven config accessors, and what they mean for the moves ahead

This is the part of phase 0 the remaining phases lean on hardest. `automation/shared/config.py`
now exposes `overlay_root()`, `candidate_dir()`, `tailoring_card_path()`,
`applications_log_path()`, `company_search_log_path()`, `blacklist_path()`, `story_bank_path()`,
`search_profiles_dir()`, `skill_references_dir(skill)`, `companies_root()` and `calendar_path()`,
plus `overlay_mounted()` — each mirrored byte-identically into the four vendored copies under
`skills/*/scripts/_vendor/config.py`.

**Eight of them read a `paths.*` config key** (`overlay_root`, `candidate_dir`, `calendar_md`,
`blacklist_yaml`, `story_bank_dir`, `search_profiles_dir`, `skill_references_root`,
`companies_root`), joining the seven keys that already existed (`profile_md`, `baseline_yaml`,
`reference_docx`, `company_levels_yaml`, `applications_root`, `discoveries_dir`, `data_root`).
Relocating any of those is a `config.yaml` edit, not a code edit.

**Three of them do not**: `tailoring_card_path()`, `applications_log_path()` and
`company_search_log_path()` are hard-derived as `candidate_dir() / <FILENAME>`
(`automation/shared/config.py:444-456`). They can only move together, and only by moving
`candidate_dir`. Phase 5 splits them apart, so phase 5 needs code — see
[phase 5](#phase-5--the-lifetime-taxonomy-inside-private).

The old fragile idioms are gone from the code: `status.py:152` is
`config.applications_log_path()`, and the `0_profile` string survives in executable code only as
the constant `CANDIDATE_DIRNAME` (five `config.py` copies), one `getattr` default at
`skills/job-search/scripts/search_jobs.py:92`, and four test fixtures. The other 31 tracked
files that contain the string carry it in prose.

## Merged: phase 3 — the public-change review gate

Merged as PR #85, commits `92abe36`…`97a7303`. Built to
[review-gate.md](review-gate.md): `automation/publish/review_gate.py`,
`automation/publish/review_ledger.yaml` seeded at the phase-0d commit `eb345e71` so no
retroactive review of history is demanded, `automation/publish/tests/test_review_gate.py`, and
wiring into `automation/hooks/pre-commit` plus `.github/workflows/ci.yml`
(`--verify-all` for full ledger integrity). The working rules it imposes on every later PR are
in [How to work this plan](#how-to-work-this-plan), rule 4.

Two things worth carrying forward. The **ledger exclusion is load-bearing**: the watched
pathspec and the digest both use `':!automation/publish/review_ledger.yaml'`, because without it
acknowledging a change is itself a change and the gate never converges. And the gate **found a
real leak on its first run** — commit `ef2d0a3` redacted the owner's application history out of
tracked planning docs. That is the standing hazard for phases 5 and 7, which are the two phases
whose subject matter *is* the owner's application list: describe shapes, never instances.

The advisory company detector is hints only. Measured before narrowing: the naive form (flag any
public file naming a company present in the private tree) matched 51 of 177 private company
tokens across the public tree, on words like `canonical`, `writer`, `render` and `lambda`. It is
narrowed to diff-only, minus the pre-change baseline, matching display names, skipping
`examples/` and `skills/job-search/companies.yaml`.

## Merged: phase 4 — no private path wears a public name

Merged as PR #86, commits `1b837b7`…`7809b4b`. All eight inbound symlinks that
`automation/bootstrap_overlay.py` used to create are deleted: four personal search-profile files
under `skills/job-search/profiles/`, two `skills/<skill>/references_private/` folders, and the
two `skills/coding-interview{,-cleanup}/` skill trees. `_overlay_links()` is gone; the private
skills are reached through git-ignored `.claude/skills/<name>` and `.cursor/skills/<name>` entries
pointing straight at `private/skills/<name>`, and the runtime lists 13 skills (11 public, 2
private). The matching `.gitignore` rules were removed in the same commit, leaving a comment
that records why.

**The rule this establishes, which every later phase depends on: if a path does not start with
`private/`, what you write there is published.** There are no exceptions left — no glob, no
negation, no symlink. `find skills -maxdepth 2 -type l` returns nothing.

---

## Phase 1 — orphans

**Blocking preconditions:** none — phase 0 is merged. Ready to start.

- `private/todo/tasks/yoe-adjacent-context-cross-contamination.md` → refile as
  `private/tasks/0_backlog/<YYYY-MM-DD>-yoe-adjacent-context-cross-contamination/task.md`
  using `templates/task/task.md`; then remove the empty `todo/` tree. (Retired by the
  2026-07-22 process-folders decision.)
- `private/email-assistant/reviews/2026-07-20-recent-job-email-review.md` →
  `private/message-queue/needs-human/reviews/<kebab-slug>.md`, reformatted to
  `templates/queue/review.md`. Remove the now-empty `email-assistant/` tree.
- Sweep `tmp/` (102 untracked files across 20 purpose folders). **Do not delete** — this is
  scratch, but confirm with the owner before removing anything that looks like a captured
  artifact, per the never-delete guardrail.

Both orphans live in the private repo, so this phase's public half is empty and the review gate
has nothing to acknowledge. Do not create a public commit just to have one.

**Green gate:** reconciler + tests.

---

## Phase 2 — public-side cleanup

**Blocking preconditions:** phase 0 merged (done). **Q4 answered** (docs consolidation
confirmed — answered: yes, with a superseding ADR).

### Split `automation/maintenance/`

`automation/` holds ten entries today: `bootstrap_overlay.py`, `hooks/`, `maintenance/`,
`metrics/`, `publish/`, `reconcile/`, `shared/`, `store/`, `vendoring/`, and an untracked
`__pycache__/`. Only `maintenance/` is a generic bucket, and it holds exactly three things:

- `automation/maintenance/gardener/` → `automation/gardener/`
- `automation/maintenance/search_recall_audit/` → `automation/search-recall-audit/`
- `automation/maintenance/import_company_levels.py` → `automation/company-levels/`

**Five of the nine `parents[N]` depth constants under `automation/maintenance/` break** — they
resolve `REPO_ROOT` by counting levels and would point at the parent of the repo. Fix them in
the same commit; prefer the upward `.git` walk that `automation/shared/config.py` adopted in
commit `5156598` (`_git_boundary()` / `_repo_root()`), for the reason recorded there: a fixed
parent count cannot survive a move or a re-host.

| Constant | Breaks? |
|---|---|
| `gardener/_common.py:24` `parents[3]` | **yes** — one level shallower after the move |
| `gardener/tests/test_store_report.py:29` `GARDENER_DIR.parents[2]` | **yes** |
| `search_recall_audit/audit.py:43` `parents[3]` | **yes** |
| `search_recall_audit/field_fidelity.py:45` `parents[3]` | **yes** |
| `search_recall_audit/store_refilter.py:14` `parents[3]` | **yes** |
| `gardener/tests/{test_skill_drift,test_store_report,test_verify_links}.py` `parents[1]` | no — relative to the tests dir, move-invariant |
| `import_company_levels.py:34` `parents[2]` | no — `automation/company-levels/` sits at the same depth as `automation/maintenance/`; leave it correct by accident and it will bite the next move, so convert it too |

### Consolidate `docs/`

`handbook/` → `docs/handbook/`; `design/` → `docs/designs/`; `roadmap/` → `docs/roadmap/`.
Re-create the `CLAUDE.md → AGENTS.md` sibling shim under `docs/designs/`. It is a **tracked
symlink** (git mode `120000`, one of only two outside the runtime `.claude/skills` and
`.cursor/skills` trees), and `automation/publish/export_public.py:238-241` deliberately
*follows* it so the export ships real content for checkouts without symlink support. So `git mv`
the link rather than deleting and re-authoring it: the exported tree looks the same either way,
which is exactly why a mistake here is invisible until Claude Code stops loading the folder's
contract.

This move now also relocates **this design family itself**. `design/workspace-restructure/`
becomes `docs/designs/workspace-restructure/`, and 23 tracked files name that path today —
including `automation/publish/review_gate.py`'s docstring, the header comment inside
`automation/publish/review_ledger.yaml`, `automation/publish/tests/test_review_gate.py`,
`automation/publish/check_public.py`'s `_DENY_TREES` comment, the ADR, `roadmap/current-state.md`,
and 13 task files across `tasks/0_backlog/` and `tasks/3_in-review/`. Every constant that has to
move with the three roots:

| Constant | File | Names |
|---|---|---|
| `STRICT_ROOT_PREFIXES` | `automation/maintenance/gardener/verify_links.py:54` | `handbook/`, `design/`, `roadmap/`, `evals/`, `templates/` |
| `PLAN_OR_RECORD_SOURCES` | `automation/maintenance/gardener/verify_links.py:87` | `design/`, `roadmap/desired-state.md`, `evals/results/` |
| `SKIP_PREFIXES` | `automation/maintenance/gardener/verify_links.py:66` | `tmp/`, `private/tmp/` |
| `_FALLBACK_SKIP_DIRS` | `automation/maintenance/gardener/verify_links.py:137` | `tmp` |
| `ALLOWLIST_DIRS` | `automation/publish/export_public.py:76` | `handbook`, `design`, `evals`, `templates` |
| `check_roadmap_fresh()` + `CHECK_ROOTS` | `automation/reconcile/reconcile.py:253,281` | `roadmap` (twice — the check body and the `--require-roots` map) |

A subtlety in `STRICT_ROOT_PREFIXES`: a prefix is strict only in a tree that has that root
(`_present_strict_prefixes()`). Rename the roots without renaming the constant and nothing goes
red — the checks simply stop checking. That silent-disarm is the failure mode to test for, not
a broken-link report.

### Absorb measurement into `evals/`

`ab-protocol.md` and `design/stage-benchmarks/{protocol,stage-map}.md` → `evals/protocols/`;
`evals/<skill>/canaries.yaml` → `evals/canaries/<skill>.yaml`. `evals/` holds **nine** tracked
per-skill folders today, one `canaries.yaml` each: application-tracker, ask-me-anything,
behavioral-interview-prep, company-research, email-assistant, github-workflow,
interview-calendar, job-search, resume-writer. (`evals/coding-interview-cleanup/` exists on disk
but is empty and untracked — git carries no empty directories, so it is local residue, not a
tenth folder.) `rubrics/` and `results/` stay. The *rationale* docs stay in `docs/designs/`.

### The rest

- `tmp/` → `local/`, updating the root `.gitignore`, `handbook/file-organization.md`'s scratch
  rule, and `AGENTS.md`'s "Scratch & Temporary Files" bullet (which names `tmp/ats_scripts/`,
  `tmp/web_artifacts/`, `tmp/scratch/`). Nine tracked `SKILL.md` files name `tmp/` — heaviest
  are `job-search` (15), `search-recall-audit` (10), `github-workflow` (7).
- **Same PR:** `.github/workflows/ci.yml` — it carries 16 executed path pins, of which exactly
  one moves in this phase (`automation/maintenance/gardener/tests`); check the other 15 rather
  than assuming. `.github/pull_request_template.md:12` pins
  `automation/maintenance/gardener/gardener.py`.
- Write the superseding ADR for the `docs/` reversal into `memory/decisions/` — the prior
  decision is recorded in `handbook/file-organization.md` ("the former generic `docs/` was
  dissolved into `handbook/` + `design/`").

**Green gate:** full gate command + export dry-run + `instruction_budget.py --strict`. Prove the
silent-disarm case explicitly: after the move, plant a genuinely broken backticked ref in a
`docs/handbook/` doc and confirm `verify_links.py` still fails on it.

---

## Phase 5 — the lifetime taxonomy inside `private/`

**Blocking preconditions:** phases 0 and 4 merged (both done). **Q5 and Q6 answered** —
answered: rendered artifacts stay in the application folder and the *user* may delete a rejected
application (an agent never does); handovers are local-only.

Target tree: [README.md](README.md#the-private-overlay). 805 tracked private files move
(everything outside `applications/`, plus `applications/0_profile` and
`applications/1_discoveries`); `applications/<status>/<slug>/` keeps its path.

### Most of this is a `config.yaml` edit, not a code edit

Phase 0's accessors changed the shape of this phase. Work through the move table asking "does a
`paths.*` key already exist?" first.

| From | To | Config key, or the code change |
|---|---|---|
| `applications/0_profile/profile` | `me/` | `paths.profile_md` |
| `applications/0_profile/baseline` | `me/` | `paths.baseline_yaml` — but read [`tasks/0_backlog/2026-07-29-baseline-path-diverges-from-candidate-dir`](../../tasks/0_backlog/2026-07-29-baseline-path-diverges-from-candidate-dir/task.md) first: its default is config-dir-relative, not `candidate_dir()`-derived |
| `templates/resume/reference.docx` | `me/resume/reference.docx` | `paths.reference_docx` |
| `applications/0_profile/company-levels.yaml` | `market/logs/` | `paths.company_levels_yaml` — **keep the file whole**, 27 YAML anchors cannot shard per company |
| `applications/0_profile/calendar.md` | `me/interviews/calendar.md` | `paths.calendar_md` (already first-class since phase 0) |
| `applications/1_discoveries/` | `market/scans/{current,archive}/` | `paths.discoveries_dir` covers `current/`; **the `archive/` tier is new structure** — the gardener's discovery-expiry routine needs the second directory |
| `job-search/blacklist.yaml` | `market/` | `paths.blacklist_yaml` |
| `interviews/behavioral/story-bank/` | `me/interviews/stories/` | `paths.story_bank_dir` for the location — **but** see the display-key trap below |
| `job-search-profiles/` | `market/searches/` | `paths.search_profiles_dir` |
| `interviews/company-specific/<c>/company-info/` | `companies/<key>/research/` | `paths.companies_root`; 282 files, mechanical |
| `data/` | `store/` | `paths.data_root` / `$JOBHUNT_DATA_ROOT`, **plus** the nine ignore patterns in `private/.gitignore` in the same commit |
| `applications/0_profile/tailoring-card.md` | `me/` | **code** — no config key; see below |
| `applications/0_profile/{applications-log,company-search-log}.yaml` | `market/logs/` | **code** — no config key; see below |
| `interviews/behavioral/question-bank/{README,_general_*,sources,tests}` | `me/interviews/questions/` | mechanical; 55 tracked files in the question bank total |
| `interviews/behavioral/question-bank/<company>-*.md` | `companies/<key>/derived/behavioral.md` | **code** — these are build outputs; `skills/behavioral-interview-prep/scripts/answer_bank.py` must learn cross-tree targets |
| `interviews/common-message-replies/` | `me/interviews/replies/` | mechanical, 2 files; no script names this path |
| `interviews/company-specific/<c>/coding/` | `companies/<key>/coding/` | 163 files across 24 companies. An interview-running firm is a company too — it gets its own `companies/<key>/` |
| `interviews/company-specific/TODO/` | keep as-is | an **untracked** screenshot inbox two private skills poll; moving it orphans them |
| `benchmark/`, `config.benchmark.yaml`, `evals/` | `evals/{fixtures,runs,canaries}/` | the benchmark config resolves its paths relative to its own directory, so moving it relocates the whole overlay-derived path family with it — see [`memory/facts/overlay-root-follows-the-active-config.md`](../../memory/facts/overlay-root-follows-the-active-config.md) |
| `docs/harness-engineering…` | `docs/` | **code** — `automation/maintenance/gardener/_common.py:32` `DESIGN_DOC` is a literal |
| `cursor-rules/private-skills.mdc` | `skills/` | mechanical |
| `history/` (both repos) | `private/local/history/` | **code** — see the reconciler note below |

### The four code changes this phase cannot avoid

1. **The card and the two skip-logs must stop sharing one parent.** `tailoring_card_path()`,
   `applications_log_path()` and `company_search_log_path()` are hard-derived as
   `candidate_dir() / <FILENAME>` with no `paths.*` key of their own
   (`automation/shared/config.py:444-456`). This phase sends the card to `me/` and the logs to
   `market/logs/`, which one `candidate_dir` cannot express. Give each its own config key (or
   re-derive the logs from a new `market` root), then re-vendor — every `config.py` change is a
   five-file change plus `sync_vendored.py --check`.
2. **`search_jobs.profile_dir()` still returns its first candidate when no probe holds a log**
   (`skills/job-search/scripts/search_jobs.py:158-181`). Phase 0 improved it — it now probes
   `config.profile_md_path().parent` and `config.candidate_dir()` before the two literal layout
   names — but it still looks for a *directory containing a log file*, and after this move no
   probe contains one. Both the already-considered and recently-searched skips would switch off
   silently. Fix it to read `config.applications_log_path()` / `config.company_search_log_path()`
   directly. Phase 6 depends on the same function.
3. **The story bank has a display key as well as a location.**
   `skills/resume-writer/scripts/build_tailoring_card.py:78` and
   `automation/maintenance/gardener/card_staleness.py:41` both carry
   `STORY_BANK_REL = "interviews/behavioral/story-bank"` — the literal a card's header records
   next to the directory's sha256. The on-disk location already comes from
   `config.story_bank_path()`, so the hash will be right; change one display key and not the
   other and every card reads permanently stale. Change both, in one commit, or leave both.
4. **`history/` leaving the tracked tree re-points the reconciler.** The `handover-present`
   check keys on `history/conversations`, and `CHECK_ROOTS` maps it to that path
   (`automation/reconcile/reconcile.py:281`). The maintainer `pre-commit` runs
   `--require-roots`, so moving `history/` without updating both would fail every subsequent
   commit.

### What is already done for you, and what is not

The leak guard needs **no edit for this phase**: `check_public._DENY_TREES` already denies
`store/`, `me/`, `companies/` and `market/` at the public root, and
`test_deny_trees_are_append_only` locks them in place. The `.gitignore` coupling test
(`test_every_root_anchored_gitignore_product_rule_is_denied`) reads the **public** repo's
`.gitignore`, which has three root-anchored rules today (`/applications/`, `/interviews/`,
`/.agents/inputs/`); the nine store ignore patterns this phase rewrites live in
`private/.gitignore` and are outside that test's reach. So the coupling only bites if this phase
also adds a root-anchored rule to the public `.gitignore` — which it should not need to, since
`private/` is ignored wholesale.

What is *not* done: renaming `data/` → `store/` without simultaneously rewriting all nine
patterns in `private/.gitignore` un-ignores 83,491 files / 450 MB, 37,614 of them under
`data/email/`. Same commit, mechanical sed, verified with `git -C private check-ignore`.

### Judgment calls and links

**Roughly four dozen `interviews/` files are genuine judgment calls, not mechanical moves** —
flat `coding/*.py` files needing a problem folder and a company-vs-`me/interviews/practice/`
call, a `product-sense/` round type the schema does not model (15 files), cross-problem PDF
aggregates, and one loose outreach draft. Route each through the owner rather than guessing.
(This count was estimated when the plan was written and has not been re-derived; treat it as an
order of magnitude, and recount before promising a completion date.)

**244 relative markdown links inside `interviews/` are covered by no checker** —
`verify_links.py`'s `SKIP_PREFIXES` skips `interviews/` and `private/interviews/`. Fix them in
this PR and remove those two entries. Note what removing them exposes: the new private roots
(`me/`, `companies/`, `market/`, `store/`) are *not* in `SKIP_PREFIXES`, so once they exist, any
doc naming `private/me/…` falls through to `OVERLAY_PREFIX` and **is** verified whenever the
overlay is mounted. That is the desired end state; it also means the docs have to be right the
first time.

Then re-point every `paths.*` in `config.yaml`.

**Green gate:** `git -C private check-ignore` returns IGNORED for a fixed canary list covering
all nine store patterns; every gardener routine runs; `status.py` reports the same pipeline as
before; level enrichment exercised; the tailoring card rebuilds **with its stories**; a bare
`--profile <label>` still resolves the benchmark fixture.

---

## Phase 6 — the skip-log becomes authoritative

**Blocking preconditions:** phase 5 merged.

`skills/application-tracker/scripts/status.py:1954` `sync_log()` still does
`APPLICATIONS_LOG.write_text(...)` at line 1967 — a wholesale regeneration from a scan of the
application folders. So deleting a rejected application and re-syncing drops its rows and
job-search re-surfaces the posting as fresh. This is the reason phase 5's "applications are
disposable" is unsafe on its own. (Phase 0 changed *where* the file is found —
`status.py:152` is now `config.applications_log_path()` — but not *how* it is written.)

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
- `search_jobs.profile_dir()` is the shared hazard with phase 5. If phase 5 fixed it to read
  `config.applications_log_path()` directly, this phase inherits a working accessor; if phase 5
  deferred it, fix it here **before** changing the file format, or the skips are already off and
  the proof below will pass for the wrong reason.

**Green gate:** delete a rejected application (as the user would), re-run search, confirm the
posting does **not** resurface.

---

## Phase 7 — the company key

**Blocking preconditions:** phase 5 merged, and the key-assignment approach decided (filed
non-blocking as its own task; default is one proposal PR).

242 application folders carry **213 distinct free-text company strings**; `registry.canonical()`
resolves only 119 — **94 unresolvable, 44%** (re-measured 2026-07-29; unchanged since the plan
was written). The unresolvable set breaks into four recurring shapes. The private tree has live
instances of each; **naming them here would put the owner's application list in the public tree,
which is the leak this design exists to prevent** — and which the review gate caught once
already (commit `ef2d0a3`). Use the shape, never the instance.

| Shape | Example form |
|---|---|
| bare name vs. name + legal suffix | `<Name>` / `<Name> Ltd.` |
| bare name vs. name + parenthesised legal entity | `<Name>` / `<Name> (<LegalEntity>)` |
| bare name vs. name + category word | `<Name>` / `<Name> AI` |
| two folders, same employer, different slug prefix | `<name>-<role>-<date>` twice |

- `companies/_index.yaml`: `key → {display, aliases[], parent, kind}`. `kind` distinguishes an
  employer from an interview-running firm (one that runs the loop on a client's behalf and has
  its own question set); `parent` handles subsidiaries and joint ventures — a cloud arm under
  its parent, a regional JV under the global brand, an acquired product under the acquirer.
- `meta.yaml` gains `company_key` alongside the human `company:` string — 242 edits.
- Retire the other three alias registries (`companies.yaml` `aliases:`,
  `company-search-log.yaml` per-row `aliases:`, `company-levels.yaml` per-company `aliases:`)
  by generating them from `_index.yaml` or deleting them.
- Reconciler check: every `company_key` resolves; no two keys share an alias. It belongs in
  `CHECKS` with an entry in `CHECK_ROOTS` (`automation/reconcile/reconcile.py:265,281`) so it
  no-ops in the published tree like every other process check — a check that hard-fails without
  the overlay turns the exported repo's CI red.
- `skills/email-assistant` emits `durable: true|false` per `timeline.md` entry, and a `promote`
  command moves flagged entries into `companies/<key>/`. Without this the durable/disposable
  split degrades every time the assistant runs. There are 135 `notes.md` files to rename to
  `timeline.md`.
- This phase's PRs will be large and will name companies in their diffs. Rule 4's ledger row
  applies per commit, and the advisory company detector is likely to fire — expect
  `reviewed_by: human` rows here more than anywhere else in this plan.

---

## Phase 8 — instruction surface

**Blocking preconditions:** phases 2, 4 and 5 merged (4 is done), and
[`tasks/0_backlog/2026-07-28-slim-company-research-skill`](../../tasks/0_backlog/2026-07-28-slim-company-research-skill/task.md)
merged.

- **`skills/company-research/SKILL.md` is still at 595 lines against the hard 600-line budget in
  `automation/metrics/instruction_budget.py`** (re-measured 2026-07-29 — unchanged). Five lines
  of headroom, and this phase adds path references. The slimming PR lands first or this phase
  cannot commit, because `automation/hooks/pre-commit` runs `instruction_budget.py --strict`.
- `AGENTS.md`: the private-tree map, routing into `private/`, the new guardrails. It is at 307
  lines against a 500-line budget, so there is room.
- **Every one of the 11 public `SKILL.md` files names a path that phase 2 or phase 5 moves** —
  the old "8 of 12" count predates both the `github-workflow` skill and phase 4's removal of the
  two private skill trees from `skills/`. Split by which phase does the moving:

  | Skill | phase-2 paths (`automation/maintenance/`, `handbook/`, `design/`, `roadmap/`, `tmp/`) | phase-5 paths (`0_profile`, `interviews/`, `job-search-profiles/`, `data/`) |
  |---|---:|---:|
  | search-recall-audit | 19 | 1 |
  | job-search | 15 | 0 |
  | gardener | 11 | 0 |
  | github-workflow | 7 | 0 |
  | behavioral-interview-prep | 2 | 9 |
  | ask-me-anything | 3 | 4 |
  | company-research | 3 | 1 |
  | email-assistant | 3 | 0 |
  | resume-writer | 1 | 3 |
  | application-tracker | 2 | 0 |
  | interview-calendar | 1 | 0 |

  The two private skills (`private/skills/coding-interview{,-cleanup}/SKILL.md`) name one each.
- **7 handbook docs**, not 5, name `private/`: `private-overlay.md` (45 lines),
  `public-private-split.md` (9), `repo-map.md` (6), `architecture.md` (4),
  `command-cookbook.md` (3), `memory-map.md` (2), `configuration.md` (1).
- `examples/` reshaped to mirror the private tree (`me/`, `companies/`, `applications/`,
  `store/`), fixing the two violations it carries today: `examples/data/` is a generic bucket
  and `examples/templates/` collides with the root `templates/`. `examples/data` is one of
  `ci.yml`'s 16 executed path pins (`automation/store/validate_store.py examples/data
  --check-fixture-size`) — same PR.
- This is a "large" edit under the risk-based eval gate — **canaries run for every touched
  skill**, recorded in `evals/results/`. Nine of the 11 public skills have a canary set;
  `gardener` and `search-recall-audit` have none, so an edit to those two is covered by the
  written rationale rule in [`evals/README.md`](../../evals/README.md), not by a run.

---

## Verified facts and hazards

Re-measured 2026-07-29 against `main` at `19d0829`. Rows marked **historical** describe a state
that no longer exists and are kept only so a reader of an older branch or PR is not confused.

| Fact | Value | Was |
|---|---|---|
| Public tracked files | 712 | 649 |
| Private tracked files | 3,158 (applications 2,403 · interviews 535 · benchmark 112) | 3,138 (2,401 · 518 · 112) |
| Private files that actually move | 805 — `applications/<status>/` keeps its path | ~782 |
| `notes.md` → `timeline.md` | 135 renames | 133 |
| `interviews/company-specific/*/company-info/` | 282 files across 24 companies | 265 |
| `interviews/company-specific/*/coding/` | 163 files | 151 |
| Relative markdown links inside `interviews/` | 244 | ~300 |
| Literal `private/` in public files | 462 lines across 115 files | 241 across 84 |
| `0_profile` in tracked files | 41 files, but only 10 in executable code (5 `config.py` copies, `search_jobs.py:92`, 4 test fixtures); the rest is prose | 15 files — **historical**, measured before phase 0 replaced the idiom with accessors |
| `parents[N]` under `automation/maintenance/` | 9 occurrences, 5 of which break on the phase-2 move | 8 |
| `.venv/bin/python` in docs | 294 occurrences (unchanged by this plan) | 240 |
| `private/data/` | 450 MB, 12 tracked files, 9 ignore patterns in `private/.gitignore` | 432 MB, 12, 9 |
| Un-ignoring risk | renaming `data/`→`store/` without the sed exposes **83,491 files**, 37,614 of them under `data/email/` | 82,318 files, 36,465 raw email |
| Application folders / distinct company strings / resolvable | 242 / 213 / 119 (94 unresolvable, 44%) | same |
| `skills/company-research/SKILL.md` | 595 lines against a 600 budget | same |
| Public skills | 11 (`github-workflow` added 2026-07-29); runtime lists 13 with the two private ones | 10 / 12 — **historical** |
| Per-skill canary sets | 9 tracked folders, 4–8 canaries each; `gardener` and `search-recall-audit` have none | "8 folders holding one file each; one is empty" — **historical** |
| `verify_links.py` reference sources | 264 tracked `.md` files | 23 — **historical**, fixed in phase 0 |
| `check_public._DENY_TREES` | 11 entries, already including `store/`, `me/`, `companies/`, `market/` | 5 regexes — **historical** |
| `ci.yml` executed path pins | 16, of which 1 moves in phase 2 | "12 pinned paths" |
| Inbound public→private symlinks | 0 | 8 — **historical**, removed in phase 4 |

**Hard hazards:**

- `git clean -ffdx` in the public repo **deletes the entire private repo** (plain `-fdx` skips
  it: "Would skip repository private/"; `-ffdx`: "Would remove private/").
- `git add -f private/` — trailing slash — stages private files with exit 0 and no output. The
  phase-0 pre-commit hook now rejects this, but only at commit time.
- `git stash -a` inside `private/` swallows `local/` and the 450 MB store into a git object.
  Use `-u`.
- `automation/vendoring/sync_vendored.py` mirrors `automation/shared/**` into 4 skills
  byte-identically. Every `config.py` edit is a 5-file change plus a drift check.
- Renaming a root that a checker names in a constant **disarms the checker instead of breaking
  it**. `verify_links.py`'s `_present_strict_prefixes()` and the reconciler's `CHECK_ROOTS`
  no-op on a missing root by design. After any rename, prove the check still fails on a planted
  defect; a green run is not evidence.

**Pre-existing breakage to fix opportunistically (file, don't silently repair):** a job-search
profile references `interviews/common-message-**relies**/` (typo), and a benchmark fixture
symlink points at an uncompressed target that exists only as `.gz`. The third item on this list
— a benchmark profile that could not be bootstrapped — was closed on 2026-07-29 (commits
`eb7f07c`, `19d0829`): there was no regression, because `overlay_root()` follows the active
config, so the benchmark config finds its own fixture profile with no symlink at all.

> Never spell a personal profile's real filename in this tree. Phase 4 removed the last path
> that did.

## Human questions / additional tasks

<!-- Free space. -->
