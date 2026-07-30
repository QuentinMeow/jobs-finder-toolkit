# Execution plan

The implementation spec for [the workspace layout](README.md). Written for an agent that has
read `AGENTS.md` and nothing else about this design.

**Status: phases 0, 1, 2, 3 and 4 are merged into `main`; phases 5, 6, 7 and 8 are not started.**
All five are recorded below as short records — what they changed and what the remaining phases may
now rely on — not as instructions. The phase-0/3/4 figures were re-measured on 2026-07-29 against
`main` at commit `19d0829`, the phase-2 figures against the phase-2 stack before it merged;
re-measure anything you are about to depend on, because the tree moves under this plan faster
than the plan does.

**Phase 5 is not the next thing to start.** The owner decided on 2026-07-29 that the link-checker
repair lands first, because phase 5's largest verification step is unverifiable until it does —
[why, in one paragraph](#the-link-checker-lands-before-this-phase-not-after).

Target layout: [README.md](README.md). Gate spec: [review-gate.md](review-gate.md).
Topology decision: [`memory/decisions/workspace-layout-public-root-plus-review-gate.md`](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md).

## How to work this plan

1. **One phase per PR pair.** A phase that touches both repos lands as two PRs that merge
   together; neither half merges alone.
2. **The PR that moves a path updates every literal naming it.** Do not defer path fixes to a
   later phase — that is what made an earlier version of this plan unexecutable.
3. **Every `git mv` is its own commit**, separate from content edits, so `git log --follow`
   survives — **with the correction phase 2 forced on it**: a move commit may also carry the
   checker constants that name the moved path, and nothing else. The rule as originally written
   is unexecutable wherever a moved root is named by a checker constant, because
   `automation/hooks/pre-commit` runs `reconcile.py --check --require-roots` and a move-only
   commit that retires such a root cannot be committed at all. `--follow` survives the combined
   commit anyway: what the constants change is *other files'* references, not the moved files'
   own content. Full finding in [the phase-2 record](#merged-phase-2--public-side-cleanup).
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
  && .venv/bin/python automation/gardener/verify_links.py \
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
  mounted (`JOBHUNT_REQUIRE_REAL_CONFIG=1` forces the raise everywhere). The owner confirmed this
  shape on 2026-07-29 — it is now settled, not a default awaiting an answer — and the reasoning,
  including the residual it accepts (a mounted `private/` is a proxy for intent, so temporarily
  removing the overlay falls back silently again), is in
  [`memory/decisions/config-discovery-example-fallback.md`](../../../memory/decisions/config-discovery-example-fallback.md).
  The queue item that carried the question is closed and deleted.
- **`SKILL.md` frontmatter is the only source of skill visibility.**
  `automation/publish/sync_skill_manifests.py` derives the public set at runtime;
  `export_public.py`, `.claude-plugin/marketplace.json`, `.claude/skills/*` and `.cursor/skills/*`
  all follow it, and the reconciler's `skill-manifests` check fails when they disagree.
  `search-recall-audit` ships as a result.
- **The exporter enumerates through `git ls-files`**, warns on an allowlisted directory that
  resolves to nothing, and refuses under `--strict`. `ALLOWLIST_DIRS` now carries
  `automation/store`, and the root files `CLAUDE.md`, `CONTRIBUTING.md`, and
  `automation/bootstrap_overlay.py`, so the exported repo's own CI is green. (Phase 2 later
  retired the `handbook` and `design` entries in favour of `docs`.)
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
  open — and `STRICT_ROOT_PREFIXES` covers the human-doc and process roots (phase 2 re-spelled
  the first three, so they read `docs/handbook/ docs/designs/ docs/roadmap/ evals/ templates/
  memory/ tasks/ message-queue/ history/` today), each strict only in a tree that actually has
  that root. `check_symlinks()` fails when it finds zero link roots.
- **The reconciler gained `--require-roots`** (used by the maintainer pre-commit) while plain
  `--check` keeps its documented missing-root no-op, so the published repo's CI stays green.
  `file_retries()` no longer conjures `message-queue/needs-agent/retries` on a clean run.
- **The private overlay has hooks**: `automation/hooks/overlay-pre-commit` and
  `overlay-pre-push`, installed by `automation/bootstrap_overlay.py`. Whether a private-scope
  reconciler also runs is open in
  [`message-queue/needs-human/decisions/private-scope-reconciler.md`](../../../message-queue/needs-human/decisions/private-scope-reconciler.md);
  the default is no, and the hook reports the skip. The owner **deliberately left this
  undecided** on 2026-07-29 — it is deferred, not overlooked, so do not re-ask it; the default
  path stands until the owner returns to it.

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

## Merged: phase 1 — orphans

Both orphaned items are refiled inside the overlay and `private/todo/` and
`private/email-assistant/` no longer exist. The retired-`todo/` task went to
`private/tasks/4_done/2026-07-22-yoe-adjacent-context-cross-contamination/`, and the stray review
went to the overlay's review queue reformatted to `templates/queue/review.md`.

**This plan told the phase to file that task into `0_backlog`, and that was wrong.** The file's
own front matter said `Status: done` and it carried a resolution with a confirmed root cause and
shipped fix; filing it as backlog would have resurrected finished work. Every claim in it was
re-checked against the tree before it was recorded as done — the fix regex, three named
regressions, two corpus cases, and a vendored copy matching its canonical module line for line.
One definition-of-done bullet was never run and is recorded as not run rather than quietly
ticked. The lesson for the phases that follow: **a plan written before reading the file can be
wrong about the file, so read it before executing the instruction.**

`tmp/` was classified, not emptied. Nothing was deleted. Most of it is owner data — one folder
holds complete application folders with real employers and the owner's name in the filenames, and
another holds interview screenshots — so the sweep's output is a decision item in the overlay's
review queue listing what is safe to remove, what is regenerable, and what only the owner may
touch. The never-delete guardrail makes classification, not deletion, the deliverable here.

**This phase's public half was not empty after all**, contrary to what this plan asserted. The
sweep found that three durable records — two `evals/results/` rows and one private task — cite
snapshot files under `tmp/` that no longer exist. A record that cites scratch is evidence with an
expiry date and no expiry signal. That is now a rule in
[the scratch section of the file-organization handbook](../../handbook/file-organization.md#scratch--temporary-files),
and it binds phases 5 through 8, whose verification steps are exactly the kind of record that
tends to reach for a path under `tmp/`.

**What phase 2 inherits:** the `tmp/` → `local/` rename moves a tree that still contains the
owner's application data, so it is a move, never a clean. The inventory is in the overlay review
item.

## Merged: phase 2 — public-side cleanup

Four stacked PRs, commits `031e05d`…`fc0180b`. `automation/maintenance/` split three ways (38
files); `handbook/`, `design/` and `roadmap/` consolidated under one `docs/` parent (135); the
measurement docs and the nine per-skill canary folders absorbed into `evals/` (30); the
gitignored scratch root renamed `tmp/` → `local/` (45). No behaviour changed anywhere — every
commit is a move plus the literals naming it. What a later phase needs to know:

- **`automation/` has no generic bucket left.** `automation/gardener/`,
  `automation/search-recall-audit/` and `automation/company-levels/` replace
  `automation/maintenance/`. Six of the nine `parents[N]` depth constants became a local upward
  `.git` walk — the five that break on the move, plus `import_company_levels.py`'s `parents[2]`,
  which was correct only by coincidence of depth. The three surviving `parents[1]` in the
  gardener tests are `sys.path` bootstraps relative to the tests directory and are genuinely
  move-invariant; each now says so in a comment, and `test_store_report.py` grew its own
  `_find_repo_root()` for the repo-root half that was **not** move-invariant.
- **The three human-read roots are `docs/handbook/`, `docs/designs/` and `docs/roadmap/`**, and
  this design family moved with them. The `CLAUDE.md → AGENTS.md` shim survived as a tracked
  symlink — `git ls-files -s docs/designs/CLAUDE.md` still reports mode `120000`. The published
  file set is unchanged: `export_public.py --strict` emits 566 files both before and after. The
  superseding ADR is
  [`memory/decisions/docs-parent-for-the-human-read-trees.md`](../../../memory/decisions/docs-parent-for-the-human-read-trees.md).
- **All measurement lives under `evals/`**: `protocols/`, `canaries/<skill>.yaml`, `rubrics/`,
  `results/`. Nine canary sets and 50 canaries before and after, every file byte-identical across
  the move. (`canaries/email-assistant.yaml` was edited one PR later by the scratch-root rename;
  that is the only canary byte that changed in the whole phase.)
- **The scratch root is `local/`.** One `mv` of an untracked tree: 102 files before, the same 102
  paths after, ~1.2 GB. Nothing tracked moved; the `.gitignore` rule, both link-checker skip
  lists and every default write path moved with it.

### What this phase learned the hard way

Four of the seven findings are corrections to this plan's own instructions and three are defects
in the tree that the phase uncovered. They are recorded as errors rather than quietly folded into
the text above, because the same shapes recur in phases 5 through 8.

**Rule 3 is unexecutable where a moved root is named by a checker constant.** The rule as written
says every `git mv` is its own commit, separate from content edits. But `automation/hooks/pre-commit`
runs `reconcile.py --check --require-roots`, which asserts that the `roadmap` root exists — so a
commit that moves `roadmap/` and nothing else **cannot be committed at all**. The move and the
constants naming it have to land together. `git log --follow` survives that anyway, because what
the constants change is *other files'* references, not the moved files' own content.
[Rule 3](#how-to-work-this-plan) now carries the correction: a move commit may also carry the
constants that name the moved path, and nothing else.

**The "every constant that has to move" table was incomplete.** It listed the two `roadmap`
mentions in `automation/reconcile/reconcile.py` and stopped. It missed
`automation/reconcile/tests/test_reconcile.py:82`, which carries a bare `"roadmap"` inside a
`make_roots(skip=…)` tuple with **no trailing slash** — so no regex built from the table's
`roadmap/` form finds it. Left alone it would have created a `docs/roadmap/` directory in the
fixture while the skip list still named `roadmap`, silently changing what
`test_plain_check_still_passes_on_the_same_tree` tests: the test would still have passed, and it
would have stopped testing the missing-root no-op it exists to pin.

**`git grep "automation/maintenance"` does not find the whole surface.** Four files name the
bucket as a bare word rather than a path: `AGENTS.md`, `README.md`,
`skills/ask-me-anything/SKILL.md`, and `docs/handbook/file-organization.md` — where
`maintenance/` was cited as *an example of a good purpose-named folder*, which is the exact
opposite of what this phase establishes by dissolving it.

**Every runtime scratch write path spelled the root as a bare quoted `"tmp"` segment, not
`tmp/`.** Nine such literals existed across `automation/` and `skills/` — the two
search-recall-audit `DEFAULT_OUT`s, its snapshot and refilter output roots, job-search's snapshot
cache and both filter-variant report defaults, and the link checker's own
`_FALLBACK_SKIP_DIRS`. A word-boundary sweep for `tmp/` sees none of them. Had the phase run that
sweep alone, every document would have said `local/` while every script silently recreated `tmp/`
beside it, outside the new ignore rule.

**`automation/gardener/verify_links.py` never checks markdown links.** It only checks
**backticked** refs: `_is_checkable()` rejects any token containing parentheses, so every
`[text](path)` link in the repo is unverified. There are **31 broken relative markdown links** at
this stack's tip and there were **36** at its base — but the two sets do not overlap at all, so
that is not stability, it is churn the gate cannot see. PR 02's move broke a fresh batch that was
caught and repaired only because a throwaway checker was written for the purpose; the gate
reported "references: all resolve" the entire time. Filed as
[`tasks/3_in-review/2026-07-29-verify-links-misses-markdown-and-nonstrict-roots`](../../../tasks/3_in-review/2026-07-29-verify-links-misses-markdown-and-nonstrict-roots/task.md).

**A backticked ref whose first path segment is in no strict root prefix is invisible** — not
broken, not advisory, not counted in any skip tally. It falls out of `check_references()` at the
"not strict, not absent" fall-through (`verify_links.py:249-252`), where a token that resolved
under no base is simply dropped. Proved on this tree: a planted
`` `handbook/definitely-not-a-real-file.md` `` produced "references: all resolve" and exit 0,
while the same ref written `` `docs/handbook/…` `` produced "BROKEN references: 1" and exit 1.
**This is the silent-disarm this plan predicted, in a form it did not predict:** not the checker
no-opping wholesale, but individual references dropping out of its universe one at a time as
their root is renamed. 76 refs at the four retired root names survive across 24 record files and
are now unmonitored. This is a pre-existing structural property of the checker rather than
something the moves introduced — but the moves widened its blast radius, and it is filed with the
markdown-link gap above because it is one file, one checker, one class of gap.

**Three pre-existing broken link targets were repaired in passing**, found only because a real
checker was finally run against the tree: `../STYLE.md`, a file that has never existed,
referenced from seven design docs; `PRIVATE_OVERLAY.md`; and `../ARCHITECTURE.md`, which resolved
on macOS only through filesystem case-insensitivity against `handbook/architecture.md` and would
have failed on Linux CI.

**What phase 5 inherits:** a public tree whose roots are final, so the only paths phase 5 changes
are inside `private/` — but it inherits the two hazards this phase proved rather than assumed.
First, `verify_links.py` sees no markdown links at all and drops backticked refs at unrecognised
roots without counting them, so phase 5's plan to remove `interviews/` from `SKIP_PREFIXES` and
fix its 244 relative links will report a clean run whether or not those links are right; run a
real checker or fix the checker first. Second, a checker constant that names a moved root disarms
the check instead of breaking it, and a root can be spelled as a bare quoted segment, a bare word
in prose, or a slashed path — grep all three forms, and prove every moved check still fails on a
planted defect before believing a green gate. Phase 5 also inherits the rule that a durable
record may not cite scratch as its evidence, now with a renamed root: `local/`, not `tmp/`.

---

## Phase 5 — the lifetime taxonomy inside `private/`

> **Done and in review, 2026-07-30.** 747 tracked private files relocated across 32
> commits; the tracked total is unchanged at 3,186 and every relocation is recorded by
> git as a rename. Record and evidence:
> [the task folder](../../../tasks/3_in-review/2026-07-28-workspace-phase-5-lifetime-taxonomy/verification.md).
>
> **Four numbers below are wrong and are corrected there rather than rewritten here.**
> The acceptance figure is **747**, not 825 — 825 counts `history/` (23 files, which this
> phase did not move) plus 55 files whose paths do not change. The interview-link count
> is **261**, not 244. `paths.reference_docx` never pointed at `templates/resume/`. And
> the `archive/` tier is not new structure: `expire_discoveries._archive_dir()` already
> derives the sibling directory, so pointing `discoveries_dir` at `market/scans/current`
> gives it for free.
>
> **Three things the plan expected did not happen, each for a stated reason.**
> `history/` is filed as its own decision instead of being untracked inside a migration.
> The story bank keeps its leaf directory name, because the plan's spelling would have
> forced a 33-line content edit inside files the owner's interview ruling put off limits.
> And `examples/` is left alone — it is phase 8, and two `examples/data` literals are
> pinned in `ci.yml` and an export test.
>
> **The precondition below was necessary but not sufficient, and that only became visible
> once it was met.** The link checker could not read a single file inside the overlay —
> it enumerates with `git ls-files` in the *public* repo — so removing `interviews/` from
> `SKIP_PREFIXES` would have changed which public docs may name those paths and nothing
> else. Overlay enumeration was added to the link-checker PR; with it, removing the skips
> surfaced **126** stale references, all now repaired.

**Blocking preconditions:** phases 0 and 4 merged (both done). **Q5 and Q6 answered** —
answered: rendered artifacts stay in the application folder and the *user* may delete a rejected
application (an agent never does); handovers are local-only. **And, added 2026-07-29 by owner
decision: the link-checker repair merges first** — see [the sequencing note](#the-link-checker-lands-before-this-phase-not-after)
directly below.

Target tree: [README.md](README.md#the-private-overlay). 825 tracked private files move
(everything outside `applications/`, plus `applications/0_profile` and
`applications/1_discoveries`); `applications/<status>/<slug>/` keeps its path. (Re-measured
2026-07-29 evening: the same formula that produced the plan's earlier 805 now produces 825,
because the private tree grew — 3,186 tracked files, of which 2,411 are applications, against
3,158 / 2,403 when the figure was last taken.)

### The link checker lands before this phase, not after

This phase used to be the next thing to start. It no longer is: the owner decided on
2026-07-29 to fix the link checker first — the task
[`tasks/3_in-review/2026-07-29-verify-links-misses-markdown-and-nonstrict-roots`](../../../tasks/3_in-review/2026-07-29-verify-links-misses-markdown-and-nonstrict-roots/task.md)
merges before any phase-5 commit.

The reason is that one of this phase's own steps is unverifiable without it. Phase 5 removes
`interviews/` from `verify_links.py`'s `SKIP_PREFIXES` and repairs the 244 relative markdown
links inside that tree — and `verify_links.py` does not check markdown links at all
(`_is_checkable()` rejects any token containing parentheses, so every `[text](path)` link in the
repo is unread). Run in today's order, that repair would report success whether or not a single
link actually resolved, which is precisely the silent-disarm failure this whole design exists to
remove. Fixing the checker first converts phase 5's largest verification step from unverifiable
to verifiable. Running it second means doing the link work twice: once blind, once again after
the checker can finally see it.

### Most of this is a `config.yaml` edit, not a code edit

Phase 0's accessors changed the shape of this phase. Work through the move table asking "does a
`paths.*` key already exist?" first.

| From | To | Config key, or the code change |
|---|---|---|
| `applications/0_profile/profile` | `me/` | `paths.profile_md` |
| `applications/0_profile/baseline` | `me/` | `paths.baseline_yaml` — but read [`tasks/0_backlog/2026-07-29-baseline-path-diverges-from-candidate-dir`](../../../tasks/0_backlog/2026-07-29-baseline-path-diverges-from-candidate-dir/task.md) first: its default is config-dir-relative, not `candidate_dir()`-derived |
| `templates/resume/reference.docx` | `me/resume/reference.docx` | `paths.reference_docx` |
| `applications/0_profile/company-levels.yaml` | `market/logs/` | `paths.company_levels_yaml` — **keep the file whole**, 27 YAML anchors cannot shard per company |
| `applications/0_profile/calendar.md` | `me/interviews/calendar.md` | `paths.calendar_md` (already first-class since phase 0) |
| `applications/1_discoveries/` | `market/scans/{current,archive}/` | `paths.discoveries_dir` covers `current/`; **the `archive/` tier is new structure** — the gardener's discovery-expiry routine needs the second directory |
| `job-search/blacklist.yaml` | `market/` | `paths.blacklist_yaml` |
| `interviews/behavioral/story-bank/` | `me/interviews/stories/` | `paths.story_bank_dir` for the location, 17 files — **but** see the display-key trap below |
| `job-search-profiles/` | `market/searches/` | `paths.search_profiles_dir` |
| `interviews/company-specific/<c>/company-info/` | `companies/<key>/research/` | `paths.companies_root`; **299** files across 18 company folders, mechanical (the plan's earlier 282 / "24 companies" is stale — re-measured 2026-07-29) |
| `data/` | `store/` | `paths.data_root` / `$JOBHUNT_DATA_ROOT`, **plus** the nine ignore patterns in `private/.gitignore` in the same commit |
| `applications/0_profile/tailoring-card.md` | `me/` | **code** — no config key; see below |
| `applications/0_profile/{applications-log,company-search-log}.yaml` | `market/logs/` | **code** — no config key; see below |
| `interviews/behavioral/question-bank/{README,_general_*,sources,tests}` | `me/interviews/questions/` | mechanical; **36** of the question bank's 55 tracked files (18 `_general_*`, 1 README, 16 under `sources/`, 1 under `tests/`) |
| `interviews/behavioral/question-bank/<company>-*.md` | `companies/<key>/derived/behavioral.md` | **code** — these are build outputs; `skills/behavioral-interview-prep/scripts/answer_bank.py` must learn cross-tree targets. **19** files, and every one's pre-hyphen prefix matches an existing company folder name, so the routing is mechanical (re-measured 2026-07-29) |
| `interviews/common-message-replies/` | `me/interviews/replies/` | mechanical, 2 files; no script names this path |
| `interviews/company-specific/<c>/coding/` | `companies/<key>/coding/` | 163 files across 9 company folders (not 24 — re-measured 2026-07-29). An interview-running firm is a company too — it gets its own `companies/<key>/`. **Moves as-is**: no per-problem folders, no split aggregates — see [what the owner ruled out](#what-the-owner-decided-and-what-that-forbids) |
| `interviews/company-specific/<c>/product-sense/` | `companies/<key>/product-sense/` | 15 files in one company folder; mechanical. Previously flagged as a judgment call because "the schema does not model this round type" — it does not need to: the folder moves whole under its company |
| `interviews/company-specific/<c>/<loose reply draft>` | `companies/<key>/` | 1 file sitting directly inside a company folder; company-specific by location, so it moves with the folder |
| `interviews/company-specific/TODO/` | keep as-is | an **untracked** screenshot inbox two private skills poll; moving it orphans them |
| `benchmark/`, `config.benchmark.yaml`, `evals/` | `evals/{fixtures,runs,canaries}/` | the benchmark config resolves its paths relative to its own directory, so moving it relocates the whole overlay-derived path family with it — see [`memory/facts/overlay-root-follows-the-active-config.md`](../../../memory/facts/overlay-root-follows-the-active-config.md) |
| `docs/harness-engineering…` | `docs/` | **code** — `automation/gardener/_common.py` `DESIGN_DOC` is a literal (the module moved out of `automation/maintenance/` in phase 2; re-derive the line number) |
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
   `automation/gardener/card_staleness.py:41` both carry
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

### What the owner decided, and what that forbids

This plan used to say that "roughly four dozen `interviews/` files are genuine judgment calls,
not mechanical moves", and to route each one through the owner. **That standing item is closed.**
On 2026-07-29 the owner ruled on the whole tree at once: move company-specific material into
company folders, and reorganise nothing else. The estimate is withdrawn rather than refined — it
was never re-derived, and the ruling makes the underlying question moot. Full reasoning and the
counts behind it:
[`memory/decisions/interview-material-moves-by-company-only.md`](../../../memory/decisions/interview-material-moves-by-company-only.md).

**What moves, and why it is mechanical.** Everything under `interviews/company-specific/<c>/` is
company-specific *by construction* — the path says so — so all 478 tracked files there move to
`companies/<key>/`, including the two the plan had flagged as open: the 15-file `product-sense/`
folder and the one loose reply draft. The 19 company-prefixed question-bank files move to their
company as well. The re-measured shape of the tree, taken 2026-07-29 against the overlay:

| Subtree | Tracked files | Where the ruling sends it |
|---|---:|---|
| `interviews/` total | 552 | — |
| `interviews/behavioral/question-bank/` | 55 | splits: 19 company-prefixed → `companies/<key>/`; the other 36 → `me/interviews/questions/` |
| `interviews/behavioral/story-bank/` | 17 | `me/interviews/stories/` |
| `interviews/common-message-replies/` | 2 | `me/interviews/replies/` |
| `interviews/company-specific/` | 478 across 25 company folders | all of it → `companies/<key>/` |
| ├ `company-info/` | 299 across 18 of them | `companies/<key>/research/` |
| ├ `coding/` | 163 across 9 of them | `companies/<key>/coding/` |
| ├ `product-sense/` | 15 in one of them | `companies/<key>/product-sense/` |
| └ a loose reply draft | 1 | `companies/<key>/` |

Takeaway: the only files whose destination the ruling does not settle outright are the 55
non-company ones in the first three rows, and even there the destination column is an
assumption — see the open question below.

**What the ruling forbids.** The owner's standard is "don't touch anything else unless it's an
obvious mistake", and that rules out every *content* reorganisation this plan previously
proposed inside `interviews/`:

- **No per-problem folders.** Flat `coding/*.py` files stay flat under their company.
- **No round-type schema for `product-sense/`.** The folder moves whole; nothing models it.
- **No breaking up cross-problem PDF aggregates.** A file that spans several problems stays one
  file.
- **No company-vs-`me/interviews/practice/` re-homing call**, because there is no such call left
  to make: location under `company-specific/<c>/` is the answer.

An agent may still fix something *plainly* broken in passing — a typo'd path, a file sitting in
the wrong company's folder — but may not restructure. If a case needs argument to justify, it is
not an obvious mistake, and the answer is to leave it and file it.

**The one thing this left open was settled on 2026-07-29.** "Don't touch anything else" read two
ways for the 55 non-company files: (a) do not *reorganise* them, but still *relocate* them to
their taxonomy home, or (b) leave `interviews/` where it is entirely. The plan proceeded on (a),
and the owner confirmed (a): the story bank, the general question bank and the shared replies move
to `me/interviews/{stories,questions,replies}/` with nothing inside them altered. The table above
already assumed this, so no step changes — see the amendment in
[the interview-material ADR](../../../memory/decisions/interview-material-moves-by-company-only.md).
**Every one of the 552 interview files now has a named destination**, which is what makes this
phase's interview work schedulable at all.

### Links inside `interviews/`

**244 relative markdown links inside `interviews/` are covered by no checker** —
`verify_links.py`'s `SKIP_PREFIXES` skips `interviews/` and `private/interviews/`. Fix them in
this PR and remove those two entries. Note what removing them exposes: the new private roots
(`me/`, `companies/`, `market/`, `store/`) are *not* in `SKIP_PREFIXES`, so once they exist, any
doc naming `private/me/…` falls through to `OVERLAY_PREFIX` and **is** verified whenever the
overlay is mounted. That is the desired end state; it also means the docs have to be right the
first time.

This is the step the owner's sequencing decision protects. Today the checker reads no
`[text](path)` link at all, so repairing these 244 and then running the gate proves nothing —
which is why [the link checker lands before this phase](#the-link-checker-lands-before-this-phase-not-after)
rather than after it.

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

**Blocking preconditions:** phases 2, 4 and 5 merged (4 is merged; 2 is done and in review), and
[`tasks/0_backlog/2026-07-28-slim-company-research-skill`](../../../tasks/0_backlog/2026-07-28-slim-company-research-skill/task.md)
merged.

- **`skills/company-research/SKILL.md` is still at 595 lines against the hard 600-line budget in
  `automation/metrics/instruction_budget.py`** (re-measured 2026-07-29 — unchanged). Five lines
  of headroom, and this phase adds path references. The slimming PR lands first or this phase
  cannot commit, because `automation/hooks/pre-commit` runs `instruction_budget.py --strict`.
- `AGENTS.md`: the private-tree map, routing into `private/`, the new guardrails. It is at 307
  lines against a 500-line budget, so there is room.
- **Every one of the 11 public `SKILL.md` files names a path that phase 2 or phase 5 moves** —
  the old "8 of 12" count predates both the `github-workflow` skill and phase 4's removal of the
  two private skill trees from `skills/`. Split by which phase does the moving. **The phase-2
  column below is now obsolete:** phase 2 has run, so it retired the `automation/maintenance/`
  token from every skill and re-spelled `handbook|design|roadmap|tmp`, and the counts — and the
  phase-8 estimate built on them — no longer describe any file. Re-measure before starting; filed
  as [`tasks/0_backlog/2026-07-29-refresh-phase-8-instruction-surface-counts`](../../../tasks/0_backlog/2026-07-29-refresh-phase-8-instruction-surface-counts/task.md).
  The phase-5 column still holds.

  | Skill | phase-2 paths (`automation/maintenance/`, `handbook/`, `design/`, `roadmap/`, `tmp/`) — **obsolete** | phase-5 paths (`0_profile`, `interviews/`, `job-search-profiles/`, `data/`) |
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
  written rationale rule in [`evals/README.md`](../../../evals/README.md), not by a run.

---

## Verified facts and hazards

Re-measured 2026-07-29 — the private-tree rows against `main` at `19d0829`, the public-tree rows
against the phase-2 stack's tip `fc0180b`. The `interviews/` rows and the private-tree totals
were re-measured **again** later the same day, when the owner's ruling on that subtree made the
exact shape load-bearing; those rows carry their new value and keep the earlier one in the
"Was" column. Rows marked **historical** describe a state that no longer exists and are kept only
so a reader of an older branch or PR is not confused.

| Fact | Value | Was |
|---|---|---|
| Public tracked files | 718 (566 of them published by `export_public.py`, unchanged across phase 2) | 712 before phase 2 · 649 before phase 0 |
| Private tracked files | 3,186 (applications 2,411 · interviews 552 · benchmark 112) | 3,158 (2,403 · 535 · 112) · 3,138 (2,401 · 518 · 112) |
| Private files that actually move | 825 — `applications/<status>/` keeps its path; the 50 files under `applications/0_profile` (9) and `applications/1_discoveries` (41) still move | 805 · ~782 |
| `notes.md` → `timeline.md` | 135 renames | 133 |
| `interviews/` total | 552 tracked files | 535 |
| `interviews/company-specific/` | 478 files across 25 company folders | not previously measured as a whole |
| `interviews/company-specific/*/company-info/` | 299 files across **18** of those 25 folders | 282 "across 24 companies" — **historical**, and the company count was wrong as well as the file count · 265 |
| `interviews/company-specific/*/coding/` | 163 files across **9** of those 25 folders | 163, glossed elsewhere as "24 companies" — **historical** · 151 |
| `interviews/company-specific/*/product-sense/` | 15 files, all in one company folder | not previously counted as a row |
| `interviews/behavioral/question-bank/` | 55 files: 19 company-prefixed, 18 `_general_*`, 1 README, 16 under `sources/`, 1 under `tests/` | 55 total, unsplit |
| `interviews/behavioral/story-bank/` | 17 files | not previously counted as a row |
| Relative markdown links inside `interviews/` | 244 — **not re-derived** in the 2026-07-29 evening pass; the subtree grew by 17 files since, so treat this as a floor | ~300 |
| Literal `private/` in public files | 471 lines across 120 files | 462 across 115 · 241 across 84 |
| `0_profile` in tracked files | 41 files, but only 10 in executable code (5 `config.py` copies, `search_jobs.py:92`, 4 test fixtures); the rest is prose | 15 files — **historical**, measured before phase 0 replaced the idiom with accessors |
| `parents[N]` under `automation/maintenance/` | 9 occurrences, 5 of which break on the move — **historical**; phase 2 dissolved the directory and converted 6 of the 9 to an upward `.git` walk, leaving 3 move-invariant `parents[1]` in the gardener tests | 8 |
| `.venv/bin/python` in docs | 294 occurrences (unchanged by this plan) | 240 |
| `private/data/` | 450 MB, 12 tracked files, 9 ignore patterns in `private/.gitignore` | 432 MB, 12, 9 |
| Un-ignoring risk | renaming `data/`→`store/` without the sed exposes **83,491 files**, 37,614 of them under `data/email/` | 82,318 files, 36,465 raw email |
| Application folders / distinct company strings / resolvable | 242 / 213 / 119 (94 unresolvable, 44%) — the folder count has since drifted to **243** (2026-07-29 evening); the 213 / 119 pair was **not** re-derived with it, so do not quote the ratio as current | same |
| `skills/company-research/SKILL.md` | 595 lines against a 600 budget | same |
| Public skills | 11 (`github-workflow` added 2026-07-29); runtime lists 13 with the two private ones | 10 / 12 — **historical** |
| Per-skill canary sets | 9 sets, 50 canaries, 4–8 each, now `evals/canaries/<skill>.yaml`; `gardener` and `search-recall-audit` have none | "8 folders holding one file each; one is empty" — **historical** |
| `verify_links.py` reference sources | 271 tracked `.md` files — but **backticked refs only**; `[text](path)` links are unchecked, and 31 of them are broken today | 23 — **historical**, fixed in phase 0 |
| `check_public._DENY_TREES` | 11 entries, already including `store/`, `me/`, `companies/`, `market/` | 5 regexes — **historical** |
| `ci.yml` executed path pins | 16; the one that moved in phase 2 (`automation/gardener/tests`) is repointed, and `examples/data` is the one phase 8 moves | "12 pinned paths" |
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
  defect; a green run is not evidence. Phase 2 found a second, finer-grained form of the same
  hazard: an individual backticked ref whose root prefix is not in `STRICT_ROOT_PREFIXES` is
  dropped at `check_references()`'s fall-through without being counted anywhere, so renaming a
  root disarms every reference still spelled the old way one ref at a time. See
  [the phase-2 record](#merged-phase-2--public-side-cleanup).
- **A root is spelled three ways, and a sweep for one finds neither of the others**: a slashed
  path (`tmp/`), a bare quoted segment in code (`REPO_ROOT / "tmp"`), and a bare word in prose
  ("the `maintenance/` bucket"). Phase 2 hit all three. Grep for each form before believing a
  rename is complete.

**Pre-existing breakage to fix opportunistically (file, don't silently repair):** a job-search
profile references `interviews/common-message-**relies**/` (typo); a benchmark fixture
symlink points at an uncompressed target that exists only as `.gz`; and
`automation/search-recall-audit/store_refilter.py` raises `NameError: prof_label` on its final
print, so the script has never run to completion (broken at `d9aa3cb`, before phase 2 — the split
neither caused nor fixed it). The third item on this list
— a benchmark profile that could not be bootstrapped — was closed on 2026-07-29 (commits
`eb7f07c`, `19d0829`): there was no regression, because `overlay_root()` follows the active
config, so the benchmark config finds its own fixture profile with no symlink at all.

> Never spell a personal profile's real filename in this tree. Phase 4 removed the last path
> that did.

## Human questions / additional tasks

<!-- Free space. -->
